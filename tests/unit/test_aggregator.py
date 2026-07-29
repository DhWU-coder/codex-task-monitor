from datetime import UTC, datetime

from codex_task_monitor.models import (
    SourceEvent,
    SourceKind,
    TaskStatus,
)


def _event(
    *,
    source: SourceKind,
    status: TaskStatus | None,
    turn_id: str = "turn-1",
    authoritative: bool = False,
    **changes: object,
) -> SourceEvent:
    values: dict[str, object] = {
        "source": source,
        "thread_id": "thread-1",
        "turn_id": turn_id,
        "title": "实现任务监控器",
        "status": status,
        "cwd": "/work/codex-task-monitor",
        "branch": "feature/monitor",
        "updated_at": datetime.now(UTC),
        "authoritative": authoritative,
    }
    values.update(changes)
    return SourceEvent.model_validate(values)


def test_session_summary_merges_into_app_server_task() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(source=SourceKind.APP_SERVER, status=TaskStatus.RUNNING)
    )

    snapshot = aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=None,
            latest_summary="正在执行测试。",
        )
    )

    assert snapshot.status is TaskStatus.RUNNING
    assert snapshot.latest_summary == "正在执行测试。"
    assert snapshot.branch == "feature/monitor"


def test_disconnect_never_becomes_completed() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(source=SourceKind.APP_SERVER, status=TaskStatus.RUNNING)
    )

    snapshot = aggregator.apply(
        _event(source=SourceKind.APP_SERVER, status=TaskStatus.UNKNOWN)
    )

    assert snapshot.status in {TaskStatus.RUNNING, TaskStatus.UNKNOWN}
    assert snapshot.status is not TaskStatus.COMPLETED


def test_authoritative_session_terminal_event_wins() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(source=SourceKind.APP_SERVER, status=TaskStatus.RUNNING)
    )

    snapshot = aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.COMPLETED,
            authoritative=True,
            completed_at=datetime.now(UTC),
        )
    )

    assert snapshot.status is TaskStatus.COMPLETED
    assert snapshot.completed_at is not None


def test_new_turn_can_replace_previous_terminal_state() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.COMPLETED,
            authoritative=True,
        )
    )

    snapshot = aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            turn_id="turn-2",
        )
    )

    assert snapshot.turn_id == "turn-2"
    assert snapshot.status is TaskStatus.RUNNING


def test_waiting_state_has_priority_over_running_for_same_turn() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(source=SourceKind.SESSION, status=TaskStatus.RUNNING)
    )

    snapshot = aggregator.apply(
        _event(
            source=SourceKind.APP_SERVER,
            status=TaskStatus.WAITING_APPROVAL,
            authoritative=True,
            waiting_reason="允许执行构建命令。",
        )
    )

    assert snapshot.status is TaskStatus.WAITING_APPROVAL
    assert snapshot.waiting_reason == "允许执行构建命令。"
