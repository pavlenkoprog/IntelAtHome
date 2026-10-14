import csv
import html
import io
import ipaddress
import json
import logging
import math
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urljoin, urlsplit

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
METNO_FORECAST = "https://api.met.no/weatherapi/locationforecast/2.0/compact"
STORM_CODES = {95, 96, 99}
TFL_JAMCAM = "https://api.tfl.gov.uk/Place/Type/JamCam"
TFL_IMAGE_ORIGIN = "https://s3-eu-west-1.amazonaws.com/jamcams.tfl.gov.uk/"
CALTRANS_DISTRICTS = (4, 7, 11, 3)
SNAPSHOT_THUMB_PREFIXES = (
    "http://insecam.org/static/thumb/",
    "https://insecam.org/static/thumb/",
    "http://www.insecam.org/static/thumb/",
    "https://www.insecam.org/static/thumb/",
)
CAMERA_IMAGE_PREFIXES = (
    TFL_IMAGE_ORIGIN,
    "https://cwwp2.dot.ca.gov/",
    *SNAPSHOT_THUMB_PREFIXES,
)
CAMERA_BBOX_CAP = 150
SATELLITES_URL = "https://dataengine.worldwideview.dev/data/surveillance_satellites"
SATELLITE_INTERVAL = 15

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
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "PalantirAtHome/0.1 (local globe; weather+flights)"},
    ) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def _get_text(url: str, timeout: float = 30.0) -> str:
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": "PalantirAtHome/0.1"}) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def _get_bytes(url: str, timeout: float = 8.0) -> tuple[bytes, str]:
    with httpx.Client(
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "PalantirAtHome/0.1 (local globe; cameras)"},
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        content_type = response.headers.get("content-type") or "image/jpeg"
        return response.content, content_type.split(";")[0].strip()


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


def _tfl_prop(place: dict, key: str) -> str:
    for item in place.get("additionalProperties") or []:
        if item.get("key") == key:
            return str(item.get("value") or "")
    return ""


def _parse_tfl_cameras(raw) -> list[dict]:
    items = []
    if not isinstance(raw, list):
        return items
    for place in raw:
        if _tfl_prop(place, "available").lower() != "true":
            continue
        try:
            lat = float(place.get("lat"))
            lon = float(place.get("lon"))
        except (TypeError, ValueError):
            continue
        image_url = _tfl_prop(place, "imageUrl")
        if not image_url.startswith(TFL_IMAGE_ORIGIN):
            continue
        raw_id = str(place.get("id") or "").replace("JamCams_", "")
        if not raw_id:
            continue
        items.append(
            {
                "id": f"tfl-{raw_id}",
                "name": place.get("commonName") or f"JamCam {raw_id}",
                "kind": "camera",
                "lat": lat,
                "lon": lon,
                "source": "TfL JamCam",
                "city": "London",
                "image_url": image_url,
            }
        )
    return items


def _parse_caltrans_cameras(raw, district: int) -> list[dict]:
    items = []
    rows = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(rows, list):
        return items
    for row in rows:
        cctv = (row or {}).get("cctv") or {}
        if str(cctv.get("inService") or "").lower() != "true":
            continue
        loc = cctv.get("location") or {}
        try:
            lat = float(loc.get("latitude"))
            lon = float(loc.get("longitude"))
        except (TypeError, ValueError):
            continue
        image_url = str(((cctv.get("imageData") or {}).get("static") or {}).get("currentImageURL") or "")
        if not image_url.startswith("https://cwwp2.dot.ca.gov/"):
            continue
        location_name = str(loc.get("locationName") or "").strip()
        code = location_name.split("--", 1)[0].strip().lower() or f"x{len(items)}"
        label = location_name.split("--", 1)[-1].strip() or f"Caltrans D{district}"
        place = str(loc.get("nearbyPlace") or "").strip()
        items.append(
            {
                "id": f"ca-d{district}-{code}",
                "name": f"{label} ({place})" if place else label,
                "kind": "camera",
                "lat": lat,
                "lon": lon,
                "source": "Caltrans",
                "city": place or f"Caltrans D{district}",
                "image_url": image_url,
            }
        )
    return items


