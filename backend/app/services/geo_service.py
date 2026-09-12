import csv
import io
import time
from typing import Any

import httpx

USGS_QUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
EONET_EVENTS = "https://eonet.gsfc.nasa.gov/api/v3/events"
OPENSKY_STATES = "https://opensky-network.org/api/states/all"
ADSB_LOL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
ADSB_MIL = "https://api.adsb.lol/v2/mil"
LAUNCHES = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=20"
NE_PLACES = "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_50m_populated_places_simple.geojson"
OPENFLIGHTS = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
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
    return south <= lat <= north and west <= lon <= east


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
        name = props.get("name") or props.get("NAME") or props.get("NAMEASCII") or "City"
        pop = props.get("pop_max") or props.get("POP_MAX") or 0
        kind = "city" if int(pop or 0) >= 100000 else "town"
        items.append({"id": f"ne-{name}-{lat:.2f}", "name": name, "kind": kind, "lat": lat, "lon": lon})
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
        items.append({"id": f"apt-{parts[0]}", "name": name, "kind": "airport", "lat": lat, "lon": lon})
    _CATALOGS["airports"] = items
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
        raw = _get_json(EONET_EVENTS, params={"status": "open", "limit": 80})
        items = []
        for event in raw.get("events", []):
            categories = [c.get("title") for c in event.get("categories", []) if c.get("title")]
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
                    "category": categories[0] if categories else "unknown",
                    "lat": lat,
                    "lon": lon,
                }
            )
        return {"items": items, "source": "NASA EONET"}

    return _cached("eonet", 180, load)


def launches() -> dict:
    def load():
        raw = _get_json(LAUNCHES)
        items = []
        for launch in raw.get("results", []):
            pad = (launch.get("pad") or {}).get("location") or {}
            lat, lon = pad.get("latitude"), pad.get("longitude")
            if lat is None or lon is None:
                continue
            items.append(
                {
                    "id": launch.get("id"),
                    "name": launch.get("name") or "Launch",
                    "kind": "launch",
                    "lat": float(lat),
                    "lon": float(lon),
                    "when": launch.get("net"),
                    "pad": (launch.get("pad") or {}).get("name"),
                }
            )
        return {"items": items, "source": "Launch Library 2"}

    return _cached("launches", 300, load)


def _military_hexes() -> set[str]:
    def load():
        raw = _get_json(ADSB_MIL, timeout=12.0)
        return {str(ac.get("hex", "")).lower() for ac in (raw.get("ac") or []) if ac.get("hex")}

    try:
        return set(_cached("mil-hexes", 300, load))
    except httpx.HTTPError:
        return set()


def flights(south: float, west: float, north: float, east: float) -> dict:
    if north <= south or abs(north - south) > 80 or abs(east - west) > 120:
        return {"items": [], "source": "OpenSky", "reason": "bbox_too_large"}

    key = f"flights:{south:.1f}:{west:.1f}:{north:.1f}:{east:.1f}"
    military = _military_hexes()

    def load():
        try:
            raw = _get_json(
                OPENSKY_STATES,
                timeout=15.0,
                params={"lamin": south, "lomin": west, "lamax": north, "lomax": east},
            )
            items = []
            for state in (raw.get("states") or [])[:400]:
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
                        "military": icao in military,
                    }
                )
            return {"items": items, "source": "OpenSky"}
        except httpx.HTTPError:
            lat = (south + north) / 2
            lon = (west + east) / 2
            dist = max(50, min(250, int(abs(north - south) * 40)))
            raw = _get_json(ADSB_LOL.format(lat=lat, lon=lon, dist=dist), timeout=15.0)
            items = []
            for ac in (raw.get("ac") or [])[:400]:
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
                        "military": bool(ac.get("mil")) or icao in military,
                    }
                )
            return {"items": items, "source": "adsb.lol"}

    return _cached(key, 20, load)


def warmup_catalogs() -> None:
    try:
        _natural_earth_cities()
        _openflights_airports()
    except httpx.HTTPError:
        pass


def places(south: float, west: float, north: float, east: float, zoom: int) -> dict:
    if zoom < 4 or north <= south:
        return {"items": [], "source": "Natural Earth / OpenFlights", "reason": "zoom_in"}

    items = [
        item
        for item in _natural_earth_cities()
        if item["kind"] != "city"
        and zoom >= 6
        and _in_bbox(item["lat"], item["lon"], south, west, north, east)
    ]
    if zoom >= 6:
        items.extend(
            item
            for item in _openflights_airports()
            if _in_bbox(item["lat"], item["lon"], south, west, north, east)
        )
    return {"items": items[:400], "source": "Natural Earth / OpenFlights"}


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


def sample_weather_grid(south: float, west: float, north: float, east: float, zoom: int) -> list[dict]:
    south, west, north, east = normalize_weather_bbox(south, west, north, east)
    span_lon = east - west
    span_lat = north - south
    if span_lat <= 0 or span_lon <= 0:
        return []

    if zoom < 5:
        cols, rows = 10, 6
    elif zoom < 8:
        cols, rows = 10, 7
    else:
        cols, rows = 12, 8

    dlat = span_lat / rows
    dlon = span_lon / cols
    cells = []
    for row in range(rows):
        for col in range(cols):
            cell_south = south + row * dlat
            cell_north = south + (row + 1) * dlat
            cell_west = west + col * dlon
            cell_east = west + (col + 1) * dlon
            lat = max(-90.0, min(90.0, (cell_south + cell_north) / 2))
            cells.append(
                {
                    "lat": lat,
                    "lon": _wrap_lon((cell_west + cell_east) / 2),
                    "south": cell_south,
                    "north": cell_north,
                    "west": cell_west,
                    "east": cell_east,
                }
            )
    return cells


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
    cells = sample_weather_grid(south, west, north, east, zoom)
    if not cells:
        return {"items": [], "source": "Open-Meteo", "reason": "empty_grid"}

    key = f"wx:{south:.1f}:{west:.1f}:{north:.1f}:{east:.1f}:{zoom}"

    def load():
        raw = _get_json(
            OPEN_METEO,
            timeout=20.0,
            params={
                "latitude": ",".join(f"{cell['lat']:.4f}" for cell in cells),
                "longitude": ",".join(f"{cell['lon']:.4f}" for cell in cells),
                "current": "weather_code,cloud_cover,precipitation,wind_speed_10m,wind_direction_10m",
                "wind_speed_unit": "ms",
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
        return {"items": items, "source": "Open-Meteo"}

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
