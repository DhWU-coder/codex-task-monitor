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


class NotLoadedAppClient(FakeAppClient):
    """模拟列表未加载、详情包含滞后 Turn 状态的 App Server。"""

    async def request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self.requests.append((method, params))
        updated_at = int(datetime.now(UTC).timestamp())
        if method == "thread/list":
            return {
                "data": [
                    {
                        "id": "thread-stale",
                        "name": "你有pdf工具么",
                        "preview": "",
                        "cwd": "/work/codex-gateway",
                        "source": "appServer",
                        "status": {"type": "notLoaded"},
                        "createdAt": updated_at - 60,
                        "updatedAt": updated_at,
                        "turns": [],
                    }
                ],
                "nextCursor": None,
            }
        if method == "thread/read":
            return {
                "thread": {
                    "id": "thread-stale",
                    "name": "你有pdf工具么",
                    "preview": "",
                    "cwd": "/work/codex-gateway",
                    "source": "appServer",
                    "status": {"type": "notLoaded"},
                    "createdAt": updated_at - 60,
                    "updatedAt": updated_at,
                    "turns": [
                        {
                            "id": "turn-stale",
                            "status": "interrupted",
                            "startedAt": updated_at - 60,
                            "completedAt": None,
                            "items": [],
                        }
                    ],
                }
            }
        return {}


def _app_thread(
    thread_id: str,
    name: str,
    *,
    updated_at: int,
    status_type: str = "idle",
) -> dict[str, Any]:
    """构造运行时测试需要的最小 App Server 任务。"""

    return {
        "id": thread_id,
        "name": name,
        "preview": "",
        "cwd": "/work/lineage-project",
        "source": "appServer",
        "status": {"type": status_type},
        "createdAt": updated_at,
        "updatedAt": updated_at,
        "turns": [],
    }


class SequencedListAppClient(FakeAppClient):
    """按调用顺序返回预设任务列表响应。"""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        super().__init__()
        self.responses = list(responses)

    async def request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self.requests.append((method, params))
        if method == "thread/list":
            return self.responses.pop(0)
        return {}


class StaticThreadListAppClient(FakeAppClient):
    """始终返回同一组 App Server 任务。"""

    def __init__(self, threads: list[dict[str, Any]]) -> None:
        super().__init__()
        self.threads = threads

    async def request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        self.requests.append((method, params))
        if method == "thread/list":
            return {"data": self.threads, "nextCursor": None}
        return {}


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
    app_client: FakeAppClient | None = None,
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
        app_client=app_client or FakeAppClient(),
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


@pytest.mark.asyncio
async def test_not_loaded_thread_preserves_session_running_state(
    tmp_path: Path,
) -> None:
    running = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        title="你有pdf工具么",
        status=TaskStatus.RUNNING,
        updated_at=datetime.now(UTC),
    )
    app_client = NotLoadedAppClient()
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running]]),
        app_client=app_client,
    )
    await runtime.observe_once()
    assert runtime.get_task("thread-stale").status is TaskStatus.RUNNING

    await runtime.refresh_once()

    methods = [method for method, _ in app_client.requests]
    assert methods == ["thread/list"]
    assert runtime.get_task("thread-stale").status is TaskStatus.RUNNING
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_orphaned_not_loaded_running_is_interrupted_without_notification(
    tmp_path: Path,
) -> None:
    running = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        title="你有pdf工具么",
        status=TaskStatus.RUNNING,
        updated_at=datetime.now(UTC) - timedelta(hours=2),
    )
    app_client = NotLoadedAppClient()
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running]]),
        app_client=app_client,
    )
    await runtime.observe_once()
    await runtime.start_watch("thread-stale", WatchMode.PERSISTENT)

    await runtime.refresh_once()

    methods = [method for method, _ in app_client.requests]
    assert methods == ["thread/list"]
    assert runtime.get_task("thread-stale").status is TaskStatus.INTERRUPTED
    watch = runtime.repository.get_watch("thread-stale")
    assert watch is not None
    assert watch.active is False
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_orphaned_task_resumes_when_session_appends_event(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    running = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        status=TaskStatus.RUNNING,
        updated_at=now - timedelta(hours=2),
    )
    resumed = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        status=None,
        latest_summary="任务继续输出。",
        updated_at=now,
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running], [resumed]]),
        app_client=NotLoadedAppClient(),
    )
    await runtime.observe_once()
    await runtime.refresh_once()
    assert runtime.get_task("thread-stale").status is TaskStatus.INTERRUPTED

    await runtime.observe_once()

    task = runtime.get_task("thread-stale")
    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert task.latest_summary == "任务继续输出。"


