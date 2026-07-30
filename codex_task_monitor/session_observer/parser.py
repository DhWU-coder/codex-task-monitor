"""Codex 会话 JSONL 记录的版本隔离解析。"""

import json
import re
from datetime import UTC, datetime
from typing import Any

from codex_task_monitor.models import SourceEvent, SourceKind, TaskStatus

TOKEN_PATTERN = re.compile(
    r"(?i)(Authorization\s*:\s*Bearer\s+)\S+|\b[atu]-[A-Za-z0-9._-]{6,}\b"
)


class SessionParser:
    """维护单个会话文件的最小解析状态。"""

    def __init__(self) -> None:
        self.canonical_thread_id: str | None = None
        self.canonical_parent_thread_id: str | None = None
        self.section_thread_id: str | None = None
        self.current_turn_id: str | None = None
        self.cwd: str | None = None
        self.title: str | None = None
        self.started_at: datetime | None = None
        self.latest_summary = ""

    def parse(
        self,
        record: dict[str, Any],
        *,
        baseline: bool = False,
    ) -> list[SourceEvent]:
        """解析一条记录，未知类型安全忽略。"""

        record_type = record.get("type")
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return []
        if record_type == "session_meta":
            return self._session_meta(record, payload, baseline)
        if not self._in_canonical_section():
            return []
        if record_type == "turn_context":
            self.current_turn_id = _text(payload.get("turn_id")) or self.current_turn_id
            self.cwd = _text(payload.get("cwd")) or self.cwd
            return []
        if record_type == "event_msg":
            return self._event_message(record, payload, baseline)
        if record_type == "response_item":
            return self._response_item(record, payload, baseline)
        return []

    def resume_canonical_section(self) -> None:
        """在跳跃读取后把解析区段恢复为当前文件的规范任务。"""

        self.section_thread_id = self.canonical_thread_id

    def _session_meta(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        baseline: bool,
    ) -> list[SourceEvent]:
        """锁定规范会话身份，并跟踪当前回放区段。"""

        thread_id = (
            _text(payload.get("id"))
            or _text(payload.get("session_id"))
        )
        if not thread_id:
            return []
        self.section_thread_id = thread_id
        if self.canonical_thread_id is None:
            self.canonical_thread_id = thread_id
            self.canonical_parent_thread_id = _text(
                payload.get("forked_from_id")
            )
        if not self._in_canonical_section():
            return []
        self.cwd = _text(payload.get("cwd")) or self.cwd
        return [
            self._event(
                record,
                status=TaskStatus.UNKNOWN,
                baseline=baseline,
            )
        ]

    def _event_message(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        baseline: bool,
    ) -> list[SourceEvent]:
        """解析会话中的任务生命周期消息。"""

        message_type = payload.get("type")
        if message_type == "user_message":
            message = _safe_text(payload.get("message"), 300)
            if message and not self.title:
                self.title = message
            return []
        if not self.canonical_thread_id:
            return []
        if message_type == "task_started":
            self.current_turn_id = _text(payload.get("turn_id")) or self.current_turn_id
            self.started_at = _datetime(payload.get("started_at")) or _record_time(record)
            return [
                self._event(
                    record,
                    status=TaskStatus.RUNNING,
                    started_at=self.started_at,
                    baseline=baseline,
                )
            ]
        if message_type == "agent_message":
            self.latest_summary = _safe_text(payload.get("message"), 4000)
            return [
                self._event(
                    record,
                    latest_summary=self.latest_summary,
                    baseline=baseline,
                )
            ]
        if message_type == "task_complete":
            self.current_turn_id = _text(payload.get("turn_id")) or self.current_turn_id
            self.latest_summary = (
                _safe_text(payload.get("last_agent_message"), 4000)
                or self.latest_summary
            )
            return [
                self._event(
                    record,
                    status=TaskStatus.COMPLETED,
                    started_at=_datetime(payload.get("started_at")) or self.started_at,
                    completed_at=(
                        _datetime(payload.get("completed_at")) or _record_time(record)
                    ),
                    latest_summary=self.latest_summary,
                    authoritative=True,
                    baseline=baseline,
                )
            ]
        if message_type in {"task_failed", "turn_failed"}:
            self.current_turn_id = _text(payload.get("turn_id")) or self.current_turn_id
            return [
                self._event(
                    record,
                    status=TaskStatus.FAILED,
                    error_summary=_safe_text(
                        payload.get("error") or payload.get("message"),
                        1000,
                    ),
                    completed_at=_record_time(record),
                    authoritative=True,
                    baseline=baseline,
                )
            ]
        if message_type in {"turn_aborted", "task_interrupted", "turn_interrupted"}:
            self.current_turn_id = _text(payload.get("turn_id")) or self.current_turn_id
            return [
                self._event(
                    record,
                    status=TaskStatus.INTERRUPTED,
                    completed_at=_record_time(record),
                    authoritative=True,
                    baseline=baseline,
                )
            ]
        if message_type == "approval_requested":
            return [
                self._event(
                    record,
                    status=TaskStatus.WAITING_APPROVAL,
                    waiting_reason=_safe_text(
                        payload.get("reason") or payload.get("command"),
                        1000,
                    ),
                    request_id=(
                        _text(payload.get("approval_id"))
                        or _text(payload.get("item_id"))
                    ),
                    baseline=baseline,
                )
            ]
        return []

    def _response_item(
        self,
        record: dict[str, Any],
        payload: dict[str, Any],
        baseline: bool,
    ) -> list[SourceEvent]:
        """识别持久化的用户输入请求。"""

        if (
            not self.canonical_thread_id
            or payload.get("name") != "request_user_input"
        ):
            return []
        arguments = payload.get("arguments")
        decoded: dict[str, Any] = {}
        if isinstance(arguments, str):
            try:
                candidate = json.loads(arguments)
                if isinstance(candidate, dict):
                    decoded = candidate
            except json.JSONDecodeError:
                decoded = {}
        questions = decoded.get("questions")
        reason = ""
        if isinstance(questions, list):
            reason = "；".join(
                _safe_text(question.get("question"), 500)
                for question in questions
                if isinstance(question, dict) and question.get("question")
            )
        return [
            self._event(
                record,
                status=TaskStatus.WAITING_INPUT,
                waiting_reason=reason,
                request_id=(
                    _text(payload.get("call_id")) or _text(payload.get("id"))
                ),
                baseline=baseline,
            )
        ]

    def _event(
        self,
        record: dict[str, Any],
        *,
        status: TaskStatus | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
        latest_summary: str | None = None,
        waiting_reason: str | None = None,
        request_id: str | None = None,
        error_summary: str | None = None,
        authoritative: bool = False,
        baseline: bool = False,
    ) -> SourceEvent:
        """使用当前解析状态构造标准来源事件。"""

        if not self.canonical_thread_id:
            raise ValueError("会话事件缺少 thread_id")
        return SourceEvent(
            source=SourceKind.SESSION,
            thread_id=self.canonical_thread_id,
            parent_thread_id=self.canonical_parent_thread_id,
            turn_id=self.current_turn_id,
            title=self.title,
            status=status,
            cwd=self.cwd,
            started_at=started_at,
            completed_at=completed_at,
            updated_at=_record_time(record) or datetime.now(UTC),
            latest_summary=latest_summary,
            waiting_reason=waiting_reason,
            request_id=request_id,
            error_summary=error_summary,
            authoritative=authoritative,
            baseline=baseline,
        )

    def _in_canonical_section(self) -> bool:
        """判断当前记录是否属于文件的规范任务区段。"""

        return bool(
            self.canonical_thread_id
            and self.section_thread_id == self.canonical_thread_id
        )


def _record_time(record: dict[str, Any]) -> datetime | None:
    """读取记录顶层时间戳。"""

    return _datetime(record.get("timestamp"))


def _datetime(value: Any) -> datetime | None:
    """兼容 ISO 字符串和 Unix 秒时间戳。"""

    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _text(value: Any) -> str | None:
    """把非空标量转换为文本。"""

    if value is None:
        return None
    result = str(value).strip()
    return result or None


def _safe_text(value: Any, maximum: int) -> str:
    """遮盖常见令牌并限制摘要长度。"""

    raw = _text(value) or ""
    redacted = TOKEN_PATTERN.sub("[已遮盖]", raw)
    return redacted[:maximum]