def _refresh_cameras_snapshot() -> None:
    by_id: dict[str, dict] = {}
    try:
        for item in _parse_tfl_cameras(_get_json(TFL_JAMCAM, timeout=20.0)):
            by_id[item["id"]] = item
    except httpx.HTTPError as exc:
        log.info("tfl cameras failed: %s", exc)

    def load_district(district: int) -> list[dict]:
        url = f"https://cwwp2.dot.ca.gov/data/d{district}/cctv/cctvStatusD{district:02d}.json"
        return _parse_caltrans_cameras(_get_json(url, timeout=20.0), district)

    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in [pool.submit(load_district, district) for district in CALTRANS_DISTRICTS]:
            try:
                for item in future.result():
                    by_id[item["id"]] = item
            except httpx.HTTPError as exc:
                log.info("caltrans cameras failed: %s", exc)

    items = list(by_id.values())
    if not items:
        previous = _get_store("cameras") or {}
        items = [
            item
            for item in previous.get("items") or []
            if not str(item.get("id") or "").startswith("snap-")
        ]
    items.extend(_snapshot_cameras())
    if items:
        sources = sorted({str(item.get("source") or "") for item in items if item.get("source")})
        _put_store("cameras", {"items": items, "source": " / ".join(sources)})
        log.info("cameras snapshot %s", len(items))


def _snapshot_thumb(url: str) -> str:
    for prefix in SNAPSHOT_THUMB_PREFIXES:
        if url.startswith(prefix):
            name = url[len(prefix) :].split("?", 1)[0].split("/", 1)[0]
            if name.endswith(".jpg"):
                name = name[:-4]
            if name and all(char.isalnum() or char in "-_" for char in name):
                return name
    return ""


def _parse_snapshot_cameras(raw: Any) -> list[dict]:
    features = raw.get("features") if isinstance(raw, dict) else None
    if not isinstance(features, list):
        return []
    items: dict[str, dict] = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coords = geometry.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            continue
        try:
            lon = float(coords[0])
            lat = float(coords[1])
        except (TypeError, ValueError):
            continue
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        city = str(props.get("city") or "").strip()
        region = str(props.get("region") or "").strip()
        country = str(props.get("country") or "").strip()
        categories = props.get("categories")
        if isinstance(categories, list):
            category = ", ".join(str(value).strip() for value in categories if str(value).strip())
        else:
            category = ""
        preview = str(props.get("preview_url") or "").strip()
        thumb = _snapshot_thumb(preview)
        stream = _linkable_stream_url(str(props.get("stream") or ""))
        camera_id = f"snap-{thumb}" if thumb else f"snap-{lat:.5f}-{lon:.5f}"
        name = ", ".join(part for part in (city, region) if part) or country or "Camera"
        item = {
            "id": camera_id,
            "name": name,
            "kind": "camera",
            "lat": lat,
            "lon": lon,
            "source": "Дамп публичных камер",
            "city": city,
            "country": country,
            "category": category,
        }
        if thumb:
            item["image_url"] = preview
        if stream:
            item["stream_url"] = stream
        items[camera_id] = item
    return list(items.values())


_SNAPSHOT_CAMERAS: tuple[float, list[dict]] | None = None