@pytest.mark.asyncio
async def test_orphaned_task_accepts_later_real_completion(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    running = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        status=TaskStatus.RUNNING,
        updated_at=now - timedelta(hours=2),
    )
    completed = SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-stale",
        turn_id="turn-stale",
        status=TaskStatus.COMPLETED,
        completed_at=now,
        updated_at=now,
        authoritative=True,
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running], [completed]]),
        app_client=NotLoadedAppClient(),
    )
    await runtime.observe_once()
    await runtime.refresh_once()

    await runtime.observe_once()

    task = runtime.get_task("thread-stale")
    assert task is not None
    assert task.status is TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_not_loaded_thread_without_active_snapshot_skips_details(
    tmp_path: Path,
) -> None:
    app_client = NotLoadedAppClient()
    runtime, _, _ = _runtime(tmp_path, app_client=app_client)

    await runtime.refresh_once()

    methods = [method for method, _ in app_client.requests]
    assert methods == ["thread/list"]
    assert runtime.get_task("thread-stale").status is TaskStatus.UNKNOWN


@pytest.mark.asyncio
async def test_visible_set_includes_rows_outside_recent_window(
    tmp_path: Path,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    app_client = SequencedListAppClient(
        [
            {
                "data": [
                    _app_thread(
                        "thread-a",
                        "父任务",
                        updated_at=now - 172800,
                    ),
                    _app_thread("thread-b", "子任务", updated_at=now),
                ],
                "nextCursor": None,
            }
        ]
    )
    observer = FakeObserver(
        [
            [
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-a",
                    title="父任务本地消息",
                    status=TaskStatus.RUNNING,
                    updated_at=datetime.now(UTC),
                ),
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-b",
                    parent_thread_id="thread-a",
                    title="子任务本地消息",
                    status=TaskStatus.RUNNING,
                    updated_at=datetime.now(UTC),
                ),
            ]
        ]
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=observer,
        app_client=app_client,
    )

    await runtime.refresh_once()
    await runtime.observe_once()

    assert {task.thread_id for task in runtime.list_tasks()} == {
        "thread-a",
        "thread-b",
    }


@pytest.mark.asyncio
async def test_incomplete_thread_list_preserves_previous_visible_set(
    tmp_path: Path,
) -> None:
    now = int(datetime.now(UTC).timestamp())
    thread_a = _app_thread("thread-a", "父任务", updated_at=now)
    thread_b = _app_thread("thread-b", "子任务", updated_at=now)
    app_client = SequencedListAppClient(
        [
            {"data": [thread_a, thread_b], "nextCursor": None},
            {"data": [thread_b], "nextCursor": "page-2"},
            {"unexpected": []},
        ]
    )
    observer = FakeObserver(
        [
            [
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-b",
                    parent_thread_id="thread-a",
                    status=TaskStatus.RUNNING,
                    updated_at=datetime.now(UTC),
                )
            ]
        ]
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=observer,
        app_client=app_client,
    )

    await runtime.refresh_once()
    await runtime.observe_once()
    await runtime.refresh_once()

    assert {task.thread_id for task in runtime.list_tasks()} == {
        "thread-a",
        "thread-b",
    }


