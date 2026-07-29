"""飞书自建应用鉴权与文本消息发送。"""

import asyncio
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from codex_task_monitor.config.models import FeishuConfig

AUTH_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
MESSAGE_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
AUTH_ERROR_CODES = {99991663, 99991668, 99991677}
RETRYABLE_API_CODES = {230049}


class FeishuApiError(RuntimeError):
    """飞书 OpenAPI 返回的结构化错误。"""

    def __init__(self, code: int, message: str, *, retryable: bool = False) -> None:
        self.code = code
        self.retryable = retryable
        super().__init__(f"飞书 API 错误 {code}: {message[:300]}")


class FeishuClient:
    """缓存租户令牌并发送飞书私聊文本。"""

    def __init__(
        self,
        config: FeishuConfig,
        *,
        client: httpx.AsyncClient | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.config = config
        self._client = client or httpx.AsyncClient(timeout=10)
        self._owns_client = client is None
        self._sleep = sleep
        self._token: str | None = None
        self._token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    @property
    def configured(self) -> bool:
        """返回发送消息所需字段是否完整。"""

        return bool(
            self.config.app_id
            and self.config.app_secret
            and self.config.receive_id
        )

    async def close(self) -> None:
        """关闭内部创建的 HTTP 客户端。"""

        if self._owns_client:
            await self._client.aclose()

    async def send_text(self, text: str) -> str:
        """发送文本并返回飞书消息 ID。"""

        if not self.configured:
            raise FeishuApiError(0, "飞书应用凭据或接收人未配置")

        token = await self._tenant_token()
        refreshed = False
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                response = await self._client.post(
                    MESSAGE_URL,
                    params={"receive_id_type": self.config.receive_id_type},
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json; charset=utf-8",
                    },
                    json={
                        "receive_id": self.config.receive_id,
                        "msg_type": "text",
                        "content": json.dumps({"text": text}, ensure_ascii=False),
                    },
                )
                payload = _response_payload(response)
                code = int(payload.get("code", response.status_code))
                if code in AUTH_ERROR_CODES and not refreshed:
                    self._token = None
                    token = await self._tenant_token(force=True)
                    refreshed = True
                    continue
                if _is_retryable(response.status_code, code):
                    raise FeishuApiError(
                        code,
                        str(payload.get("msg", "临时错误")),
                        retryable=True,
                    )
                if response.status_code >= 400 or code != 0:
                    raise FeishuApiError(code, str(payload.get("msg", "请求失败")))
                message_id = payload.get("data", {}).get("message_id")
                if not isinstance(message_id, str) or not message_id:
                    raise FeishuApiError(0, "响应缺少 message_id")
                return message_id
            except (httpx.RequestError, FeishuApiError) as error:
                last_error = error
                retryable = isinstance(error, httpx.RequestError) or error.retryable
                if not retryable or attempt == 2:
                    raise
                await self._sleep((2**attempt) * 0.1 + random.random() * 0.05)
        if last_error:
            raise last_error
        raise FeishuApiError(0, "发送流程意外结束")

    async def _tenant_token(self, *, force: bool = False) -> str:
        """获取或复用仍有安全余量的租户令牌。"""

        if not force and self._token and time.monotonic() < self._token_expires_at:
            return self._token
        async with self._token_lock:
            if not force and self._token and time.monotonic() < self._token_expires_at:
                return self._token
            response = await self._client.post(
                AUTH_URL,
                headers={"Content-Type": "application/json; charset=utf-8"},
                json={
                    "app_id": self.config.app_id,
                    "app_secret": self.config.app_secret,
                },
            )
            payload = _response_payload(response)
            code = int(payload.get("code", response.status_code))
            if response.status_code >= 400 or code != 0:
                raise FeishuApiError(code, str(payload.get("msg", "鉴权失败")))
            token = payload.get("tenant_access_token")
            if not isinstance(token, str) or not token:
                raise FeishuApiError(0, "鉴权响应缺少 tenant_access_token")
            expire = int(payload.get("expire", 7200))
            self._token = token
            self._token_expires_at = time.monotonic() + max(1, expire - 300)
            return token


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    """安全解析飞书 JSON 响应。"""

    try:
        payload = response.json()
    except ValueError as error:
        raise FeishuApiError(response.status_code, "响应不是有效 JSON") from error
    if not isinstance(payload, dict):
        raise FeishuApiError(response.status_code, "响应 JSON 不是对象")
    return payload


def _is_retryable(status_code: int, code: int) -> bool:
    """判断 HTTP 或业务错误是否适合短暂重试。"""

    return status_code == 429 or status_code >= 500 or code in RETRYABLE_API_CODES
