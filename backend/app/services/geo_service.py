import csv
import io
import json
import logging
import math
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("palantir.store")
if not log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("[store] %(message)s"))
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
ADSB_GLOBE = "https://globe.theairtraffic.com/data/aircraft.json"
FLIGHT_CAP = 800
SNAPSHOT_INTERVAL = 600
WEATHER_PLANET_STEP = 20.0
WEATHER_BATCH = 40
SNAPSHOT_DIR = Path(__file__).resolve().parents[3] / "data" / "snapshots"
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
_STORE: dict[str, dict] = {}
_STORE_LOCK = threading.Lock()
_SNAPSHOT_STARTED = False


def _cached(key: str, ttl: float, loader):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = loader()
    _CACHE[key] = (now, value)
    return value


def _put_store(name: str, payload: dict) -> dict:
    data = {**payload, "updated": time.time()}
    with _STORE_LOCK:
        _STORE[name] = data
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return data
    try:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        path = SNAPSHOT_DIR / f"{name}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        log.info("snapshot write %s failed: %s", name, exc)
    return data


def _get_store(name: str) -> dict | None:
    with _STORE_LOCK:
        hit = _STORE.get(name)
    return dict(hit) if hit else None


def _load_snapshots_from_disk() -> None:
    if not SNAPSHOT_DIR.exists():
        return
    for path in SNAPSHOT_DIR.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict) and "items" in payload:
            with _STORE_LOCK:
                _STORE[path.stem] = payload
            log.info("loaded disk %s items=%s", path.stem, len(payload.get("items") or []))


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


def _load_earthquakes() -> dict:
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


def earthquakes() -> dict:
    snap = _get_store("earthquakes")
    if snap:
        return {"items": snap["items"], "source": snap["source"]}
    try:
        data = _load_earthquakes()
        return _put_store("earthquakes", data)
    except httpx.HTTPError:
        return {"items": [], "source": "USGS", "reason": "warming"}


def _load_events() -> dict:
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


def events() -> dict:
    snap = _get_store("events")
    if snap:
        return {"items": snap["items"], "source": snap["source"]}
    try:
        data = _load_events()
        return _put_store("events", data)
    except httpx.HTTPError:
        return {"items": [], "source": "NASA EONET", "reason": "warming"}


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
    for ac in raw.get("ac") or raw.get("aircraft") or []:
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


def _viewport_span(south: float, west: float, north: float, east: float) -> tuple[float, float, float]:
    span_lat = max(0.1, north - south)
    if west <= east:
        span_lon = max(0.1, east - west)
        mid_lon = (west + east) / 2
    else:
        span_lon = max(0.1, 360 + east - west)
        mid_lon = _wrap_lon(west + span_lon / 2)
    return span_lat, span_lon, mid_lon


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


ADSB_WORLD = (
    (51.5, 0.0),
    (48.9, 2.3),
    (50.1, 8.7),
    (52.3, 4.8),
    (41.9, 12.5),
    (55.8, 37.6),
    (59.9, 30.3),
    (41.0, 29.0),
    (40.6, -73.9),
    (33.9, -118.4),
    (41.9, -87.6),
    (25.8, -80.3),
    (49.2, -123.1),
    (19.4, -99.1),
    (-23.5, -46.6),
    (-34.6, -58.4),
    (25.2, 55.3),
    (30.0, 31.2),
    (28.6, 77.2),
    (1.35, 103.8),
    (13.7, 100.5),
    (22.3, 114.2),
    (31.2, 121.5),
    (35.7, 139.7),
    (37.6, 126.9),
    (-33.9, 151.2),
    (-26.1, 28.2),
)


def _refresh_flights_snapshot() -> None:
    try:
        raw = _get_json(OPENSKY_STATES, timeout=40.0)
        items = _apply_military(_parse_opensky(raw))
        if items:
            _put_store("flights", {"items": items, "source": "OpenSky"})
            log.info("flights snapshot %s", len(items))
            return
    except httpx.HTTPError as exc:
        log.info("opensky snapshot failed: %s", exc)

    try:
        raw = _get_json(ADSB_GLOBE, timeout=40.0)
        items = _apply_military(_parse_adsb(raw))
        if items:
            _put_store("flights", {"items": items, "source": "theairtraffic"})
            log.info("flights globe snapshot %s", len(items))
            return
    except httpx.HTTPError as exc:
        log.info("globe snapshot failed: %s", exc)

    existing = _get_store("flights") or {"items": []}
    by_id = {item["id"]: item for item in existing.get("items") or []}
    before = len(by_id)
    for lat, lon in ADSB_WORLD:
        try:
            raw = _get_json(ADSB_FEEDS[0].format(lat=lat, lon=lon, dist=250), timeout=8.0)
            for item in _parse_adsb(raw):
                by_id[item["id"]] = item
        except httpx.HTTPError:
            continue
        time.sleep(0.35)
    items = _apply_military(list(by_id.values()))
    if items:
        _put_store("flights", {"items": items, "source": "adsb.lol"})
        log.info("flights fallback snapshot %s (was %s)", len(items), before)