def _snapshot_cameras() -> list[dict]:
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return []
    global _SNAPSHOT_CAMERAS
    path = SNAPSHOT_DIR / "cameras_geojson.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return []
    if _SNAPSHOT_CAMERAS and _SNAPSHOT_CAMERAS[0] == mtime:
        return _SNAPSHOT_CAMERAS[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.info("snapshot cameras unreadable: %s", exc)
        return []
    items = _parse_snapshot_cameras(raw)
    _SNAPSHOT_CAMERAS = (mtime, items)
    log.info("snapshot cameras %s", len(items))
    return items


def _camera_catalog() -> tuple[list[dict], str]:
    snap = _get_store("cameras") or {}
    live = [
        item
        for item in snap.get("items") or []
        if not str(item.get("id") or "").startswith("snap-")
    ]
    items = [*live, *_snapshot_cameras()]
    sources: list[str] = []
    for item in items:
        source = str(item.get("source") or "")
        if source and source not in sources:
            sources.append(source)
    return items, " / ".join(sources) or "TfL / Caltrans"


OFFICIAL_CAMERA_SOURCES = {"TfL JamCam", "Caltrans"}
_HIDDEN_CAMERA_KEYS = {"image_url", "stream_url"}


_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
    "youtu.be",
    "www.youtu.be",
}
_YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def _linkable_stream_url(url: str) -> str:
    raw = html.unescape(html.unescape(url.strip()))
    if not raw or len(raw) > 2000 or any(char.isspace() for char in raw):
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or port == 0:
        return ""
    return raw


def _youtube_embed_url(url: str) -> str:
    raw = _linkable_stream_url(url)
    if not raw:
        return ""
    parsed = urlsplit(raw)
    host = (parsed.hostname or "").lower()
    if host not in _YOUTUBE_HOSTS:
        return ""
    video_id = ""
    if host in {"youtu.be", "www.youtu.be"}:
        video_id = parsed.path.strip("/").split("/", 1)[0]
    else:
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 2 and parts[0] in {"embed", "shorts"}:
            video_id = parts[1]
        else:
            for key, value in parse_qsl(parsed.query):
                if key == "v" and value:
                    video_id = value
                    break
    if not _YOUTUBE_ID.fullmatch(video_id):
        return ""
    return f"https://www.youtube-nocookie.com/embed/{video_id}?autoplay=0"


def _safe_stream_url(url: str) -> str:
    raw = url.strip()
    if not raw or len(raw) > 2000 or any(char in raw for char in "\r\n\t "):
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return ""
    if parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        return ""
    host = parsed.hostname
    if not host or port == 0:
        return ""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return ""
    if not ip.is_global:
        return ""
    return raw


def _stream_media_type(header: str) -> str:
    value = header.strip()
    if not value:
        return "image/jpeg"
    base = value.split(";", 1)[0].strip().lower()
    if base in {"image/jpeg", "image/jpg"}:
        return "image/jpeg"
    if base in {"image/png", "image/gif", "image/webp"}:
        return base
    if base == "multipart/x-mixed-replace":
        return value
    return ""


def _public_camera(item: dict) -> dict:
    public = {key: value for key, value in item.items() if key not in _HIDDEN_CAMERA_KEYS}
    image = str(item.get("image_url") or "")
    stream = _linkable_stream_url(str(item.get("stream_url") or ""))
    embed = _youtube_embed_url(stream)
    public["has_frame"] = any(image.startswith(prefix) for prefix in CAMERA_IMAGE_PREFIXES)
    public["has_stream"] = bool(_safe_stream_url(stream))
    if embed:
        public["stream_url"] = embed
        public["embed"] = "youtube"
    elif stream:
        public["stream_url"] = stream
    official = item.get("source") in OFFICIAL_CAMERA_SOURCES and public["has_frame"]
    public["player"] = official or public["has_stream"]
    return public


def cameras(south: float, west: float, north: float, east: float, zoom: int | None = None) -> dict:
    if north <= south:
        return {"items": [], "source": "TfL / Caltrans", "reason": "bad_bbox"}
    catalog, source = _camera_catalog()
    if not catalog:
        return {"items": [], "source": source, "reason": "warming"}
    world = zoom is not None and zoom < 4
    if world:
        items = list(catalog)
        south, west, north, east = -85.0, -180.0, 85.0, 180.0
    else:
        items = [item for item in catalog if _in_bbox(item["lat"], item["lon"], south, west, north, east)]
    if len(items) > CAMERA_BBOX_CAP:
        if world or zoom is None or zoom < 8:
            items = _spread_flights(items, south, west, north, east, CAMERA_BBOX_CAP)
        else:
            mid_lat = (south + north) / 2
            mid_lon = (west + east) / 2
            items.sort(key=lambda item: (item["lat"] - mid_lat) ** 2 + (item["lon"] - mid_lon) ** 2)
            items = items[:CAMERA_BBOX_CAP]
    return {"items": [_public_camera(item) for item in items], "source": source}


