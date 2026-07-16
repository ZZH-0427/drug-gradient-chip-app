from __future__ import annotations

import logging
from collections.abc import Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.errors import ModelRuntimeError
from app.core.config import resolve_frontend_origins
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
                logger.info(
                    "Forward model loaded successfully: ensemble_size=%s device=%s",
                    len(state.seeds or []),
                    state.device,
                )
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
    return fastapi_app


app = create_app()
