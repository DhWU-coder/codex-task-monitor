from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from codex_task_monitor.config.service import ConfigService
from codex_task_monitor.models import (
    SourceKind,
    TaskSnapshot,
    TaskStatus,
    WatchMode,
)


class FakeRuntime:
    def __init__(self) -> None:
        self.task = TaskSnapshot(
            thread_id="thread-1",
            turn_id="turn-1",
            title="实现任务监控器",
            status=TaskStatus.RUNNING,
            source=SourceKind.MERGED,
            project_name="codex-task-monitor",
            cwd="/work/codex-task-monitor",
            branch="feature/monitor",
            updated_at=datetime.now(UTC),
        )
        self.health = {}
        self.watch_mode: WatchMode | None = None
        self.test_messages = 0
        self.retried: list[int] = []

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def list_tasks(self) -> list[TaskSnapshot]:
        return [self.task]

    def get_task(self, thread_id: str) -> TaskSnapshot | None:
        return self.task if thread_id == self.task.thread_id else None

    async def start_watch(self, thread_id: str, mode: WatchMode) -> object:
        self.watch_mode = mode
        return object()

    async def stop_watch(self, thread_id: str) -> None:
        self.watch_mode = None

    async def test_notification(self) -> str:
        self.test_messages += 1
        return "om_test"

    async def retry_notification(self, notification_id: int) -> str:
        self.retried.append(notification_id)
        return "om_retry"

    async def apply_config(self, changes: dict[str, Any]) -> None:
        return None


def _client(tmp_path: Path) -> tuple[TestClient, FakeRuntime, ConfigService]:
    from codex_task_monitor.web.app import create_app

    config_service = ConfigService(tmp_path / "config.yaml")
    config_service.create_default()
    config_service.update_from_public(
        {"feishu": {"app_secret": "secret-test"}}
    )
    runtime = FakeRuntime()
    app = create_app(
        runtime=runtime,
        config_service=config_service,
        manage_runtime=False,
        allowed_hosts={"testserver", "127.0.0.1:6664"},
    )
    return TestClient(app), runtime, config_service


def _csrf_headers(client: TestClient) -> dict[str, str]:
    client.get("/api/config")
    token = client.cookies.get("codex_monitor_csrf")
    assert token
    return {
        "X-CSRF-Token": token,
        "Origin": "http://testserver",
    }


def test_lists_tasks_and_reads_detail(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/api/tasks")
    detail = client.get("/api/tasks/thread-1")

    assert response.status_code == 200
    assert response.json()["tasks"][0]["thread_id"] == "thread-1"
    assert detail.json()["project_name"] == "codex-task-monitor"


def test_missing_task_returns_404(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    assert client.get("/api/tasks/missing").status_code == 404


def test_watch_endpoints_require_and_accept_csrf(tmp_path: Path) -> None:
    client, runtime, _ = _client(tmp_path)
    payload = {"mode": "persistent"}

    rejected = client.post("/api/tasks/thread-1/watch", json=payload)
    accepted = client.post(
        "/api/tasks/thread-1/watch",
        json=payload,
        headers=_csrf_headers(client),
    )
    stopped = client.delete(
        "/api/tasks/thread-1/watch",
        headers=_csrf_headers(client),
    )

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert runtime.watch_mode is None
    assert stopped.status_code == 200


def test_config_response_never_contains_secret(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/api/config")

    assert response.json()["feishu"]["app_secret"] == ""
    assert response.json()["feishu"]["app_secret_configured"] is True
    assert "secret-test" not in response.text


def test_config_update_is_validated_and_saved(tmp_path: Path) -> None:
    client, _, config_service = _client(tmp_path)

    response = client.put(
        "/api/config",
        json={"server": {"port": 6670}},
        headers=_csrf_headers(client),
    )

    assert response.status_code == 200
    assert config_service.load().server.port == 6670
    assert response.json()["restart_required"] is True


def test_invalid_config_error_never_echoes_submitted_secret(
    tmp_path: Path,
) -> None:
    client, _, config_service = _client(tmp_path)

    response = client.put(
        "/api/config",
        json={
            "server": {"port": 1},
            "feishu": {"app_secret": "must-not-leak"},
        },
        headers=_csrf_headers(client),
    )

    assert response.status_code == 422
    assert "must-not-leak" not in response.text
    assert config_service.load().feishu.app_secret == "secret-test"


def test_test_notification_and_retry_are_explicit_mutations(tmp_path: Path) -> None:
    client, runtime, _ = _client(tmp_path)
    headers = _csrf_headers(client)

    test_response = client.post(
        "/api/notifications/test",
        json={},
        headers=headers,
    )
    retry_response = client.post(
        "/api/notifications/12/retry",
        json={},
        headers=headers,
    )

    assert test_response.json()["message_id"] == "om_test"
    assert retry_response.json()["message_id"] == "om_retry"
    assert runtime.test_messages == 1
    assert runtime.retried == [12]


def test_rejects_untrusted_host(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/api/tasks", headers={"Host": "evil.example"})

    assert response.status_code == 400


def test_health_endpoint_returns_source_state(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_event_broker_publishes_to_subscribers() -> None:
    from codex_task_monitor.web.events import EventBroker

    broker = EventBroker()
    queue = broker.subscribe()

    await broker.publish("tasks", {"tasks": []})
    event = await queue.get()
    broker.unsubscribe(queue)

    assert event == {"type": "tasks", "payload": {"tasks": []}}


def test_serves_built_frontend_and_history_fallback(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    home = client.get("/")
    frontend_route = client.get("/tasks/thread-1")

    assert home.status_code == 200
    assert "Codex 任务监控器" in home.text
    assert frontend_route.status_code == 200
    assert "Codex 任务监控器" in frontend_route.text


def test_api_route_never_falls_back_to_frontend(tmp_path: Path) -> None:
    client, _, _ = _client(tmp_path)

    response = client.get("/api/not-a-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