def camera_record(camera_id: str) -> dict | None:
    catalog, _source = _camera_catalog()
    for item in catalog:
        if item.get("id") == camera_id:
            return item
    return None


def camera_frame(camera_id: str) -> tuple[bytes, str] | None:
    item = camera_record(camera_id)
    if not item:
        return None
    url = str(item.get("image_url") or "")
    if not any(url.startswith(prefix) for prefix in CAMERA_IMAGE_PREFIXES):
        return None
    try:
        return _get_bytes(url)
    except httpx.HTTPError:
        return None


def camera_stream_url(camera_id: str) -> str:
    item = camera_record(camera_id)
    if not item:
        return ""
    return _safe_stream_url(str(item.get("stream_url") or ""))


def open_camera_stream(camera_id: str):
    url = camera_stream_url(camera_id)
    if not url:
        return None
    client = httpx.Client(
        timeout=httpx.Timeout(8.0, read=20.0),
        follow_redirects=False,
        headers={"User-Agent": "PalantirAtHome/0.1 (local globe; cameras)"},
    )
    response = None
    try:
        current = url
        for _ in range(3):
            response = client.send(client.build_request("GET", current), stream=True)
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location") or ""
                response.close()
                response = None
                current = _safe_stream_url(urljoin(current, location))
                if not current:
                    client.close()
                    return None
                continue
            break
        if response is None or response.status_code != 200:
            if response is not None:
                response.close()
            client.close()
            return None
        media_type = _stream_media_type(response.headers.get("content-type") or "")
        if not media_type:
            response.close()
            client.close()
            return None

        def chunks():
            try:
                for chunk in response.iter_bytes():
                    if chunk:
                        yield chunk
            finally:
                response.close()
                client.close()

        return chunks(), media_type
    except httpx.HTTPError:
        log.info("camera stream failed: %s", camera_id)
        if response is not None:
            response.close()
        client.close()
        return None


def _refresh_radar_snapshot() -> None:
    data = _load_weather_radar()
    _put_store("radar", {"items": [], **data})
    log.info("radar snapshot %s", data.get("rain_url"))


_SATELLITE_LOOP_STARTED = False


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _norad_id(value: Any) -> int | str | None:
    if isinstance(value, bool) or value is None or value == "":
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    text = str(value).strip()
    return text or None


def _satellite_rows(raw: Any) -> list:
    if not isinstance(raw, dict):
        return []
    items = raw.get("items")
    if isinstance(items, dict):
        rows = items.get("satellites")
        return rows if isinstance(rows, list) else []
    if isinstance(items, list):
        return items
    return []


def _parse_satellites(raw: Any) -> list[dict]:
    parsed: list[dict] = []
    for row in _satellite_rows(raw):
        if not isinstance(row, dict):
            continue
        lat = _finite(row.get("latitude", row.get("lat")))
        lon = _finite(row.get("longitude", row.get("lon")))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue
        group = str(row.get("group") or "").strip().lower()
        if group not in {"military", "recon"}:
            continue
        norad = _norad_id(row.get("noradId", row.get("norad_id")))
        name = str(row.get("name") or norad or "Satellite").strip() or "Satellite"
        parsed.append(
            {
                "id": str(norad or name),
                "norad": norad,
                "name": name,
                "kind": "satellite",
                "group": group,
                "lat": lat,
                "lon": lon,
                "altitude": _finite(row.get("altitude")),
                "heading": _finite(row.get("heading")),
                "speed": _finite(row.get("speed")),
            }
        )
    return parsed


def refresh_satellites() -> None:
    raw = _get_json(SATELLITES_URL, timeout=20.0)
    items = _parse_satellites(raw)
    _put_store("satellites", {"items": items, "source": "CelesTrak"})
    log.info("satellites %s saved", len(items))


