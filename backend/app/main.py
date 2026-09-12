from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles


class FrontendStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        if path.endswith(".js"):
            response.headers["content-type"] = "application/javascript; charset=utf-8"
        elif path.endswith(".css"):
            response.headers["content-type"] = "text/css; charset=utf-8"
        return response

from app.api.v1.router import api_router
from app.config import settings
from app.db.session import init_db
from app.services.geo_service import warmup_catalogs

FRONTEND_DIR = Path(__file__).resolve().parents[2] / "frontend"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    warmup_catalogs()
    yield


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Local investigation workspace",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")

    if FRONTEND_DIR.exists():
        app.mount("/", FrontendStaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

    return app


app = create_app()
