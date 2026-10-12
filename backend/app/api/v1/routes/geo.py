from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from app.services import geo_service

router = APIRouter()
BBox = Annotated[float, Query()]


@router.get("/earthquakes")
def get_earthquakes() -> dict:
    try:
        return geo_service.earthquakes()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"USGS unavailable: {exc}") from exc


@router.get("/events")
def get_events() -> dict:
    try:
        return geo_service.events()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"EONET unavailable: {exc}") from exc


@router.get("/flights")
def get_flights(
    south: BBox,
    west: BBox,
    north: BBox,
    east: BBox,
    zoom: Annotated[int, Query(ge=0, le=22)] = 0,
) -> dict:
    try:
        return geo_service.flights(south, west, north, east, zoom=zoom)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Flight feed unavailable: {exc}") from exc


@router.get("/weather/radar")
def get_weather_radar() -> dict:
    try:
        return geo_service.weather_radar()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"RainViewer unavailable: {exc}") from exc


@router.get("/weather")
def get_weather(
    south: BBox,
    west: BBox,
    north: BBox,
    east: BBox,
    zoom: Annotated[int, Query(ge=0, le=22)] = 4,
) -> dict:
    try:
        return geo_service.weather_field(south, west, north, east, zoom)
    except httpx.HTTPError:
        return {"items": [], "source": "Open-Meteo", "reason": "feed_unavailable"}


@router.get("/imagery")
def get_imagery_meta(
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    zoom: Annotated[int, Query(ge=0, le=22)] = 8,
) -> dict:
    try:
        return geo_service.imagery_meta(lat, lon, zoom)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Imagery metadata unavailable: {exc}") from exc


@router.get("/cameras")
def get_cameras(
    south: BBox,
    west: BBox,
    north: BBox,
    east: BBox,
    zoom: Annotated[int, Query(ge=0, le=22)] = 0,
) -> dict:
    return geo_service.cameras(south, west, north, east, zoom=zoom)


@router.get("/cameras/{camera_id}/frame")
def get_camera_frame(camera_id: str) -> Response:
    frame = geo_service.camera_frame(camera_id)
    if not frame:
        raise HTTPException(status_code=404, detail="Camera frame unavailable")
    body, content_type = frame
    return Response(content=body, media_type=content_type, headers={"Cache-Control": "no-store"})


@router.get("/satellites")
def get_satellites() -> dict:
    return geo_service.satellites()


@router.get("/places")
def get_places(
    south: BBox,
    west: BBox,
    north: BBox,
    east: BBox,
    zoom: Annotated[int, Query(ge=0, le=22)] = 6,
) -> dict:
    try:
        return geo_service.places(south, west, north, east, zoom)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Overpass unavailable: {exc}") from exc
