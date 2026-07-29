import sys
from pathlib import Path

import pytest


def _command(log_path: Path) -> list[str]:
    script = Path(__file__).with_name("fake_app_server.py")
    return [sys.executable, str(script), str(log_path)]


@pytest.mark.asyncio
async def test_client_initializes_before_listing_threads(tmp_path: Path) -> None:
    from codex_task_monitor.codex_adapter.client import AppServerClient

    log_path = tmp_path / "methods.log"
    client = AppServerClient(_command(log_path))

    await client.start()
    result = await client.request(
        "thread/list",
        {"useStateDbOnly": True},
    )
    await client.stop()

    assert result["data"][0]["id"] == "thread-1"
    assert log_path.read_text(encoding="utf-8").splitlines()[:3] == [
        "initialize",
        "initialized",
        "thread/list",
    ]


@pytest.mark.asyncio
async def test_client_publishes_server_notifications(tmp_path: Path) -> None:
    from codex_task_monitor.codex_adapter.client import AppServerClient

    client = AppServerClient(_command(tmp_path / "methods.log"))

    await client.start()
    notification = await client.next_notification(timeout=1)
    await client.stop()

    assert notification["method"] == "thread/status/changed"
    assert notification["params"]["threadId"] == "thread-1"


@pytest.mark.asyncio
async def test_request_timeout_does_not_leave_pending_future(tmp_path: Path) -> None:
    from codex_task_monitor.codex_adapter.client import AppServerClient

    client = AppServerClient(
        _command(tmp_path / "methods.log"),
        request_timeout=0.05,
    )
    await client.start()

    with pytest.raises(TimeoutError):
        await client.request("never/respond", {})

    assert client.pending_request_count == 0
    await client.stop()


@pytest.mark.asyncio
async def test_stop_is_idempotent(tmp_path: Path) -> None:
    from codex_task_monitor.codex_adapter.client import AppServerClient

    client = AppServerClient(_command(tmp_path / "methods.log"))
    await client.start()

    await client.stop()
    await client.stop()

    assert client.connected is False


@pytest.mark.asyncio
async def test_client_accepts_jsonl_larger_than_asyncio_default(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.codex_adapter.client import AppServerClient

    client = AppServerClient(_command(tmp_path / "methods.log"))
    await client.start()

    result = await client.request("large/response", {})
    await client.stop()

    assert len(result["payload"]) == 100_000