def flights(south: float, west: float, north: float, east: float, zoom: int | None = None) -> dict:
    if north <= south:
        return {"items": [], "source": "OpenSky", "reason": "bad_bbox"}
    snap = _get_store("flights")
    if not snap:
        return {"items": [], "source": "OpenSky", "reason": "warming"}
    items = [item for item in snap["items"] if _in_bbox(item["lat"], item["lon"], south, west, north, east)]
    return {"items": items, "source": snap.get("source") or "OpenSky"}


def _planet_weather_cells() -> tuple[list[dict], dict]:
    step = WEATHER_PLANET_STEP
    south, west, north, east = -84.0, -180.0, 84.0, 180.0
    rows = max(1, int(round((north - south) / step)))
    cols = max(1, int(round((east - west) / step)))
    cells = []
    for row in range(rows):
        for col in range(cols):
            cell_south = south + row * step
            cell_west = west + col * step
            cells.append(
                {
                    "lat": cell_south + step / 2,
                    "lon": cell_west + step / 2,
                    "south": cell_south,
                    "north": cell_south + step,
                    "west": cell_west,
                    "east": cell_west + step,
                    "row": row,
                    "col": col,
                }
            )
    grid = {
        "rows": rows,
        "cols": cols,
        "south": south,
        "west": west,
        "north": south + rows * step,
        "east": west + cols * step,
        "dlat": step,
        "dlon": step,
    }
    return cells, grid


def _refresh_weather_snapshot() -> None:
    cells, grid = _planet_weather_cells()
    items: list[dict] = []
    for index in range(0, len(cells), WEATHER_BATCH):
        chunk = cells[index : index + WEATHER_BATCH]
        raw = None
        for attempt in range(3):
            try:
                raw = _get_json(
                    OPEN_METEO,
                    timeout=40.0,
                    params={
                        "latitude": ",".join(f"{cell['lat']:.4f}" for cell in chunk),
                        "longitude": ",".join(f"{cell['lon']:.4f}" for cell in chunk),
                        "current": "weather_code,cloud_cover,precipitation,wind_speed_10m,wind_direction_10m",
                        "wind_speed_unit": "ms",
                        "cell_selection": "nearest",
                    },
                )
                break
            except httpx.HTTPError as exc:
                log.info("weather batch %s failed: %s", index, exc)
                time.sleep(8.0 * (attempt + 1))
        if raw is None:
            continue
        rows = raw if isinstance(raw, list) else [raw]
        for cell, row in zip(chunk, rows, strict=False):
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
        time.sleep(2.0)
    if items:
        _put_store("weather", {"items": items, "grid": grid, "source": "Open-Meteo"})
        log.info("weather snapshot %s", len(items))


def _refresh_radar_snapshot() -> None:
    data = _load_weather_radar()
    _put_store("radar", {"items": [], **data})
    log.info("radar snapshot %s", data.get("rain_url"))


def refresh_snapshots() -> None:
    jobs = (
        ("earthquakes", lambda: _put_store("earthquakes", _load_earthquakes())),
        ("events", lambda: _put_store("events", _load_events())),
        ("radar", _refresh_radar_snapshot),
        ("flights", _refresh_flights_snapshot),
        ("weather", _refresh_weather_snapshot),
        ("military", _military_hexes),
    )
    for name, job in jobs:
        try:
            job()
        except Exception as exc:
            log.info("refresh %s failed: %s", name, exc)


def warmup_catalogs() -> None:
    for loader in (_natural_earth_cities, _openflights_airports, _natural_earth_ports):
        try:
            loader()
            log.info("catalog %s ready", loader.__name__)
        except Exception as exc:
            log.info("catalog %s failed: %s", loader.__name__, exc)


def start_snapshot_loop() -> None:
    global _SNAPSHOT_STARTED
    if _SNAPSHOT_STARTED:
        return
    _SNAPSHOT_STARTED = True

    def run() -> None:
        _load_snapshots_from_disk()
        warmup_catalogs()
        refresh_snapshots()
        while True:
            time.sleep(SNAPSHOT_INTERVAL)
            refresh_snapshots()

    threading.Thread(target=run, daemon=True).start()


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

    step = 2.0 if zoom <= 6 else WEATHER_FINEST
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


def _load_weather_radar() -> dict:
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


def weather_radar() -> dict:
    snap = _get_store("radar")
    if snap and snap.get("rain_url"):
        return {
            "source": snap.get("source") or "RainViewer",
            "rain_url": snap.get("rain_url"),
            "clouds_url": snap.get("clouds_url"),
            "time": snap.get("time"),
            "max_zoom": snap.get("max_zoom") or 7,
        }
    try:
        data = _load_weather_radar()
        _put_store("radar", {"items": [], **data})
        return data
    except httpx.HTTPError:
        return {"source": "RainViewer", "rain_url": None, "clouds_url": None, "time": None, "max_zoom": 7}


def weather_field(south: float, west: float, north: float, east: float, zoom: int) -> dict:
    _ = zoom
    south, west, north, east = normalize_weather_bbox(south, west, north, east)
    snap = _get_store("weather")
    if not snap:
        return {"items": [], "source": "Open-Meteo", "reason": "warming"}
    items = [
        item
        for item in snap["items"]
        if _in_bbox(item["lat"], item["lon"], south, west, north, east)
    ]
    return {"items": items, "grid": snap.get("grid") or {}, "source": snap.get("source") or "Open-Meteo"}


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
