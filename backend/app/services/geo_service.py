import csv
import io
import time
from typing import Any

import httpx

USGS_QUAKES = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_day.geojson"
EONET_EVENTS = "https://eonet.gsfc.nasa.gov/api/v3/events"
OPENSKY_STATES = "https://opensky-network.org/api/states/all"
ADSB_LOL = "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{dist}"
LAUNCHES = "https://ll.thespacedevs.com/2.2.0/launch/upcoming/?limit=20"
NE_PLACES = "https://cdn.jsdelivr.net/gh/nvkelso/natural-earth-vector@master/geojson/ne_50m_populated_places_simple.geojson"
OPENFLIGHTS = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"

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


def flights(south: float, west: float, north: float, east: float) -> dict:
    if north <= south or abs(north - south) > 80 or abs(east - west) > 120:
        return {"items": [], "source": "OpenSky", "reason": "bbox_too_large"}

    key = f"flights:{south:.1f}:{west:.1f}:{north:.1f}:{east:.1f}"

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
                items.append(
                    {
                        "id": state[0],
                        "name": (state[1] or state[0] or "Flight").strip(),
                        "kind": "flight",
                        "lat": state[6],
                        "lon": state[5],
                        "altitude": state[7],
                        "country": state[2],
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
                items.append(
                    {
                        "id": ac.get("hex"),
                        "name": ac.get("flight") or ac.get("r") or ac.get("hex") or "Flight",
                        "kind": "flight",
                        "lat": ac.get("lat"),
                        "lon": ac.get("lon"),
                        "altitude": ac.get("alt_baro"),
                        "country": None,
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
        if _in_bbox(item["lat"], item["lon"], south, west, north, east)
        and (zoom >= 6 or item["kind"] == "city")
    ]
    if zoom >= 6:
        items.extend(
            item
            for item in _openflights_airports()
            if _in_bbox(item["lat"], item["lon"], south, west, north, east)
        )
    return {"items": items[:400], "source": "Natural Earth / OpenFlights"}
