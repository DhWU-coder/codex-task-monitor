from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_task_monitor.models import (
    SourceKind,
    TaskSnapshot,
    TaskStatus,
    WatchMode,
)
from codex_task_monitor.storage.database import Database
from codex_task_monitor.storage.repository import Repository


def _task(
    *,
    status: TaskStatus,
    turn_id: str = "turn-1",
    request_id: str | None = None,
) -> TaskSnapshot:
    started_at = datetime.now(UTC) - timedelta(seconds=30)
    completed_at = datetime.now(UTC) if status in {
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.INTERRUPTED,
    } else None
    return TaskSnapshot(
        thread_id="thread-1",
        turn_id=turn_id,
        title="实现任务监控器",
        status=status,
        source=SourceKind.MERGED,
        project_name="codex-task-monitor",
        cwd="/work/codex-task-monitor",
        branch="feature/monitor",
        started_at=started_at,
        completed_at=completed_at,
        latest_summary="已完成测试。",
        waiting_reason="允许执行构建命令。",
        request_id=request_id,
    )


def _service(tmp_path: Path):
    from codex_task_monitor.monitoring.service import MonitoringService

    database = Database(tmp_path / "data" / "monitor.db")
    database.initialize()
    return MonitoringService(Repository(database))


@pytest.mark.asyncio
async def test_current_turn_stops_after_terminal_event(tmp_path: Path) -> None:
    service = _service(tmp_path)
    await service.start_watch(_task(status=TaskStatus.RUNNING), WatchMode.CURRENT_TURN)

    events = await service.apply(_task(status=TaskStatus.COMPLETED))

    assert [event.status for event in events] == [TaskStatus.COMPLETED]
    watch = service.watch_for("thread-1")
    assert watch is not None
    assert watch.active is False


@pytest.mark.asyncio
async def test_persistent_watch_accepts_next_turn(tmp_path: Path) -> None:
    service = _service(tmp_path)
    await service.start_watch(_task(status=TaskStatus.RUNNING), WatchMode.PERSISTENT)
    await service.apply(_task(status=TaskStatus.COMPLETED))

    events = await service.apply(
        _task(
            status=TaskStatus.WAITING_INPUT,
            turn_id="turn-2",
            request_id="request-2",
        )
    )

    assert [event.status for event in events] == [TaskStatus.WAITING_INPUT]
    watch = service.watch_for("thread-1")
    assert watch is not None
    assert watch.active is True


@pytest.mark.asyncio
async def test_starting_watch_does_not_notify_baseline(tmp_path: Path) -> None:
    service = _service(tmp_path)
    running = _task(status=TaskStatus.RUNNING)

    await service.start_watch(running, WatchMode.CURRENT_TURN)

    assert await service.apply(running) == []


@pytest.mark.asyncio
async def test_waiting_request_is_notified_only_once(tmp_path: Path) -> None:
    service = _service(tmp_path)
    await service.start_watch(_task(status=TaskStatus.RUNNING), WatchMode.PERSISTENT)
    waiting = _task(status=TaskStatus.WAITING_APPROVAL, request_id="approval-1")

    first = await service.apply(waiting)
    second = await service.apply(waiting)

    assert len(first) == 1
    assert first[0].status is TaskStatus.WAITING_APPROVAL
    assert second == []


@pytest.mark.asyncio
async def test_unknown_state_never_emits_terminal_notification(tmp_path: Path) -> None:
    service = _service(tmp_path)
    await service.start_watch(_task(status=TaskStatus.RUNNING), WatchMode.CURRENT_TURN)

    events = await service.apply(_task(status=TaskStatus.UNKNOWN))

    assert events == []
    watch = service.watch_for("thread-1")
    assert watch is not None
    assert watch.active is True


@pytest.mark.asyncio
async def test_current_turn_ignores_a_different_turn(tmp_path: Path) -> None:
    service = _service(tmp_path)
    await service.start_watch(_task(status=TaskStatus.RUNNING), WatchMode.CURRENT_TURN)

    events = await service.apply(
        _task(status=TaskStatus.COMPLETED, turn_id="turn-2")
    )

    assert events == []
