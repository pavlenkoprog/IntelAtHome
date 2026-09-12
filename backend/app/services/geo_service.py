import csv
import io
import logging
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx

log = logging.getLogger("palantir.flights")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[flights] %(message)s"))
    log.addHandler(_handler)
    log.setLevel(logging.INFO)
    log.propagate = False

USGS_QUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
EONET_EVENTS = "https://eonet.gsfc.nasa.gov/api/v3/events"
OPENSKY_STATES = "https://opensky-network.org/api/states/all"
ADSB_FEEDS = (
    "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}",
    "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{dist}",
)
ADSB_MIL = "https://api.adsb.lol/v2/mil"
FLIGHT_CAP = 800
FLIGHT_POOL_TTL = 50
ADSB_TILE_STEP = 4.0
ADSB_DIST = 250
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


def _adsb_point(lat: float, lon: float, dist: int) -> dict:
    last_error = None
    for template in ADSB_FEEDS:
        try:
            raw = _get_json(template.format(lat=lat, lon=_wrap_lon(lon), dist=dist), timeout=6.0)
            return {"items": _parse_adsb(raw), "source": "adsb.lol" if "adsb.lol" in template else "adsb.fi"}
        except httpx.HTTPStatusError as exc:
            last_error = exc
            if exc.response is not None and exc.response.status_code == 429:
                break
        except httpx.HTTPError as exc:
            last_error = exc
    if last_error:
        raise last_error
    return {"items": [], "source": "adsb.lol"}


def _viewport_span(south: float, west: float, north: float, east: float) -> tuple[float, float, float]:
    span_lat = max(0.1, north - south)
    if west <= east:
        span_lon = max(0.1, east - west)
        mid_lon = (west + east) / 2
    else:
        span_lon = max(0.1, 360 + east - west)
        mid_lon = _wrap_lon(west + span_lon / 2)
    return span_lat, span_lon, mid_lon


def _grid_cells(south: float, west: float, north: float, east: float) -> list[tuple[float, float]]:
    step = ADSB_TILE_STEP
    span_lat, span_lon, mid_lon = _viewport_span(south, west, north, east)
    mid_lat = (south + north) / 2
    lat = math.floor((south - step / 2) / step) * step
    cells: list[tuple[float, float]] = []
    while lat <= north + step / 2:
        if west <= east:
            lon = math.floor((west - step / 2) / step) * step
            while lon <= east + step / 2:
                cells.append((lat + step / 2, _wrap_lon(lon + step / 2)))
                lon += step
        else:
            lon = west - step / 2
            end = west + span_lon + step / 2
            while lon <= end:
                cells.append((lat + step / 2, _wrap_lon(lon + step / 2)))
                lon += step
        lat += step
        if len(cells) > 24:
            break
    cells.sort(
        key=lambda cell: (cell[0] - mid_lat) ** 2 + ((_wrap_lon(cell[1] - mid_lon)) ** 2)
    )
    return cells[:8]


def _adsb_tile(lat: float, lon: float, dist: int) -> tuple[list[dict], bool]:
    key = f"adsb-tile:{lat:.1f}:{lon:.1f}:{dist}"
    hit = _CACHE.get(key)
    if hit and hit[1] and time.time() - hit[0] < 20:
        log.info("tile cache lat=%.2f lon=%.2f dist=%s count=%s", lat, lon, dist, len(hit[1]))
        return hit[1], True
    try:
        data = _adsb_point(lat, lon, dist)
    except httpx.HTTPError:
        if hit and hit[1]:
            log.info("tile stale lat=%.2f lon=%.2f dist=%s count=%s", lat, lon, dist, len(hit[1]))
            return hit[1], True
        raise
    if data["items"]:
        _CACHE[key] = (time.time(), data["items"])
    log.info("tile fetch lat=%.2f lon=%.2f dist=%s count=%s", lat, lon, dist, len(data["items"]))
    return data["items"], False


def _flight_pool() -> dict[str, dict]:
    hit = _CACHE.get("flights-pool")
    now = time.time()
    store = dict(hit[1]) if hit else {}
    for key in [key for key, item in store.items() if now - item.get("_ts", 0) > FLIGHT_POOL_TTL]:
        del store[key]
    return store


def _flight_pool_add(items: list[dict]) -> None:
    store = _flight_pool()
    now = time.time()
    for item in items:
        store[item["id"]] = {**item, "_ts": now}
    _CACHE["flights-pool"] = (now, store)


def _public_flight(item: dict) -> dict:
    return {key: value for key, value in item.items() if key != "_ts"}


