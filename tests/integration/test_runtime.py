from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from codex_task_monitor.config.service import ConfigService
from codex_task_monitor.models import (
    SourceEvent,
    SourceKind,
    TaskStatus,
    WatchMode,
)
from codex_task_monitor.storage.database import Database
from codex_task_monitor.storage.repository import Repository


class FakeAppClient:
    def __init__(self) -> None:
        self.connected = True
        self.requests: list[tuple[str, dict[str, Any]]] = []

    async def start(self) -> None:
        self.connected = True

    async def stop(self) -> None:
        self.connected = False

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.requests.append((method, params))
        if method == "thread/list":
            return {
                "data": [
                    {
                        "id": "thread-1",
                        "name": "实现任务监控器",
                        "preview": "",
                        "cwd": "/work/codex-task-monitor",
                        "gitInfo": {"branch": "feature/monitor"},
                        "source": "appServer",
                        "status": {"type": "active", "activeFlags": []},
                        "createdAt": 1785310000,
                        "updatedAt": 1785310100,
                        "turns": [],
                    },
                    {
                        "id": "thread-old",
                        "name": "很久以前的任务",
                        "preview": "",
                        "cwd": "/work/old-project",
                        "source": "appServer",
                        "status": {"type": "notLoaded"},
                        "createdAt": 1767225600,
                        "updatedAt": 1767225600,
                        "turns": [],
                    }
                ],
                "nextCursor": None,
            }
        if method == "thread/read":
            return {
                "thread": {
                    "id": "thread-1",
                    "name": "实现任务监控器",
                    "preview": "",
                    "cwd": "/work/codex-task-monitor",
                    "gitInfo": {"branch": "feature/monitor"},
                    "source": "appServer",
                    "status": {"type": "active", "activeFlags": []},
                    "createdAt": 1785310000,
                    "updatedAt": 1785310100,
                    "turns": [
                        {
                            "id": "turn-1",
                            "status": "inProgress",
                            "startedAt": 1785310000,
                            "completedAt": None,
                            "items": [],
                        }
                    ],
                }
            }
        return {}

    async def next_notification(
        self,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        raise TimeoutError


class FakeObserver:
    def __init__(self, batches: list[list[SourceEvent]] | None = None) -> None:
        self.batches = list(batches or [])

    async def scan_once(self) -> list[SourceEvent]:
        return self.batches.pop(0) if self.batches else []


class FakeNotifier:
    def __init__(self) -> None:
        self.messages: list[str] = []
        self.closed = False

    async def send_text(self, text: str) -> str:
        self.messages.append(text)
        return f"om_{len(self.messages)}"

    async def close(self) -> None:
        self.closed = True


class FakePublisher:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


def _runtime(
    tmp_path: Path,
    *,
    observer: FakeObserver | None = None,
):
    from codex_task_monitor.runtime import RuntimeService

    config_service = ConfigService(tmp_path / "config.yaml")
    config_service.create_default()
    config_service.update_from_public(
        {
            "feishu": {
                "app_id": "cli_test",
                "app_secret": "secret-test",
                "receive_id": "ou_test",
            }
        }
    )
    database = Database(tmp_path / "data" / "monitor.db")
    database.initialize()
    notifier = FakeNotifier()
    publisher = FakePublisher()
    runtime = RuntimeService(
        config_service=config_service,
        repository=Repository(database),
        app_client=FakeAppClient(),
        observer=observer or FakeObserver(),
        notifier=notifier,
        publisher=publisher,
    )
    return runtime, notifier, publisher


@pytest.mark.asyncio
async def test_refresh_lists_active_thread_with_turn_details(tmp_path: Path) -> None:
    runtime, _, _ = _runtime(tmp_path)

    await runtime.refresh_once()

    tasks = runtime.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].thread_id == "thread-1"
    assert tasks[0].turn_id == "turn-1"
    assert tasks[0].status is TaskStatus.RUNNING
    list_request = runtime.app_client.requests[0]
    assert list_request[1]["useStateDbOnly"] is True
    assert "subAgent" not in list_request[1]["sourceKinds"]


