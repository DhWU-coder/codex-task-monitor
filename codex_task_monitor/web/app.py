"""FastAPI 应用工厂。"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from codex_task_monitor.config.service import ConfigService
from codex_task_monitor.web.api import create_api_router
from codex_task_monitor.web.events import EventBroker
from codex_task_monitor.web.security import install_security_middleware

STATIC_DIRECTORY = Path(__file__).resolve().parent / "static"


def create_app(
    *,
    runtime: Any,
    config_service: ConfigService,
    manage_runtime: bool = True,
    allowed_hosts: set[str] | None = None,
    broker: EventBroker | None = None,
) -> FastAPI:
    """创建可测试、可由 CLI 启动的本地 Web 应用。"""

    event_broker = broker or EventBroker()
    runtime.publisher = event_broker

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """按应用生命周期启动和停止监控运行时。"""

        if manage_runtime:
            await runtime.start()
        try:
            yield
        finally:
            if manage_runtime:
                await runtime.stop()

    app = FastAPI(
        title="Codex 任务监控器",
        version="0.1.0",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
    )
    app.state.event_broker = event_broker
    config = config_service.load()
    hosts = allowed_hosts or {
        config.server.host,
        f"{config.server.host}:{config.server.port}",
        "127.0.0.1",
        f"127.0.0.1:{config.server.port}",
        "localhost",
        f"localhost:{config.server.port}",
        "[::1]",
        f"[::1]:{config.server.port}",
    }
    install_security_middleware(app, allowed_hosts=hosts)
    app.include_router(
        create_api_router(
            runtime=runtime,
            config_service=config_service,
            broker=event_broker,
        )
    )
    _install_frontend(app)
    return app


def _install_frontend(app: FastAPI) -> None:
    """挂载前端构建资源并提供历史路由回退。"""

    index_path = STATIC_DIRECTORY / "index.html"
    assets_path = STATIC_DIRECTORY / "assets"
    if index_path.is_file() and assets_path.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=assets_path),
            name="frontend-assets",
        )

        @app.get("/", include_in_schema=False)
        async def frontend_index() -> FileResponse:
            """返回前端入口。"""

            return FileResponse(index_path)

        @app.get("/{frontend_path:path}", include_in_schema=False)
        async def frontend_fallback(frontend_path: str) -> FileResponse:
            """仅为非 API 地址回退到前端入口。"""

            if frontend_path == "healthz" or frontend_path.startswith(
                ("api/", "healthz/")
            ):
                raise HTTPException(status_code=404, detail="接口不存在")
            return FileResponse(index_path)

        return

    @app.get("/", include_in_schema=False)
    async def frontend_not_built() -> PlainTextResponse:
        """在未构建前端时返回明确提示。"""

        return PlainTextResponse(
            "前端尚未构建，请在 frontend 目录执行 npm install && npm run build。",
            status_code=503,
        )
