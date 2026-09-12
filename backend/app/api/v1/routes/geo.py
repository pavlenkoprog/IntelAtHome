from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Query

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


@router.get("/launches")
def get_launches() -> dict:
    try:
        return geo_service.launches()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Launch Library unavailable: {exc}") from exc


@router.get("/flights")
def get_flights(south: BBox, west: BBox, north: BBox, east: BBox) -> dict:
    try:
        return geo_service.flights(south, west, north, east)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Flight feed unavailable: {exc}") from exc


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