def _adsb_cover(south: float, west: float, north: float, east: float) -> dict:
    cells = _grid_cells(south, west, north, east)
    items: dict[str, dict] = {}
    cached_tiles = 0
    fetched = None
    for lat, lon in cells:
        key = f"adsb-tile:{lat:.1f}:{lon:.1f}:{ADSB_DIST}"
        hit = _CACHE.get(key)
        if hit and hit[1] and time.time() - hit[0] < 20:
            cached_tiles += 1
            for item in hit[1]:
                items[item["id"]] = item
    for lat, lon in cells:
        key = f"adsb-tile:{lat:.1f}:{lon:.1f}:{ADSB_DIST}"
        hit = _CACHE.get(key)
        if hit and hit[1] and time.time() - hit[0] < 20:
            continue
        try:
            chunk, _cached = _adsb_tile(lat, lon, ADSB_DIST)
            fetched = (lat, lon)
            for item in chunk:
                items[item["id"]] = item
        except httpx.HTTPError as exc:
            log.info("tile error %s", exc)
        break
    return {
        "items": list(items.values()),
        "source": "adsb.lol",
        "tiles": cells,
        "fetched": fetched,
        "cached_tiles": cached_tiles,
        "dist": ADSB_DIST,
    }


def _spread_flights(
    items: list[dict],
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int = FLIGHT_CAP,
) -> list[dict]:
    if len(items) <= limit:
        return items
    rows, cols = 5, 5
    span_lat, span_lon, _mid = _viewport_span(south, west, north, east)
    buckets: list[list[dict]] = [[] for _ in range(rows * cols)]
    for item in items:
        row = min(rows - 1, max(0, int((item["lat"] - south) / span_lat * rows)))
        if west <= east:
            col = min(cols - 1, max(0, int((item["lon"] - west) / span_lon * cols)))
        else:
            shifted = item["lon"] - west if item["lon"] >= west else item["lon"] + 360 - west
            col = min(cols - 1, max(0, int(shifted / span_lon * cols)))
        buckets[row * cols + col].append(item)
    chosen: list[dict] = []
    index = 0
    while len(chosen) < limit and any(buckets):
        bucket = buckets[index % len(buckets)]
        if bucket:
            chosen.append(bucket.pop())
        index += 1
        if index > limit * len(buckets):
            break
    return chosen


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


def flights(south: float, west: float, north: float, east: float, zoom: int | None = None) -> dict:
    log.info(
        "request zoom=%s bbox=%.3f,%.3f,%.3f,%.3f",
        zoom,
        south,
        west,
        north,
        east,
    )
    if north <= south:
        log.info("skip bad_bbox")
        return {"items": [], "source": "OpenSky", "reason": "bad_bbox"}

    opensky = _CACHE.get("flights-world")
    if opensky is None or time.time() - opensky[0] >= 20:
        _schedule_flight_refresh()

    source = "adsb.lol"
    cover_meta = {"tiles": [], "cached_tiles": 0, "dist": ADSB_DIST, "raw": 0, "fetched": None}
    try:
        data = _adsb_cover(south, west, north, east)
        cover_meta = {
            "tiles": data.get("tiles") or [],
            "cached_tiles": data.get("cached_tiles") or 0,
            "dist": data.get("dist") or ADSB_DIST,
            "raw": len(data["items"]),
            "fetched": data.get("fetched"),
        }
        source = data.get("source") or source
        _flight_pool_add(data["items"])
    except httpx.HTTPError as exc:
        log.info("adsb cover error %s", exc)

    opensky_extra = 0
    if opensky:
        extra = [
            item
            for item in opensky[1]["items"]
            if _in_bbox(item["lat"], item["lon"], south, west, north, east)
        ]
        _flight_pool_add(extra)
        opensky_extra = len(extra)
        if extra:
            source = opensky[1]["source"]

    in_view = [
        _public_flight(item)
        for item in _flight_pool().values()
        if _in_bbox(item["lat"], item["lon"], south, west, north, east)
    ]
    items = _spread_flights(in_view, south, west, north, east)
    if not items:
        log.info(
            "empty source=%s tiles=%s cached=%s fetched=%s dist=%s adsb=%s pool=%s opensky_extra=%s",
            source,
            cover_meta["tiles"],
            cover_meta["cached_tiles"],
            cover_meta["fetched"],
            cover_meta["dist"],
            cover_meta["raw"],
            len(_flight_pool()),
            opensky_extra,
        )
        return {"items": [], "source": source, "reason": "feed_unavailable"}
    log.info(
        "loaded count=%s source=%s tiles=%s cached=%s fetched=%s dist=%s adsb=%s in_bbox=%s pool=%s opensky_extra=%s",
        len(items),
        source,
        cover_meta["tiles"],
        cover_meta["cached_tiles"],
        cover_meta["fetched"],
        cover_meta["dist"],
        cover_meta["raw"],
        len(in_view),
        len(_flight_pool()),
        opensky_extra,
    )
    return {"items": _apply_military(items), "source": source}


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
