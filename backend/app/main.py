from __future__ import annotations

import logging
import json
import os
from pathlib import Path
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.config import (
    resolve_frontend_dist_dir,
    resolve_frontend_origins,
    resolve_serve_frontend,
)
from app.core.errors import ModelRuntimeError
from app.core.model_state import ForwardAdapterProtocol, ForwardModelState
from app.model_runtime.forward_adapter import ForwardModelAdapter


logger = logging.getLogger(__name__)


def create_app(
    *,
    adapter_factory: Callable[[], ForwardAdapterProtocol] | None = None,
    load_model: bool = True,
) -> FastAPI:
    factory = adapter_factory or ForwardModelAdapter

    @asynccontextmanager
    async def lifespan(app_instance: FastAPI) -> Any:
        logger.info("Starting drug gradient chip API.")
        app_instance.state.forward_model = ForwardModelState.not_ready(
            code="MODEL_NOT_READY",
            message="Forward model has not been loaded.",
        )
        if load_model:
            try:
                logger.info("Loading forward model adapter.")
                adapter = factory()
                app_instance.state.forward_model = ForwardModelState.ready_state(adapter)
                state = app_instance.state.forward_model
                settings = getattr(adapter, "settings", None)
                logger.info(
                    "Forward model loaded successfully: model=%s device=%s asset_source=%s",
                    state.model_name,
                    state.device,
                    getattr(settings, "asset_source", "unknown"),
                )
                logging.getLogger("uvicorn.error").info(
                    "Forward model loaded successfully: model=%s device=%s asset_source=%s",
                    state.model_name,
                    state.device,
                    getattr(settings, "asset_source", "unknown"),
                )
                write_local_app_process_identity()
            except ModelRuntimeError as exc:
                logger.exception("Forward model loading failed: %s", exc)
                app_instance.state.forward_model = ForwardModelState.not_ready(
                    code="MODEL_CONFIGURATION_ERROR",
                    message="Forward model configuration is invalid.",
                )
            except Exception as exc:
                logger.exception("Unexpected forward model loading failure")
                app_instance.state.forward_model = ForwardModelState.not_ready(
                    code="MODEL_CONFIGURATION_ERROR",
                    message="Forward model failed to load.",
                )
        yield

    fastapi_app = FastAPI(
        title="Drug Gradient Chip API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @fastapi_app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Any, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": "Request validation failed.",
                }
            },
        )

    frontend_origins = resolve_frontend_origins()
    if frontend_origins:
        fastapi_app.add_middleware(
            CORSMiddleware,
            allow_origins=frontend_origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type"],
        )
    fastapi_app.include_router(api_router)
    configure_frontend_serving(fastapi_app)
    return fastapi_app


def write_local_app_process_identity() -> None:
    token = os.getenv("LOCAL_APP_IDENTITY_TOKEN", "").strip()
    identity_path = os.getenv("LOCAL_APP_IDENTITY_FILE", "").strip()
    if not token or not identity_path:
        return

    path = Path(identity_path)
    payload = {
        "schema_version": 1,
        "pid": os.getpid(),
        "identity_token": token,
        "application_root": os.getenv("LOCAL_APP_APPLICATION_ROOT", ""),
        "app_module": os.getenv("LOCAL_APP_MODULE", ""),
        "host": os.getenv("LOCAL_APP_HOST", ""),
        "port": os.getenv("LOCAL_APP_PORT", ""),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def configure_frontend_serving(fastapi_app: FastAPI) -> None:
    if not resolve_serve_frontend():
        logger.info("Frontend static serving disabled.")
        return

    dist_dir = resolve_frontend_dist_dir()
    assets_dir = dist_dir / "assets"
    index_path = dist_dir / "index.html"

    if not dist_dir.exists() or not index_path.is_file():
        logger.warning("Frontend static serving enabled but dist directory is incomplete.")
        return

    logger.info("Frontend static serving enabled: dist=%s", dist_dir)
    if assets_dir.is_dir():
        fastapi_app.mount(
            "/assets",
            StaticFiles(directory=assets_dir, html=False),
            name="frontend-assets",
        )
    else:
        logger.warning("Frontend assets directory is missing.")

    favicon_path = dist_dir / "favicon.svg"

    @fastapi_app.get("/favicon.svg", include_in_schema=False, response_model=None)
    def serve_favicon():
        if favicon_path.is_file():
            return FileResponse(favicon_path)
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @fastapi_app.get("/{path:path}", include_in_schema=False, response_model=None)
    def serve_spa(path: str):
        if path == "api" or path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not Found"})
        return FileResponse(index_path)


app = create_app()