@pytest.mark.asyncio
async def test_internal_continuation_keeps_only_named_visible_leaf(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    app_client = StaticThreadListAppClient(
        [
            _app_thread(
                "thread-c",
                "侧栏任务名称",
                updated_at=int(now.timestamp()),
            )
        ]
    )
    events = [
        SourceEvent(
            source=SourceKind.SESSION,
            thread_id="thread-a",
            title="祖先消息",
            status=TaskStatus.COMPLETED,
            authoritative=True,
            updated_at=now,
        ),
        SourceEvent(
            source=SourceKind.SESSION,
            thread_id="thread-b",
            parent_thread_id="thread-a",
            title="中间消息",
            status=TaskStatus.RUNNING,
            updated_at=now,
        ),
        SourceEvent(
            source=SourceKind.SESSION,
            thread_id="thread-c",
            parent_thread_id="thread-b",
            title="第一条用户消息",
            status=TaskStatus.RUNNING,
            updated_at=now,
        ),
    ]
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([events]),
        app_client=app_client,
    )
    runtime.repository.save_watch(
        thread_id="thread-a",
        mode=WatchMode.PERSISTENT,
        baseline_status=TaskStatus.RUNNING,
    )

    await runtime.refresh_once()
    await runtime.observe_once()

    tasks = runtime.list_tasks()
    assert [task.thread_id for task in tasks] == ["thread-c"]
    assert tasks[0].title == "侧栏任务名称"
    assert runtime.get_task("thread-a") is None
    assert runtime.get_task("thread-b") is None
    watch = runtime.repository.get_watch("thread-a")
    assert watch is not None
    assert watch.active is False
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_user_fork_keeps_both_app_server_tasks(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    app_client = StaticThreadListAppClient(
        [
            _app_thread(
                "thread-a",
                "任务 A",
                updated_at=int(now.timestamp()),
            ),
            _app_thread(
                "thread-b",
                "任务 B",
                updated_at=int(now.timestamp()),
            ),
        ]
    )
    observer = FakeObserver(
        [
            [
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-b",
                    parent_thread_id="thread-a",
                    title="B 的第一条消息",
                    status=TaskStatus.RUNNING,
                    updated_at=now,
                )
            ]
        ]
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=observer,
        app_client=app_client,
    )

    await runtime.refresh_once()
    await runtime.observe_once()

    assert {
        task.thread_id: task.title for task in runtime.list_tasks()
    } == {
        "thread-a": "任务 A",
        "thread-b": "任务 B",
    }


@pytest.mark.asyncio
async def test_three_running_named_tasks_use_app_server_titles(
    tmp_path: Path,
) -> None:
    now = datetime.now(UTC)
    app_client = StaticThreadListAppClient(
        [
            _app_thread(
                "thread-monitor",
                "codex任务监控器",
                updated_at=int(now.timestamp()),
                status_type="notLoaded",
            ),
            _app_thread(
                "thread-feishu",
                "飞书channel-Web Chat",
                updated_at=int(now.timestamp()),
                status_type="notLoaded",
            ),
            _app_thread(
                "thread-frontend",
                "生成前端",
                updated_at=int(
                    (now - timedelta(hours=48)).timestamp()
                ),
                status_type="notLoaded",
            ),
        ]
    )
    observer = FakeObserver(
        [
            [
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-monitor",
                    title="监控器的第一条用户消息",
                    status=TaskStatus.RUNNING,
                    updated_at=now,
                ),
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-feishu",
                    title="飞书任务的第一条用户消息",
                    status=TaskStatus.RUNNING,
                    updated_at=now,
                ),
                SourceEvent(
                    source=SourceKind.SESSION,
                    thread_id="thread-frontend",
                    title="前端任务的第一条用户消息",
                    status=TaskStatus.RUNNING,
                    updated_at=now,
                ),
            ]
        ]
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=observer,
        app_client=app_client,
    )

    await runtime.refresh_once()
    await runtime.observe_once()

    tasks = {task.thread_id: task for task in runtime.list_tasks()}
    assert set(tasks) == {
        "thread-monitor",
        "thread-feishu",
        "thread-frontend",
    }
    assert {
        thread_id: task.status for thread_id, task in tasks.items()
    } == {
        "thread-monitor": TaskStatus.RUNNING,
        "thread-feishu": TaskStatus.RUNNING,
        "thread-frontend": TaskStatus.RUNNING,
    }
    assert {
        thread_id: task.title for thread_id, task in tasks.items()
    } == {
        "thread-monitor": "codex任务监控器",
        "thread-feishu": "飞书channel-Web Chat",
        "thread-frontend": "生成前端",
    }


