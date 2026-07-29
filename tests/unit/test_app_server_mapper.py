from codex_task_monitor.models import TaskStatus


def _thread(
    *,
    status: dict[str, object],
    turns: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "id": "thread-1",
        "name": "实现任务监控器",
        "preview": "实现任务监控器预览",
        "cwd": "/work/codex-task-monitor",
        "gitInfo": {"branch": "feature/monitor"},
        "source": "appServer",
        "status": status,
        "createdAt": 1785310000,
        "updatedAt": 1785310100,
        "turns": turns or [],
    }


def test_active_thread_maps_to_running() -> None:
    from codex_task_monitor.codex_adapter.mapper import map_thread

    snapshot = map_thread(
        _thread(status={"type": "active", "activeFlags": []})
    )

    assert snapshot.status is TaskStatus.RUNNING
    assert snapshot.title == "实现任务监控器"
    assert snapshot.project_name == "codex-task-monitor"
    assert snapshot.branch == "feature/monitor"


def test_active_flags_map_to_waiting_states() -> None:
    from codex_task_monitor.codex_adapter.mapper import map_thread

    approval = map_thread(
        _thread(
            status={
                "type": "active",
                "activeFlags": ["waitingOnApproval"],
            }
        )
    )
    user_input = map_thread(
        _thread(
            status={
                "type": "active",
                "activeFlags": ["waitingOnUserInput"],
            }
        )
    )

    assert approval.status is TaskStatus.WAITING_APPROVAL
    assert user_input.status is TaskStatus.WAITING_INPUT


def test_completed_turn_supplies_summary_and_timestamps() -> None:
    from codex_task_monitor.codex_adapter.mapper import map_thread

    snapshot = map_thread(
        _thread(
            status={"type": "idle"},
            turns=[
                {
                    "id": "turn-1",
                    "status": "completed",
                    "startedAt": 1785310000,
                    "completedAt": 1785310100,
                    "items": [
                        {
                            "id": "message-1",
                            "type": "agentMessage",
                            "text": "已经完成实现。",
                        }
                    ],
                }
            ],
        )
    )

    assert snapshot.turn_id == "turn-1"
    assert snapshot.status is TaskStatus.COMPLETED
    assert snapshot.latest_summary == "已经完成实现。"
    assert snapshot.started_at is not None
    assert snapshot.completed_at is not None


def test_turn_completed_notification_maps_failed_error() -> None:
    from codex_task_monitor.codex_adapter.mapper import map_notification

    event = map_notification(
        "turn/completed",
        {
            "threadId": "thread-1",
            "turn": {
                "id": "turn-1",
                "status": "failed",
                "items": [],
                "error": {"message": "构建失败"},
            },
        },
    )

    assert event is not None
    assert event.status is TaskStatus.FAILED
    assert event.error_summary == "构建失败"
    assert event.authoritative is True


def test_user_input_request_maps_waiting_event() -> None:
    from codex_task_monitor.codex_adapter.mapper import map_notification

    event = map_notification(
        "item/tool/requestUserInput",
        {
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "item-1",
            "questions": [{"header": "确认", "question": "是否继续？"}],
        },
    )

    assert event is not None
    assert event.status is TaskStatus.WAITING_INPUT
    assert event.request_id == "item-1"
    assert event.waiting_reason == "是否继续？"


def test_unknown_status_maps_to_unknown() -> None:
    from codex_task_monitor.codex_adapter.mapper import map_thread

    snapshot = map_thread(_thread(status={"type": "futureStatus"}))

    assert snapshot.status is TaskStatus.UNKNOWN
