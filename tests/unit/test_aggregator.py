from datetime import UTC, datetime, timedelta

from codex_task_monitor.models import (
    SourceEvent,
    SourceKind,
    TaskSnapshot,
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


def test_app_server_name_is_not_overwritten_by_session_title() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply_snapshot(
        TaskSnapshot(
            thread_id="thread-1",
            title="侧栏任务名称",
            status=TaskStatus.RUNNING,
            source=SourceKind.APP_SERVER,
        )
    )

    snapshot = aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            title="第一条用户消息",
        )
    )

    assert snapshot.title == "侧栏任务名称"


def test_registers_app_server_title_before_session_event() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.set_app_server_title("thread-1", "用户重命名")

    snapshot = aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            title="第一条用户消息",
        )
    )

    assert snapshot.title == "用户重命名"


def test_only_local_ancestors_of_visible_leaf_are_hidden() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-a",
        )
    )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-b",
            parent_thread_id="thread-a",
        )
    )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-c",
            parent_thread_id="thread-b",
        )
    )

    aggregator.set_app_server_thread_ids({"thread-c"})

    assert [task.thread_id for task in aggregator.list_tasks()] == ["thread-c"]
    assert aggregator.get("thread-a") is None
    assert aggregator.get("thread-b") is None


def test_visible_fork_parent_and_child_remain_independent() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-a",
        )
    )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-b",
            parent_thread_id="thread-a",
        )
    )

    aggregator.set_app_server_thread_ids({"thread-a", "thread-b"})

    assert {task.thread_id for task in aggregator.list_tasks()} == {
        "thread-a",
        "thread-b",
    }


def test_unconfirmed_local_lineage_remains_visible() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-a",
        )
    )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-b",
            parent_thread_id="thread-a",
        )
    )

    assert {task.thread_id for task in aggregator.list_tasks()} == {
        "thread-a",
        "thread-b",
    }


def test_confirmed_internal_thread_stays_hidden_until_it_becomes_visible() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-a",
        )
    )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-c",
            parent_thread_id="thread-a",
        )
    )

    aggregator.set_app_server_thread_ids({"thread-c"})
    assert aggregator.get("thread-a") is None

    aggregator.set_app_server_thread_ids(set())
    assert aggregator.get("thread-a") is None

    aggregator.set_app_server_thread_ids({"thread-a"})
    assert aggregator.get("thread-a") is not None


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


def test_orphaned_interruption_is_cleared_by_new_session_event() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    started_at = datetime.now(UTC) - timedelta(hours=2)
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            updated_at=started_at,
        )
    )

    interrupted = aggregator.mark_orphaned_interrupted(
        "thread-1",
        completed_at=datetime.now(UTC),
    )
    resumed = aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=None,
            updated_at=datetime.now(UTC),
            latest_summary="任务继续输出。",
        )
    )

    assert interrupted is not None
    assert interrupted.status is TaskStatus.INTERRUPTED
    assert resumed.status is TaskStatus.RUNNING
    assert resumed.latest_summary == "任务继续输出。"


def test_stable_order_ignores_updated_at_changes() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    base_time = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-older",
            started_at=base_time,
            updated_at=base_time,
        )
    )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-newer",
            started_at=base_time + timedelta(minutes=5),
            updated_at=base_time + timedelta(minutes=5),
        )
    )

    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=None,
            thread_id="thread-older",
            started_at=None,
            updated_at=base_time + timedelta(minutes=10),
            latest_summary="旧任务产生了新的运行摘要。",
        )
    )

    assert [task.thread_id for task in aggregator.list_tasks()] == [
        "thread-newer",
        "thread-older",
    ]


def test_stable_order_uses_thread_id_for_equal_start_times() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    started_at = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    for thread_id in ("thread-b", "thread-a"):
        aggregator.apply(
            _event(
                source=SourceKind.SESSION,
                status=TaskStatus.RUNNING,
                thread_id=thread_id,
                started_at=started_at,
                updated_at=started_at,
            )
        )

    assert [task.thread_id for task in aggregator.list_tasks()] == [
        "thread-a",
        "thread-b",
    ]


def test_stable_order_places_tasks_without_start_time_last() -> None:
    from codex_task_monitor.monitoring.aggregator import TaskAggregator

    aggregator = TaskAggregator()
    base_time = datetime(2026, 7, 30, 10, 0, tzinfo=UTC)
    for thread_id in ("thread-missing-z", "thread-missing-a"):
        aggregator.apply(
            _event(
                source=SourceKind.APP_SERVER,
                status=TaskStatus.RUNNING,
                thread_id=thread_id,
                started_at=None,
                updated_at=base_time + timedelta(minutes=10),
            )
        )
    aggregator.apply(
        _event(
            source=SourceKind.SESSION,
            status=TaskStatus.RUNNING,
            thread_id="thread-started",
            started_at=base_time,
            updated_at=base_time,
        )
    )

    assert [task.thread_id for task in aggregator.list_tasks()] == [
        "thread-started",
        "thread-missing-a",
        "thread-missing-z",
    ]