def _manual_completion_running_event(
    *,
    turn_id: str | None = "turn-manual",
    started_at: datetime | None = None,
    status: TaskStatus = TaskStatus.RUNNING,
    updated_at: datetime | None = None,
    authoritative: bool = False,
) -> SourceEvent:
    """构造手动结束运行时测试使用的事件。"""

    effective_started_at = started_at or datetime.now(UTC) - timedelta(minutes=5)
    return SourceEvent(
        source=SourceKind.SESSION,
        thread_id="thread-manual",
        turn_id=turn_id,
        title="需要手动结束的任务",
        status=status,
        started_at=effective_started_at,
        completed_at=updated_at if status is TaskStatus.COMPLETED else None,
        updated_at=updated_at or effective_started_at,
        authoritative=authoritative,
    )


@pytest.mark.asyncio
async def test_manual_completion_persists_without_notification_and_stops_current_watch(
    tmp_path: Path,
) -> None:
    running = _manual_completion_running_event()
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running]]),
    )
    await runtime.observe_once()
    await runtime.start_watch("thread-manual", WatchMode.CURRENT_TURN)

    task = await runtime.mark_manual_completion("thread-manual")

    assert task.status is TaskStatus.MANUALLY_COMPLETED
    assert task.completed_at is not None
    assert runtime.repository.get_manual_completion("thread-manual") is not None
    assert runtime.repository.list_snapshots()[0].status is TaskStatus.MANUALLY_COMPLETED
    watch = runtime.repository.get_watch("thread-manual")
    assert watch is not None
    assert watch.active is False
    assert notifier.messages == []
    assert runtime.repository.get_notification_by_key(
        "thread-manual:turn-manual:manually_completed"
    ) is None


@pytest.mark.asyncio
async def test_manual_completion_keeps_persistent_watch_active(
    tmp_path: Path,
) -> None:
    running = _manual_completion_running_event()
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running]]),
    )
    await runtime.observe_once()
    await runtime.start_watch("thread-manual", WatchMode.PERSISTENT)

    task = await runtime.mark_manual_completion("thread-manual")

    watch = runtime.repository.get_watch("thread-manual")
    assert task.status is TaskStatus.MANUALLY_COMPLETED
    assert task.monitored is True
    assert watch is not None
    assert watch.active is True
    assert watch.mode is WatchMode.PERSISTENT


@pytest.mark.asyncio
async def test_manual_completion_suppresses_same_turn_updates_and_notifications(
    tmp_path: Path,
) -> None:
    started_at = datetime.now(UTC) - timedelta(minutes=5)
    running = _manual_completion_running_event(started_at=started_at)
    later = datetime.now(UTC) + timedelta(minutes=1)
    same_turn_running = _manual_completion_running_event(
        started_at=started_at,
        updated_at=later,
    )
    same_turn_waiting = _manual_completion_running_event(
        started_at=started_at,
        status=TaskStatus.WAITING_INPUT,
        updated_at=later + timedelta(minutes=1),
    )
    same_turn_completed = _manual_completion_running_event(
        started_at=started_at,
        status=TaskStatus.COMPLETED,
        updated_at=later + timedelta(minutes=2),
        authoritative=True,
    )
    runtime, notifier, _ = _runtime(
        tmp_path,
        observer=FakeObserver(
            [
                [running],
                [same_turn_running],
                [same_turn_waiting],
                [same_turn_completed],
            ]
        ),
    )
    await runtime.observe_once()
    await runtime.start_watch("thread-manual", WatchMode.PERSISTENT)
    marked = await runtime.mark_manual_completion("thread-manual")

    await runtime.observe_once()
    assert runtime.get_task("thread-manual").status is TaskStatus.MANUALLY_COMPLETED
    await runtime.observe_once()
    assert runtime.get_task("thread-manual").status is TaskStatus.MANUALLY_COMPLETED
    await runtime.observe_once()
    task = runtime.get_task("thread-manual")

    assert task is not None
    assert task.status is TaskStatus.MANUALLY_COMPLETED
    assert task.completed_at == marked.completed_at
    assert notifier.messages == []


