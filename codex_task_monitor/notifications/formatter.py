"""飞书任务状态文本格式化。"""

import re

from codex_task_monitor.models import NotificationEvent, TaskStatus

STATUS_TITLES = {
    TaskStatus.COMPLETED: "Codex 任务已完成",
    TaskStatus.FAILED: "Codex 任务执行失败",
    TaskStatus.INTERRUPTED: "Codex 任务已中断",
    TaskStatus.WAITING_INPUT: "Codex 任务等待输入",
    TaskStatus.WAITING_APPROVAL: "Codex 任务等待审批",
}
STATUS_LABELS = {
    TaskStatus.COMPLETED: "已完成",
    TaskStatus.FAILED: "失败",
    TaskStatus.INTERRUPTED: "已中断",
    TaskStatus.WAITING_INPUT: "等待用户输入",
    TaskStatus.WAITING_APPROVAL: "等待审批",
}
SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)\S+"),
    re.compile(r"\b[atu]-[A-Za-z0-9._-]{6,}\b"),
    re.compile(r"(?i)(app_secret\s*[=:]\s*)\S+"),
)


def redact_sensitive(text: str) -> str:
    """遮盖摘要中的常见凭据形式。"""

    result = text
    result = SENSITIVE_PATTERNS[0].sub(r"\1[已遮盖]", result)
    result = SENSITIVE_PATTERNS[1].sub("[已遮盖]", result)
    result = SENSITIVE_PATTERNS[2].sub(r"\1[已遮盖]", result)
    return result


def _truncate(text: str, maximum: int) -> str:
    """按字符数截断并添加省略号。"""

    cleaned = redact_sensitive(text).strip()
    if len(cleaned) <= maximum:
        return cleaned
    return f"{cleaned[: max(1, maximum - 1)]}…"


def _duration_label(seconds: float | None) -> str | None:
    """把秒数格式化为紧凑中文时长。"""

    if seconds is None:
        return None
    total = max(0, int(round(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} 小时 {minutes} 分 {secs} 秒"
    if minutes:
        return f"{minutes} 分 {secs} 秒"
    return f"{secs} 秒"


def format_notification(event: NotificationEvent, max_length: int) -> str:
    """把任务事件转换为飞书普通文本消息。"""

    title = STATUS_TITLES.get(event.status, "Codex 任务状态变化")
    label = STATUS_LABELS.get(event.status, event.status.value)
    lines = [
        f"【{title}】",
        "",
        f"任务：{_truncate(event.title, 200)}",
    ]
    if event.project_name:
        lines.append(f"项目：{_truncate(event.project_name, 200)}")
    if event.cwd:
        lines.append(f"目录：{_truncate(event.cwd, 500)}")
    if event.branch:
        lines.append(f"分支：{_truncate(event.branch, 200)}")
    lines.append(f"状态：{label}")
    duration = _duration_label(event.duration_seconds)
    if duration:
        lines.append(f"运行时长：{duration}")
    local_time = event.occurred_at.astimezone()
    lines.append(f"事件时间：{local_time:%Y-%m-%d %H:%M:%S %Z}")

    detail = event.waiting_reason or event.error_summary or event.summary
    if detail:
        heading = "待处理：" if event.status in {
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING_INPUT,
        } else "摘要："
        lines.extend(["", heading, _truncate(detail, max_length)])
    return "\n".join(lines)
