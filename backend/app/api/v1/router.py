from fastapi import APIRouter

from app.api.v1.routes import datasets, entities, geo, health, investigations, media

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(geo.router, prefix="/geo", tags=["geo"])
api_router.include_router(media.router, prefix="/media", tags=["media"])
api_router.include_router(datasets.router, prefix="/datasets", tags=["datasets"])
api_router.include_router(entities.router, prefix="/entities", tags=["entities"])
api_router.include_router(investigations.router, prefix="/investigations", tags=["investigations"])
