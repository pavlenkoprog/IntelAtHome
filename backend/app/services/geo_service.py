import csv
import io
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

USGS_QUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
EONET_EVENTS = "https://eonet.gsfc.nasa.gov/api/v3/events"
OPENSKY_STATES = "https://opensky-network.org/api/states/all"
ADSB_FEEDS = (
    "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}",
    "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{dist}",
)
ADSB_MIL = "https://api.adsb.lol/v2/mil"
ADSB_SEEDS = (
    (51.50, -0.12),
    (40.70, -74.00),
    (35.68, 139.69),
    (55.75, 37.62),
)
NE_PLACES = "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_50m_populated_places_simple.geojson"
NE_PORTS = "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_10m_ports.geojson"
OPENFLIGHTS = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
MILITARY_HINTS = (
    "air base",
    "airbase",
    " afb",
    "afb ",
    "air force",
    "naval air",
    "raf ",
    "mcas ",
    " nas ",
    "nab ",
    "авиабаза",
)
RAINVIEWER_MAPS = "https://api.rainviewer.com/public/weather-maps.json"
OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
STORM_CODES = {95, 96, 99}

_CATALOGS: dict[str, list[dict]] = {}

_CACHE: dict[str, tuple[float, Any]] = {}


def _cached(key: str, ttl: float, loader):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _CACHE[key] = (now, value)
    return value