def satellites() -> dict:
    snap = _get_store("satellites")
    if snap and isinstance(snap.get("items"), list):
        return {"items": snap["items"], "source": snap.get("source") or "CelesTrak"}
    return {"items": [], "source": "CelesTrak", "reason": "warming"}


def start_satellite_loop() -> None:
    global _SATELLITE_LOOP_STARTED
    if _SATELLITE_LOOP_STARTED or os.environ.get("PYTEST_CURRENT_TEST"):
        return
    _SATELLITE_LOOP_STARTED = True

    def run() -> None:
        while True:
            try:
                refresh_satellites()
            except Exception as exc:
                log.info("satellites fetch failed: %s", exc)
            time.sleep(SATELLITE_INTERVAL)

    threading.Thread(target=run, name="satellites", daemon=True).start()


def refresh_snapshots() -> None:
    jobs = (
        ("earthquakes", lambda: _put_store("earthquakes", _load_earthquakes())),
        ("events", lambda: _put_store("events", _load_events())),
        ("radar", _refresh_radar_snapshot),
        ("flights", _refresh_flights_snapshot),
        ("cameras", _refresh_cameras_snapshot),
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
        start_satellite_loop()
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


def _parse_metno_cell(raw: dict, cell: dict) -> dict | None:
    series = ((raw.get("properties") or {}).get("timeseries") or [])
    if not series:
        return None
    data = (series[0].get("data") or {})
    instant = ((data.get("instant") or {}).get("details")) or {}
    nxt = data.get("next_1_hours") or data.get("next_6_hours") or {}
    symbol = str(((nxt.get("summary") or {}).get("symbol_code") or "")).lower()
    return {
        **cell,
        "kind": "weather",
        "cloud_cover": instant.get("cloud_area_fraction"),
        "precipitation": (nxt.get("details") or {}).get("precipitation_amount"),
        "wind_speed": instant.get("wind_speed"),
        "wind_direction": instant.get("wind_from_direction"),
        "weather_code": symbol or None,
        "storm": "thunder" in symbol,
    }


def _weather_from_metno(cells: list[dict], grid: dict) -> dict:
    stride = max(1, math.ceil(len(cells) / 20))
    sample = cells[::stride][:20]
    items: list[dict] = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = [
            pool.submit(
                _get_json,
                METNO_FORECAST,
                12.0,
                {"lat": f"{cell['lat']:.3f}", "lon": f"{cell['lon']:.3f}"},
            )
            for cell in sample
        ]
        for cell, future in zip(sample, futures, strict=False):
            try:
                item = _parse_metno_cell(future.result(), cell)
            except httpx.HTTPError:
                continue
            if item:
                items.append(item)
    return {"items": items, "grid": grid, "source": "MET Norway"}


def _weather_stale(key: str) -> dict | None:
    hit = _CACHE.get(key)
    if hit:
        return hit[1]
    last = _CACHE.get("weather-last")
    return last[1] if last else None


def weather_field(south: float, west: float, north: float, east: float, zoom: int) -> dict:
    south, west, north, east = normalize_weather_bbox(south, west, north, east)
    cells, grid = build_weather_grid(south, west, north, east, zoom)
    if not cells:
        return {"items": [], "source": "Open-Meteo", "reason": "empty_grid"}

    key = f"wx:{grid['south']:.0f}:{grid['west']:.0f}:{grid['dlat']:.1f}:{grid['rows']}:{grid['cols']}"
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < 600:
        return hit[1]

    fetched_at = _CACHE.get("weather-fetch-at")
    if fetched_at and now - fetched_at[0] < 12:
        stale = _weather_stale(key)
        if stale:
            return stale

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

    try:
        value = load()
    except httpx.HTTPError:
        value = _weather_from_metno(cells, grid)
        if not value["items"]:
            stale = _weather_stale(key)
            if stale:
                return stale
            return {"items": [], "grid": grid, "source": "Open-Meteo", "reason": "feed_unavailable"}
    _CACHE[key] = (now, value)
    _CACHE["weather-last"] = (now, value)
    _CACHE["weather-fetch-at"] = (now, True)
    return value


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
