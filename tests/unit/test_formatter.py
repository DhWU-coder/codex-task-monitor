from datetime import UTC, datetime

from codex_task_monitor.models import NotificationEvent, TaskStatus


def _event(**changes: object) -> NotificationEvent:
    values: dict[str, object] = {
        "dedupe_key": "thread-1:turn-1:completed",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "status": TaskStatus.COMPLETED,
        "title": "实现任务监控器",
        "project_name": "codex-task-monitor",
        "cwd": "/work/codex-task-monitor",
        "branch": "feature/monitor",
        "duration_seconds": 1122,
        "occurred_at": datetime(2026, 7, 29, 11, 8, 31, tzinfo=UTC),
        "summary": "已完成测试。",
    }
    values.update(changes)
    return NotificationEvent.model_validate(values)


def test_terminal_message_contains_project_and_branch() -> None:
    from codex_task_monitor.notifications.formatter import format_notification

    text = format_notification(_event(), max_length=500)

    assert "【Codex 任务已完成】" in text
    assert "任务：实现任务监控器" in text
    assert "项目：codex-task-monitor" in text
    assert "分支：feature/monitor" in text
    assert "运行时长：18 分 42 秒" in text
    assert "摘要：" in text


def test_waiting_message_contains_reason() -> None:
    from codex_task_monitor.notifications.formatter import format_notification

    text = format_notification(
        _event(
            status=TaskStatus.WAITING_APPROVAL,
            waiting_reason="允许执行前端构建命令。",
            completed_at=None,
        ),
        max_length=500,
    )

    assert "【Codex 任务等待审批】" in text
    assert "待处理：" in text
    assert "允许执行前端构建命令。" in text


def test_formatter_redacts_access_tokens() -> None:
    from codex_task_monitor.notifications.formatter import format_notification

    text = format_notification(
        _event(summary="请求失败：Authorization: Bearer t-secret-token-value"),
        max_length=500,
    )

    assert "t-secret-token-value" not in text
    assert "[已遮盖]" in text


def test_summary_is_truncated() -> None:
    from codex_task_monitor.notifications.formatter import format_notification

    text = format_notification(_event(summary="测" * 100), max_length=20)

    assert "测" * 20 not in text
    assert "…" in text


def test_branch_line_is_omitted_when_unavailable() -> None:
    from codex_task_monitor.notifications.formatter import format_notification

    text = format_notification(_event(branch=None), max_length=500)

    assert "分支：" not in text