def _get_json(url: str, timeout: float = 20.0, params: dict | None = None) -> Any:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "PalantirAtHome/0.1"}) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _get_text(url: str, timeout: float = 30.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "PalantirAtHome/0.1"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _in_bbox(lat: float, lon: float, south: float, west: float, north: float, east: float) -> bool:
    if not (south <= lat <= north):
        return False
    if west <= east:
        return west <= lon <= east
    return lon >= west or lon <= east


def _natural_earth_cities() -> list[dict]:
    if "cities" in _CATALOGS:
        return _CATALOGS["cities"]
    raw = _get_json(NE_PLACES, timeout=30.0)
    items = []
    for feature in raw.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        name = props.get("name") or props.get("NAME") or props.get("NAMEASCII") or "Town"
        pop = int(props.get("pop_max") or props.get("POP_MAX") or 0)
        items.append(
            {
                "id": f"ne-{name}-{lat:.2f}",
                "name": name,
                "kind": "town",
                "lat": lat,
                "lon": lon,
                "pop": pop,
            }
        )
    _CATALOGS["cities"] = items
    return items


def _openflights_airports() -> list[dict]:
    if "airports" in _CATALOGS:
        return _CATALOGS["airports"]
    items = []
    reader = csv.reader(io.StringIO(_get_text(OPENFLIGHTS)))
    for parts in reader:
        if len(parts) < 8:
            continue
        try:
            lat = float(parts[6])
            lon = float(parts[7])
        except ValueError:
            continue
        name = parts[1] or parts[2] or "Airport"
        iata = parts[4] if len(parts) > 4 else ""
        kind = "military" if any(hint in name.lower() for hint in MILITARY_HINTS) else "airport"
        items.append(
            {
                "id": f"apt-{parts[0]}",
                "name": name,
                "kind": kind,
                "lat": lat,
                "lon": lon,
                "iata": iata if iata and iata != "\\N" else None,
            }
        )
    _CATALOGS["airports"] = items
    return items


def _natural_earth_ports() -> list[dict]:
    if "ports" in _CATALOGS:
        return _CATALOGS["ports"]
    raw = _get_json(NE_PORTS, timeout=30.0)
    items = []
    for feature in raw.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or []
        if geom.get("type") == "MultiPoint" and coords:
            coords = coords[0]
        if len(coords) < 2:
            continue
        lon, lat = float(coords[0]), float(coords[1])
        name = props.get("name") or props.get("NAME") or props.get("port") or "Port"
        items.append({"id": f"port-{name}-{lat:.2f}", "name": name, "kind": "port", "lat": lat, "lon": lon})
    _CATALOGS["ports"] = items
    return items


def earthquakes() -> dict:
    def load():
        raw = _get_json(USGS_QUAKES)
        items = []
        for feature in raw.get("features", [])[:250]:
            coords = feature.get("geometry", {}).get("coordinates") or [None, None]
            props = feature.get("properties") or {}
            lon, lat = coords[0], coords[1]
            if lat is None or lon is None:
                continue
            items.append(
                {
                    "id": feature.get("id"),
                    "name": props.get("place") or "Earthquake",
                    "kind": "earthquake",
                    "lat": lat,
                    "lon": lon,
                    "magnitude": props.get("mag"),
                    "url": props.get("url"),
                }
            )
        return {"items": items, "source": "USGS"}

    return _cached("earthquakes", 120, load)


def events() -> dict:
    def load():
        raw = _get_json(EONET_EVENTS, params={"status": "open", "limit": 200})
        items = []
        for event in raw.get("events", []):
            categories = event.get("categories") or []
            first = categories[0] if categories else {}
            geometry = event.get("geometry") or []
            if not geometry:
                continue
            coords = geometry[-1].get("coordinates") or []
            if len(coords) < 2:
                continue
            lon, lat = coords[0], coords[1]
            items.append(
                {
                    "id": event.get("id"),
                    "name": event.get("title") or "Event",
                    "kind": "event",
                    "category": first.get("title") or "unknown",
                    "category_id": first.get("id") or "unknown",
                    "lat": lat,
                    "lon": lon,
                }
            )
        return {"items": items, "source": "NASA EONET"}

    return _cached("eonet", 180, load)


def _safe_list(loader) -> list:
    try:
        return loader()
    except (httpx.HTTPError, ValueError, TypeError, KeyError):
        return []


def _military_hexes() -> set[str]:
    hit = _CACHE.get("mil-hexes")
    if hit:
        return set(hit[1])

    def load():
        raw = _get_json(ADSB_MIL, timeout=8.0)
        return {str(ac.get("hex", "")).lower() for ac in (raw.get("ac") or []) if ac.get("hex")}

    try:
        return set(_cached("mil-hexes", 300, load))
    except httpx.HTTPError:
        return set()


def _parse_opensky(raw: dict) -> list[dict]:
    items = []
    for state in raw.get("states") or []:
        if not state or state[6] is None or state[5] is None:
            continue
        icao = str(state[0] or "").lower()
        items.append(
            {
                "id": icao,
                "name": (state[1] or state[0] or "Flight").strip(),
                "kind": "flight",
                "lat": state[6],
                "lon": state[5],
                "altitude": state[7],
                "heading": state[10],
                "country": state[2],
                "military": False,
            }
        )
    return items


def _parse_adsb(raw: dict) -> list[dict]:
    items = []
    for ac in raw.get("ac") or []:
        if ac.get("lat") is None or ac.get("lon") is None:
            continue
        icao = str(ac.get("hex") or "").lower()
        items.append(
            {
                "id": icao,
                "name": ac.get("flight") or ac.get("r") or icao or "Flight",
                "kind": "flight",
                "lat": ac.get("lat"),
                "lon": ac.get("lon"),
                "altitude": ac.get("alt_baro"),
                "heading": ac.get("track"),
                "country": None,
                "military": bool(ac.get("mil")),
            }
        )
    return items


def _apply_military(items: list[dict]) -> list[dict]:
    military = _military_hexes() if _CACHE.get("mil-hexes") else set()
    if not military:
        return items
    for item in items:
        item["military"] = bool(item.get("military")) or item["id"] in military
    return items


_FLIGHT_REFRESH = threading.Lock()


def _flight_pool() -> tuple[dict[str, dict], str | None, float | None]:
    pool: dict[str, dict] = {}
    source = None
    age = None
    opensky = _CACHE.get("flights-world")
    if opensky:
        age = time.time() - opensky[0]
        source = opensky[1]["source"]
        for item in opensky[1]["items"]:
            pool[item["id"]] = item
    adsb = _CACHE.get("flights-adsb")
    if adsb:
        if source is None:
            source = "adsb.lol"
        for item in adsb[1]:
            pool.setdefault(item["id"], item)
    return pool, source, age


def _store_adsb(items: list[dict]) -> None:
    existing = {item["id"]: item for item in ((_CACHE.get("flights-adsb") or (0, []))[1])}
    for item in items:
        existing[item["id"]] = item
    _CACHE["flights-adsb"] = (time.time(), list(existing.values()))


def _adsb_point(lat: float, lon: float, dist: int) -> dict:
    last_error = None
    for template in ADSB_FEEDS:
        try:
            raw = _get_json(template.format(lat=lat, lon=_wrap_lon(lon), dist=dist), timeout=6.0)
            return {"items": _parse_adsb(raw), "source": "adsb.lol" if "adsb.lol" in template else "adsb.fi"}
        except httpx.HTTPError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return {"items": [], "source": "adsb.lol"}


def _adsb_viewport(south: float, west: float, north: float, east: float) -> dict:
    lat = (south + north) / 2
    if west <= east:
        lon = (west + east) / 2
        span = max(north - south, east - west)
    else:
        span = max(north - south, 360 + east - west)
        lon = west + span / 2
    dist = max(80, min(250, int(span * 45)))
    return _adsb_point(lat, lon, dist)


def _schedule_flight_refresh() -> None:
    if _FLIGHT_REFRESH.locked():
        return

    def run() -> None:
        try:
            _refresh_flights_world()
        except Exception:
            _CACHE["flights-fail"] = (time.time(), True)

    threading.Thread(target=run, daemon=True).start()


def _refresh_flights_world() -> dict:
    with _FLIGHT_REFRESH:
        hit = _CACHE.get("flights-world")
        if hit and time.time() - hit[0] < 20:
            return hit[1]
        raw = _get_json(OPENSKY_STATES, timeout=8.0)
        value = {"items": _parse_opensky(raw), "source": "OpenSky"}
        _CACHE["flights-world"] = (time.time(), value)
        _CACHE.pop("flights-fail", None)
        return value


def _seed_adsb_regions() -> None:
    for lat, lon in ADSB_SEEDS:
        try:
            data = _adsb_point(lat, lon, 250)
            if data["items"]:
                _store_adsb(data["items"])
        except httpx.HTTPError:
            continue
        time.sleep(0.35)


def flights(south: float, west: float, north: float, east: float) -> dict:
    if north <= south:
        return {"items": [], "source": "OpenSky", "reason": "bad_bbox"}

    pool, source, age = _flight_pool()
    if age is None or age >= 20:
        _schedule_flight_refresh()

    items = [item for item in pool.values() if _in_bbox(item["lat"], item["lon"], south, west, north, east)]
    if items:
        return {"items": _apply_military(items)[:500], "source": source or "OpenSky"}

    try:
        data = _adsb_viewport(south, west, north, east)
    except httpx.HTTPError:
        return {"items": [], "source": "adsb.lol", "reason": "feed_unavailable"}
    _store_adsb(data["items"])
    items = [item for item in data["items"] if _in_bbox(item["lat"], item["lon"], south, west, north, east)]
    return {"items": _apply_military(items)[:500], "source": data["source"]}


def warmup_catalogs() -> None:
    for loader in (_natural_earth_cities, _openflights_airports, _natural_earth_ports, _military_hexes):
        try:
            loader()
        except Exception:
            pass
    try:
        _refresh_flights_world()
    except Exception:
        pass
    try:
        _seed_adsb_regions()
    except Exception:
        pass


def places(south: float, west: float, north: float, east: float, zoom: int) -> dict:
    if zoom < 4 or north <= south:
        return {"items": [], "source": "Natural Earth / OpenFlights", "reason": "zoom_in"}

    with ThreadPoolExecutor(max_workers=3) as pool:
        cities_f = pool.submit(_safe_list, _natural_earth_cities)
        ports_f = pool.submit(_safe_list, _natural_earth_ports)
        airports_f = pool.submit(_safe_list, _openflights_airports)
        cities = cities_f.result()
        port_catalog = ports_f.result()
        airport_catalog = airports_f.result()

    towns = [
        item
        for item in cities
        if item["kind"] == "town" and _in_bbox(item["lat"], item["lon"], south, west, north, east)
    ]
    towns.sort(key=lambda item: item.get("pop") or 0, reverse=True)
    ports = [
        item
        for item in port_catalog
        if _in_bbox(item["lat"], item["lon"], south, west, north, east)
    ]
    airports = []
    military = []
    for item in airport_catalog:
        if not _in_bbox(item["lat"], item["lon"], south, west, north, east):
            continue
        if item["kind"] == "military":
            military.append(item)
        elif item.get("iata"):
            airports.append(item)

    items = towns[:80] + ports[:50] + military[:40] + airports[:80]
    return {"items": items, "source": "Natural Earth / OpenFlights"}


ESRI_IMAGERY_META = (
    "https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/4/query"
)


def _format_src_date(value: Any) -> str | None:
    if value in (None, "", 99999, "99999"):
        return None
    text = str(int(value)) if isinstance(value, (int, float)) else str(value)
    if len(text) == 8 and text.isdigit():
        return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
    return text


def _wrap_lon(lon: float) -> float:
    return ((lon + 180) % 360) - 180


def _latest_frame(frames: list | None) -> dict | None:
    if not frames:
        return None
    return frames[-1]


def radar_tile_url(host: str, path: str, color: int = 2) -> str:
    return f"{host.rstrip('/')}{path}/256/{{z}}/{{x}}/{{y}}/{color}/1_1.png"


def satellite_tile_url(host: str, path: str) -> str:
    return f"{host.rstrip('/')}{path}/256/{{z}}/{{x}}/{{y}}/0/0_0.png"


WEATHER_FINEST = 0.1
WEATHER_MAX_CELLS = 120


def sample_weather_grid(south: float, west: float, north: float, east: float, zoom: int) -> list[dict]:
    cells, _grid = build_weather_grid(south, west, north, east, zoom)
    return cells


def build_weather_grid(south: float, west: float, north: float, east: float, zoom: int) -> tuple[list[dict], dict]:
    south, west, north, east = normalize_weather_bbox(south, west, north, east)
    span_lon = east - west
    span_lat = north - south
    if span_lat <= 0 or span_lon <= 0:
        return [], {}

    _ = zoom
    step = WEATHER_FINEST
    west_g = south_g = 0.0
    cols = rows = 1
    for _ in range(12):
        west_g = math.floor(west / step) * step
        south_g = math.floor(south / step) * step
        cols = max(1, math.ceil((east - west_g) / step - 1e-9))
        rows = max(1, math.ceil((north - south_g) / step - 1e-9))
        if cols * rows <= WEATHER_MAX_CELLS:
            break
        step *= 2

    cells = []
    for row in range(rows):
        for col in range(cols):
            cell_south = south_g + row * step
            cell_north = cell_south + step
            cell_west = west_g + col * step
            cell_east = cell_west + step
            lat = max(-90.0, min(90.0, (cell_south + cell_north) / 2))
            cells.append(
                {
                    "lat": lat,
                    "lon": _wrap_lon((cell_west + cell_east) / 2),
                    "south": cell_south,
                    "north": cell_north,
                    "west": cell_west,
                    "east": cell_east,
                    "row": row,
                    "col": col,
                }
            )
    grid = {
        "rows": rows,
        "cols": cols,
        "south": south_g,
        "west": west_g,
        "north": south_g + rows * step,
        "east": west_g + cols * step,
        "dlat": step,
        "dlon": step,
    }
    return cells, grid


def normalize_weather_bbox(south: float, west: float, north: float, east: float) -> tuple[float, float, float, float]:
    south = max(-85.0, min(85.0, south))
    north = max(-85.0, min(85.0, north))
    if north <= south:
        south, north = -60.0, 70.0
    span = east - west
    if span <= 0:
        east += 360.0
        span = east - west
    if span > 360.0:
        mid = west + span / 2.0
        west = mid - 180.0
        east = mid + 180.0
    return south, west, north, east


def weather_radar() -> dict:
    def load():
        raw = _get_json(RAINVIEWER_MAPS, timeout=15.0)
        host = raw.get("host") or "https://tilecache.rainviewer.com"
        radar = raw.get("radar") or {}
        latest = _latest_frame((radar.get("past") or []) + (radar.get("nowcast") or []))
        satellite = _latest_frame((raw.get("satellite") or {}).get("infrared") or [])
        return {
            "source": "RainViewer",
            "rain_url": radar_tile_url(host, latest["path"]) if latest else None,
            "clouds_url": satellite_tile_url(host, satellite["path"]) if satellite else None,
            "time": latest.get("time") if latest else None,
            "max_zoom": 7,
        }

    return _cached("weather-radar", 180, load)


def weather_field(south: float, west: float, north: float, east: float, zoom: int) -> dict:
    south, west, north, east = normalize_weather_bbox(south, west, north, east)
    cells, grid = build_weather_grid(south, west, north, east, zoom)
    if not cells:
        return {"items": [], "source": "Open-Meteo", "reason": "empty_grid"}

    key = f"wx:{grid['south']:.2f}:{grid['west']:.2f}:{grid['dlat']:.3f}:{grid['rows']}:{grid['cols']}"

    def load():
        raw = _get_json(
            OPEN_METEO,
            timeout=25.0,
            params={
                "latitude": ",".join(f"{cell['lat']:.4f}" for cell in cells),
                "longitude": ",".join(f"{cell['lon']:.4f}" for cell in cells),
                "current": "weather_code,cloud_cover,precipitation,wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
                "cell_selection": "nearest",
            },
        )
        rows = raw if isinstance(raw, list) else [raw]
        items = []
        for cell, row in zip(cells, rows, strict=False):
            current = (row or {}).get("current") or {}
            code = current.get("weather_code")
            items.append(
                {
                    **cell,
                    "kind": "weather",
                    "cloud_cover": current.get("cloud_cover"),
                    "precipitation": current.get("precipitation"),
                    "wind_speed": current.get("wind_speed_10m"),
                    "wind_direction": current.get("wind_direction_10m"),
                    "weather_code": code,
                    "storm": code in STORM_CODES,
                }
            )
        return {"items": items, "grid": grid, "source": "Open-Meteo"}

    return _cached(key, 600, load)


def imagery_meta(lat: float, lon: float, zoom: int) -> dict:
    key = f"img:{lat:.3f}:{lon:.3f}:{zoom}"

    def load():
        raw = _get_json(
            ESRI_IMAGERY_META,
            timeout=20.0,
            params={
                "geometry": f"{lon},{lat}",
                "geometryType": "esriGeometryPoint",
                "inSR": 4326,
                "spatialRel": "esriSpatialRelIntersects",
                "outFields": "SRC_DATE,SRC_RES,SRC_DESC,NICE_NAME,NICE_DESC,MinMapLevel,MaxMapLevel",
                "returnGeometry": "false",
                "f": "json",
            },
        )
        records = [feature.get("attributes") or {} for feature in raw.get("features") or []]
        matching = [
            item
            for item in records
            if item.get("MinMapLevel") is None
            or item.get("MaxMapLevel") is None
            or item["MinMapLevel"] <= zoom <= item["MaxMapLevel"]
        ]
        pool = matching or records
        if not pool:
            return {"date": None, "source": None, "name": None, "resolution_m": None}
        chosen = min(pool, key=lambda item: item.get("SRC_RES") if item.get("SRC_RES") is not None else 9999)
        source = chosen.get("NICE_DESC") or chosen.get("SRC_DESC") or chosen.get("NICE_NAME")
        return {
            "date": _format_src_date(chosen.get("SRC_DATE")),
            "source": source,
            "name": chosen.get("NICE_NAME"),
            "resolution_m": chosen.get("SRC_RES"),
        }

    return _cached(key, 600, load)