@pytest.mark.asyncio
async def test_manual_completion_is_cleared_by_new_turn(
    tmp_path: Path,
) -> None:
    first_started_at = datetime.now(UTC) - timedelta(minutes=5)
    first = _manual_completion_running_event(started_at=first_started_at)
    second_started_at = datetime.now(UTC) + timedelta(minutes=1)
    second = _manual_completion_running_event(
        turn_id="turn-next",
        started_at=second_started_at,
        updated_at=second_started_at,
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[first], [second]]),
    )
    await runtime.observe_once()
    await runtime.start_watch("thread-manual", WatchMode.PERSISTENT)
    await runtime.mark_manual_completion("thread-manual")

    await runtime.observe_once()
    task = runtime.get_task("thread-manual")

    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert task.turn_id == "turn-next"
    assert task.started_at == second_started_at
    assert task.completed_at is None
    assert runtime.repository.get_manual_completion("thread-manual") is None
    watch = runtime.repository.get_watch("thread-manual")
    assert watch is not None
    assert watch.active is True


@pytest.mark.asyncio
async def test_manual_completion_without_turn_uses_later_start_time(
    tmp_path: Path,
) -> None:
    first_started_at = datetime.now(UTC) - timedelta(minutes=5)
    first = _manual_completion_running_event(
        turn_id=None,
        started_at=first_started_at,
    )
    runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[first]]),
    )
    await runtime.observe_once()
    marked = await runtime.mark_manual_completion("thread-manual")
    assert marked.completed_at is not None

    same_generation = _manual_completion_running_event(
        turn_id=None,
        started_at=first_started_at,
        updated_at=marked.completed_at + timedelta(seconds=1),
    )
    runtime.observer.batches.append([same_generation])
    await runtime.observe_once()
    assert runtime.get_task("thread-manual").status is TaskStatus.MANUALLY_COMPLETED

    next_started_at = marked.completed_at + timedelta(seconds=2)
    next_generation = _manual_completion_running_event(
        turn_id=None,
        started_at=next_started_at,
        updated_at=next_started_at,
    )
    runtime.observer.batches.append([next_generation])
    await runtime.observe_once()
    task = runtime.get_task("thread-manual")

    assert task is not None
    assert task.status is TaskStatus.RUNNING
    assert task.started_at == next_started_at
    assert runtime.repository.get_manual_completion("thread-manual") is None


@pytest.mark.asyncio
async def test_manual_completion_and_persistent_watch_survive_runtime_restart(
    tmp_path: Path,
) -> None:
    running = _manual_completion_running_event(
        turn_id="turn-1",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    first_runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running]]),
    )
    await first_runtime.observe_once()
    await first_runtime.start_watch("thread-manual", WatchMode.PERSISTENT)
    await first_runtime.mark_manual_completion("thread-manual")

    second_runtime, _, _ = _runtime(
        tmp_path,
        observer=FakeObserver([[running]]),
        app_client=StaticThreadListAppClient([]),
    )
    await second_runtime.start()
    try:
        task = second_runtime.get_task("thread-manual")
        watch = second_runtime.repository.get_watch("thread-manual")

        assert task is not None
        assert task.status is TaskStatus.MANUALLY_COMPLETED
        assert watch is not None
        assert watch.active is True
        assert watch.mode is WatchMode.PERSISTENT
    finally:
        await second_runtime.stop()
