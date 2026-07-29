import json

import httpx
import pytest
import respx

from codex_task_monitor.config.models import FeishuConfig


def _config() -> FeishuConfig:
    return FeishuConfig(
        app_id="cli_test",
        app_secret="secret-test",
        receive_id="ou_test",
        receive_id_type="open_id",
    )


@pytest.mark.asyncio
@respx.mock
async def test_sends_text_message_with_cached_tenant_token() -> None:
    from codex_task_monitor.notifications.feishu import FeishuClient

    token_route = respx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": "t-test-token", "expire": 7200},
        )
    )
    message_route = respx.post(
        "https://open.feishu.cn/open-apis/im/v1/messages",
        params={"receive_id_type": "open_id"},
    ).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "data": {"message_id": "om_test"}},
        )
    )
    client = FeishuClient(_config(), sleep=lambda _: _no_wait())

    first = await client.send_text("第一条")
    second = await client.send_text("第二条")
    await client.close()

    assert first == "om_test"
    assert second == "om_test"
    assert token_route.call_count == 1
    assert message_route.call_count == 2
    request_body = json.loads(message_route.calls[0].request.content)
    assert request_body["receive_id"] == "ou_test"
    assert request_body["msg_type"] == "text"
    assert json.loads(request_body["content"]) == {"text": "第一条"}
    assert message_route.calls[0].request.headers["Authorization"] == "Bearer t-test-token"


@pytest.mark.asyncio
@respx.mock
async def test_authentication_error_refreshes_token_once() -> None:
    from codex_task_monitor.notifications.feishu import FeishuClient

    respx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    ).mock(
        side_effect=[
            httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "t-old", "expire": 7200},
            ),
            httpx.Response(
                200,
                json={"code": 0, "tenant_access_token": "t-new", "expire": 7200},
            ),
        ]
    )
    message_route = respx.post(
        "https://open.feishu.cn/open-apis/im/v1/messages"
    ).mock(
        side_effect=[
            httpx.Response(200, json={"code": 99991663, "msg": "token invalid"}),
            httpx.Response(
                200,
                json={"code": 0, "data": {"message_id": "om_test"}},
            ),
        ]
    )
    client = FeishuClient(_config(), sleep=lambda _: _no_wait())

    message_id = await client.send_text("测试")
    await client.close()

    assert message_id == "om_test"
    assert message_route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_rate_limit_is_retried_three_times() -> None:
    from codex_task_monitor.notifications.feishu import FeishuClient

    respx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": "t-test", "expire": 7200},
        )
    )
    route = respx.post(
        "https://open.feishu.cn/open-apis/im/v1/messages"
    ).mock(
        side_effect=[
            httpx.Response(429, json={"code": 230049, "msg": "busy"}),
            httpx.Response(503, json={"code": 1, "msg": "unavailable"}),
            httpx.Response(
                200,
                json={"code": 0, "data": {"message_id": "om_test"}},
            ),
        ]
    )
    client = FeishuClient(_config(), sleep=lambda _: _no_wait())

    assert await client.send_text("测试") == "om_test"
    await client.close()
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_permission_error_is_not_retried() -> None:
    from codex_task_monitor.notifications.feishu import FeishuApiError, FeishuClient

    respx.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    ).mock(
        return_value=httpx.Response(
            200,
            json={"code": 0, "tenant_access_token": "t-test", "expire": 7200},
        )
    )
    route = respx.post(
        "https://open.feishu.cn/open-apis/im/v1/messages"
    ).mock(
        return_value=httpx.Response(
            400,
            json={"code": 230013, "msg": "bot unavailable"},
        )
    )
    client = FeishuClient(_config(), sleep=lambda _: _no_wait())

    with pytest.raises(FeishuApiError, match="230013"):
        await client.send_text("测试")
    await client.close()

    assert route.call_count == 1


async def _no_wait() -> None:
    return None