@pytest.mark.asyncio
async def test_monitored_completion_sends_one_message(tmp_path: Path) -> None:
    completed = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-1",
        turn_id="turn-1",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        latest_summary="任务已经完成。",
        authoritative=True,
    )
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[completed], [completed]]),
    )
    await runtime.refresh_once()
    await runtime.start_watch("thread-1", WatchMode.CURRENT_TURN)

    await runtime.observe_once()
    await runtime.observe_once()

    assert len(notifier.messages) == 1
    assert "Codex 任务已完成" in notifier.messages[0]
    assert "项目：codex-task-monitor" in notifier.messages[0]


@pytest.mark.asyncio
async def test_unmonitored_completion_does_not_send_message(tmp_path: Path) -> None:
    completed = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-1",
        turn_id="turn-1",
        status=TaskStatus.COMPLETED,
        authoritative=True,
    )
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[completed]]),
    )
    await runtime.refresh_once()

    await runtime.observe_once()

    assert notifier.messages == []


@pytest.mark.asyncio
async def test_baseline_completion_never_sends_message(tmp_path: Path) -> None:
    completed = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-1",
        turn_id="turn-1",
        status=TaskStatus.COMPLETED,
        authoritative=True,
        baseline=True,
    )
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[completed]]),
    )
    await runtime.refresh_once()
    await runtime.start_watch("thread-1", WatchMode.PERSISTENT)

    await runtime.observe_once()

    assert notifier.messages == []


@pytest.mark.asyncio
async def test_task_changes_are_published(tmp_path: Path) -> None:
    runtime, _, publisher = _runtime(tmp_path)

    await runtime.refresh_once()

    assert any(event_type == "tasks" for event_type, _ in publisher.events)


@pytest.mark.asyncio
async def test_formatted_notification_is_saved_for_retry(tmp_path: Path) -> None:
    completed = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-1",
        turn_id="turn-1",
        status=TaskStatus.COMPLETED,
        completed_at=datetime.now(UTC),
        latest_summary="任务已经完成。",
        authoritative=True,
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[completed]]),
    )
    await runtime.refresh_once()
    await runtime.start_watch("thread-1", WatchMode.CURRENT_TURN)

    await runtime.observe_once()

    notification = runtime.repository.get_notification_by_key(
        "thread-1:turn-1:completed"
    )
    assert notification is not None
    assert "Codex 任务已完成" in str(notification["message"])


@pytest.mark.asyncio
async def test_test_notification_uses_current_notifier(tmp_path: Path) -> None:
    runtime, notifier, _ = _runtime(tmp_path)

    message_id = await runtime.test_notification()

    assert message_id == "om_1"
    assert "测试消息" in notifier.messages[0]


@pytest.mark.asyncio
async def test_failed_notification_can_be_retried_by_id(tmp_path: Path) -> None:
    runtime, notifier, _ = _runtime(tmp_path)
    runtime.repository.reserve_notification(
        "thread-1:turn-1:completed",
        message="需要重试的安全消息",
    )
    runtime.repository.mark_notification_failed(
        "thread-1:turn-1:completed",
        "临时网络错误",
    )
    notification = runtime.repository.get_notification_by_key(
        "thread-1:turn-1:completed"
    )
    assert notification is not None

    message_id = await runtime.retry_notification(int(notification["id"]))

    assert message_id == "om_1"
    assert notifier.messages == ["需要重试的安全消息"]
    assert runtime.repository.get_notification(
        int(notification["id"])
    )["state"] == "sent"


@pytest.mark.asyncio
async def test_feishu_config_change_replaces_notifier(tmp_path: Path) -> None:
    runtime, old_notifier, _ = _runtime(tmp_path)
    runtime.config_service.update_from_public(
        {"feishu": {"receive_id": "ou_changed"}}
    )

    await runtime.apply_config({"feishu": {"receive_id": "ou_changed"}})

    assert old_notifier.closed is True
    assert runtime.notifier.config.receive_id == "ou_changed"
    await runtime.notifier.close()


@pytest.mark.asyncio
async def test_stale_session_running_event_is_not_shown(
    tmp_path: Path,
) -> None:
    stale = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        title="已经停滞的历史任务",
        status=TaskStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(hours=48),
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[stale]]),
    )

    await runtime.observe_once()

    assert runtime.get_task("thread-stale") is None
