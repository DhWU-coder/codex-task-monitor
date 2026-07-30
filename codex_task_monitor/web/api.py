"""本地任务监控器的 HTTP 和 SSE 接口。"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, HTTPException, Request
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from codex_task_monitor.config.service import ConfigService
from codex_task_monitor.web.events import EventBroker
from codex_task_monitor.web.schemas import WatchRequest


def create_api_router(
    *,
    runtime: Any,
    config_service: ConfigService,
    broker: EventBroker,
) -> APIRouter:
    """创建绑定到指定运行时的 API 路由。"""

    router = APIRouter()

    @router.get("/api/tasks")
    async def list_tasks() -> dict[str, Any]:
        """列出聚合后的 Codex 任务。"""

        return {
            "tasks": [
                task.model_dump(mode="json")
                for task in runtime.list_tasks()
            ]
        }

    @router.get("/api/tasks/{thread_id}")
    async def get_task(thread_id: str) -> dict[str, Any]:
        """读取单个任务详情。"""

        task = runtime.get_task(thread_id)
        if task is None:
            raise HTTPException(status_code=404, detail="任务不存在")
        return task.model_dump(mode="json")

    @router.post("/api/tasks/{thread_id}/watch")
    async def start_watch(
        thread_id: str,
        payload: WatchRequest,
    ) -> dict[str, Any]:
        """启动当前轮次或持续监控。"""

        try:
            await runtime.start_watch(thread_id, payload.mode)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="任务不存在或已结束",
            ) from error
        return {"ok": True, "mode": payload.mode.value}

    @router.post("/api/tasks/{thread_id}/manual-completion")
    async def mark_manual_completion(thread_id: str) -> dict[str, Any]:
        """把活动任务的当前轮次标记为手动结束。"""

        try:
            task = await runtime.mark_manual_completion(thread_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="任务不存在",
            ) from error
        except ValueError as error:
            raise HTTPException(
                status_code=409,
                detail="任务当前轮次已经结束",
            ) from error
        return task.model_dump(mode="json")

    @router.delete("/api/tasks/{thread_id}/watch")
    async def stop_watch(thread_id: str) -> dict[str, bool]:
        """停止指定任务的监控。"""

        await runtime.stop_watch(thread_id)
        return {"ok": True}

    @router.get("/api/config")
    async def get_config() -> dict[str, Any]:
        """返回遮罩后的配置。"""

        return config_service.to_public_dict()

    @router.put("/api/config")
    async def update_config(
        payload: Annotated[dict[str, Any], Body()],
    ) -> dict[str, Any]:
        """验证、保存并热应用 UI 配置。"""

        previous = config_service.load()
        try:
            updated = config_service.update_from_public(payload)
        except ValidationError as error:
            raise HTTPException(
                status_code=422,
                detail=error.errors(include_url=False),
            ) from error
        await runtime.apply_config(payload)
        response = config_service.to_public_dict()
        response["restart_required"] = (
            previous.server.host != updated.server.host
            or previous.server.port != updated.server.port
        )
        return response

    @router.post("/api/notifications/test")
    async def test_notification() -> dict[str, str]:
        """显式发送一条飞书测试消息。"""

        message_id = await runtime.test_notification()
        return {"message_id": message_id}

    @router.post("/api/notifications/{notification_id}/retry")
    async def retry_notification(notification_id: int) -> dict[str, str]:
        """显式重试一条失败通知。"""

        try:
            message_id = await runtime.retry_notification(notification_id)
        except KeyError as error:
            raise HTTPException(
                status_code=404,
                detail="通知不存在或不可重试",
            ) from error
        return {"message_id": message_id}

    @router.get("/api/events")
    async def stream_events(request: Request) -> StreamingResponse:
        """通过 SSE 推送任务和健康状态变化。"""

        return StreamingResponse(
            broker.stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @router.get("/healthz")
    async def health() -> dict[str, Any]:
        """返回本地进程和数据源健康状态。"""

        return {
            "status": "ok",
            "sources": {
                name: (
                    source.model_dump(mode="json")
                    if hasattr(source, "model_dump")
                    else source
                )
                for name, source in runtime.health.items()
            },
        }

    return router
