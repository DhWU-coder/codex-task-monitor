"""Codex App Server 消息到领域模型的映射。"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from codex_task_monitor.models import (
    SourceEvent,
    SourceKind,
    TaskSnapshot,
    TaskStatus,
)

TURN_STATUS_MAP = {
    "inProgress": TaskStatus.RUNNING,
    "completed": TaskStatus.COMPLETED,
    "failed": TaskStatus.FAILED,
    "interrupted": TaskStatus.INTERRUPTED,
}


def map_thread(thread: dict[str, Any]) -> TaskSnapshot:
    """把 thread/list 或 thread/read 返回值映射为任务快照。"""

    turns = thread.get("turns")
    latest_turn = turns[-1] if isinstance(turns, list) and turns else None
    status = _thread_status(thread.get("status"), latest_turn)
    cwd = thread.get("cwd") if isinstance(thread.get("cwd"), str) else None
    git_info = thread.get("gitInfo")
    branch = git_info.get("branch") if isinstance(git_info, dict) else None
    if not isinstance(branch, str):
        branch = None
    thread_id = str(thread.get("id", ""))
    title = thread.get("name") or thread.get("preview") or thread_id[:8]
    turn_id = None
    started_at = None
    completed_at = None
    summary = ""
    error_summary = ""
    if isinstance(latest_turn, dict):
        turn_id = _optional_text(latest_turn.get("id"))
        started_at = _timestamp(latest_turn.get("startedAt"))
        completed_at = _timestamp(latest_turn.get("completedAt"))
        summary = _latest_agent_message(latest_turn.get("items"))
        error_summary = _turn_error(latest_turn.get("error"))
    updated_at = _timestamp(thread.get("updatedAt")) or datetime.now(UTC)
    return TaskSnapshot(
        thread_id=thread_id,
        turn_id=turn_id,
        title=str(title),
        status=status,
        source=SourceKind.APP_SERVER,
        project_name=Path(cwd).name if cwd else None,
        cwd=cwd,
        branch=branch,
        source_label=_source_label(thread.get("source")),
        started_at=started_at,
        completed_at=completed_at,
        updated_at=updated_at,
        latest_summary=summary,
        error_summary=error_summary,
    )


def map_notification(
    method: str,
    params: dict[str, Any],
) -> SourceEvent | None:
    """把 App Server 通知映射为标准来源事件。"""

    thread_id = _optional_text(params.get("threadId"))
    if not thread_id:
        return None

    if method == "thread/status/changed":
        return SourceEvent(
            source=SourceKind.APP_SERVER,
            thread_id=thread_id,
            status=_thread_status(params.get("status"), None),
            authoritative=False,
        )

    if method in {"turn/started", "turn/completed"}:
        turn = params.get("turn")
        if not isinstance(turn, dict):
            return None
        status = TURN_STATUS_MAP.get(str(turn.get("status")), TaskStatus.UNKNOWN)
        return SourceEvent(
            source=SourceKind.APP_SERVER,
            thread_id=thread_id,
            turn_id=_optional_text(turn.get("id")),
            status=status,
            started_at=_timestamp(turn.get("startedAt")),
            completed_at=_timestamp(turn.get("completedAt")),
            latest_summary=_latest_agent_message(turn.get("items")),
            error_summary=_turn_error(turn.get("error")),
            authoritative=method == "turn/completed",
        )

    if method == "item/tool/requestUserInput":
        questions = params.get("questions")
        reason = ""
        if isinstance(questions, list):
            reason = "；".join(
                str(question.get("question", "")).strip()
                for question in questions
                if isinstance(question, dict) and question.get("question")
            )
        return SourceEvent(
            source=SourceKind.APP_SERVER,
            thread_id=thread_id,
            turn_id=_optional_text(params.get("turnId")),
            status=TaskStatus.WAITING_INPUT,
            waiting_reason=reason,
            request_id=_optional_text(params.get("itemId")),
            authoritative=True,
        )

    if method.endswith("/requestApproval"):
        approval_reason = _optional_text(
            params.get("reason")
        ) or _optional_text(
            params.get("command")
        )
        request_id = _optional_text(params.get("approvalId")) or _optional_text(
            params.get("itemId")
        )
        return SourceEvent(
            source=SourceKind.APP_SERVER,
            thread_id=thread_id,
            turn_id=_optional_text(params.get("turnId")),
            status=TaskStatus.WAITING_APPROVAL,
            waiting_reason=approval_reason or "",
            request_id=request_id,
            authoritative=True,
        )
    return None


def _thread_status(
    raw_status: Any,
    latest_turn: dict[str, Any] | None,
) -> TaskStatus:
    """合并线程运行态与最新 Turn 状态。"""

    if isinstance(latest_turn, dict):
        mapped_turn = TURN_STATUS_MAP.get(str(latest_turn.get("status")))
        if mapped_turn in {
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.INTERRUPTED,
        }:
            return mapped_turn
    if not isinstance(raw_status, dict):
        return TaskStatus.UNKNOWN
    status_type = raw_status.get("type")
    if status_type == "active":
        flags = raw_status.get("activeFlags")
        active_flags = set(flags) if isinstance(flags, list) else set()
        if "waitingOnUserInput" in active_flags:
            return TaskStatus.WAITING_INPUT
        if "waitingOnApproval" in active_flags:
            return TaskStatus.WAITING_APPROVAL
        return TaskStatus.RUNNING
    if status_type == "systemError":
        return TaskStatus.FAILED
    if status_type == "idle":
        return TaskStatus.COMPLETED
    if status_type == "notLoaded":
        return TaskStatus.UNKNOWN
    return TaskStatus.UNKNOWN


def _latest_agent_message(items: Any) -> str:
    """从 Turn Item 中提取最后一条 Agent 消息。"""

    if not isinstance(items, list):
        return ""
    for item in reversed(items):
        if isinstance(item, dict) and item.get("type") == "agentMessage":
            text = item.get("text")
            return str(text).strip() if text else ""
    return ""


def _turn_error(error: Any) -> str:
    """提取不超过一千字符的 Turn 错误摘要。"""

    if isinstance(error, dict) and error.get("message"):
        return str(error["message"])[:1000]
    return ""


def _timestamp(value: Any) -> datetime | None:
    """把 Unix 秒时间戳转换为 UTC 时间。"""

    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    return None


def _optional_text(value: Any) -> str | None:
    """把非空值转换为文本。"""

    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _source_label(value: Any) -> str:
    """生成供 UI 显示的任务来源名称。"""

    if isinstance(value, str):
        return value
    if isinstance(value, dict) and value:
        return str(value.get("type") or next(iter(value)))
    return "Codex"
