from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from app.model_runtime.reverse_tasks import ReverseTaskManager
from app.schemas.common import ErrorResponse
from app.schemas.reverse import (
    ReverseDesignRequest,
    ReverseTaskCreatedResponse,
    ReverseTaskStatusResponse,
)


logger = logging.getLogger(__name__)
router = APIRouter(tags=["reverse"])


def get_reverse_task_manager() -> ReverseTaskManager:
    return ReverseTaskManager.default()


@router.post(
    "/reverse-tasks",
    response_model=ReverseTaskCreatedResponse,
    status_code=202,
    responses={409: {"model": ErrorResponse}, 503: {"model": ErrorResponse}},
)
def create_reverse_task(
    request: ReverseDesignRequest,
    manager: ReverseTaskManager = Depends(get_reverse_task_manager),
) -> ReverseTaskCreatedResponse:
    try:
        status = manager.create(request)
        return ReverseTaskCreatedResponse(task_id=status.task_id, status=status.status)
    except RuntimeError as exc:
        if str(exc) == "busy":
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "REVERSE_TASK_BUSY",
                        "message": "已有反向设计任务正在运行，请等待完成或取消后再提交。",
                    }
                },
            )
        raise
    except Exception:
        logger.exception("Failed to create reverse design task.")
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "REVERSE_MODEL_UNAVAILABLE",
                    "message": "反向设计模型暂不可用。",
                }
            },
        )


@router.get(
    "/reverse-tasks/{task_id}",
    response_model=ReverseTaskStatusResponse,
    responses={404: {"model": ErrorResponse}},
)
def get_reverse_task(
    task_id: str,
    manager: ReverseTaskManager = Depends(get_reverse_task_manager),
) -> ReverseTaskStatusResponse:
    status = manager.get(task_id)
    if status is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "REVERSE_TASK_NOT_FOUND",
                    "message": "未找到反向设计任务。",
                }
            },
        )
    return status


@router.delete(
    "/reverse-tasks/{task_id}",
    response_model=ReverseTaskStatusResponse,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def cancel_reverse_task(
    task_id: str,
    manager: ReverseTaskManager = Depends(get_reverse_task_manager),
) -> ReverseTaskStatusResponse:
    try:
        status = manager.cancel(task_id)
    except RuntimeError as exc:
        if str(exc) == "not_cancellable":
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "code": "REVERSE_TASK_NOT_CANCELLABLE",
                        "message": "该反向设计任务当前不可取消。",
                    }
                },
            )
        raise
    if status is None:
        return JSONResponse(
            status_code=404,
            content={
                "error": {
                    "code": "REVERSE_TASK_NOT_FOUND",
                    "message": "未找到反向设计任务。",
                }
            },
        )
    return status
