"""本地 Web 服务的 Host 和 CSRF 防护。"""

import secrets
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from starlette.responses import JSONResponse, Response

CSRF_COOKIE = "codex_monitor_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
MiddlewareNext = Callable[[Request], Awaitable[Response]]


def normalize_host(value: str) -> str:
    """规范化 Host，保留端口以便精确校验。"""

    return value.strip().lower().rstrip(".")


def host_is_allowed(host: str, allowed_hosts: set[str]) -> bool:
    """判断请求 Host 是否在本机白名单中。"""

    normalized = normalize_host(host)
    return normalized in {normalize_host(item) for item in allowed_hosts}


def same_origin(request: Request) -> bool:
    """验证 Origin 或 Referer 与当前请求 Host 同源。"""

    source = request.headers.get("origin") or request.headers.get("referer")
    if not source:
        return False
    parsed = urlsplit(source)
    return parsed.scheme in {"http", "https"} and normalize_host(
        parsed.netloc
    ) == normalize_host(request.headers.get("host", ""))


def install_security_middleware(
    app: FastAPI,
    *,
    allowed_hosts: set[str],
) -> None:
    """给 FastAPI 应用安装本地访问和写操作防护。"""

    @app.middleware("http")
    async def security_middleware(
        request: Request,
        call_next: MiddlewareNext,
    ) -> Response:
        host = request.headers.get("host", "")
        if not host_is_allowed(host, allowed_hosts):
            return JSONResponse(
                {"detail": "请求 Host 不受信任"},
                status_code=400,
            )

        if (
            request.url.path.startswith("/api/")
            and request.method not in SAFE_METHODS
        ):
            cookie_token = request.cookies.get(CSRF_COOKIE, "")
            header_token = request.headers.get(CSRF_HEADER, "")
            if (
                not cookie_token
                or not header_token
                or not secrets.compare_digest(cookie_token, header_token)
                or not same_origin(request)
            ):
                return JSONResponse(
                    {"detail": "CSRF 校验失败"},
                    status_code=403,
                )
            content_length = request.headers.get("content-length", "")
            transfer_encoding = request.headers.get("transfer-encoding", "")
            has_body = (
                content_length not in {"", "0"}
                or bool(transfer_encoding)
            )
            if request.method != "DELETE" and has_body:
                content_type = request.headers.get("content-type", "")
                if not content_type.startswith("application/json"):
                    return JSONResponse(
                        {"detail": "写接口仅接受 JSON"},
                        status_code=415,
                    )

        response = await call_next(request)
        if not request.cookies.get(CSRF_COOKIE):
            response.set_cookie(
                CSRF_COOKIE,
                secrets.token_urlsafe(32),
                httponly=False,
                samesite="strict",
                secure=False,
                path="/",
            )
        return response
