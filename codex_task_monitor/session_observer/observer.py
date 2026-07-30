"""Codex 会话文件的只读增量观察器。"""

import asyncio
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codex_task_monitor.models import SourceEvent, TaskStatus
from codex_task_monitor.session_observer.parser import SessionParser

LIFECYCLE_MESSAGE_TYPES = frozenset(
    {
        "task_started",
        "task_complete",
        "task_failed",
        "turn_failed",
        "turn_aborted",
        "task_interrupted",
        "turn_interrupted",
        "approval_requested",
    }
)
LIFECYCLE_STATUSES = frozenset(
    {
        TaskStatus.RUNNING,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.INTERRUPTED,
        TaskStatus.WAITING_APPROVAL,
    }
)


@dataclass
class FileCursor:
    """单个会话文件的增量读取位置。"""

    inode: int
    offset: int
    parser: SessionParser = field(default_factory=SessionParser)
    buffer: bytes = b""


class SessionObserver:
    """轮询近期 JSONL 会话并只读取新追加内容。"""

    def __init__(
        self,
        sessions_root: Path,
        *,
        max_files: int = 200,
        bootstrap_head_bytes: int = 1024 * 1024,
        bootstrap_tail_bytes: int = 2 * 1024 * 1024,
        bootstrap_lifecycle_scan_bytes: int = 256 * 1024 * 1024,
        bootstrap_scan_chunk_bytes: int = 1024 * 1024,
        bootstrap_scan_max_line_bytes: int = 4 * 1024 * 1024,
        max_increment_bytes: int = 512 * 1024,
    ) -> None:
        self.sessions_root = sessions_root.expanduser().resolve()
        self.max_files = max_files
        self.bootstrap_head_bytes = bootstrap_head_bytes
        self.bootstrap_tail_bytes = bootstrap_tail_bytes
        self.bootstrap_lifecycle_scan_bytes = bootstrap_lifecycle_scan_bytes
        self.bootstrap_scan_chunk_bytes = bootstrap_scan_chunk_bytes
        self.bootstrap_scan_max_line_bytes = bootstrap_scan_max_line_bytes
        self.max_increment_bytes = max_increment_bytes
        self._cursors: dict[Path, FileCursor] = {}

    async def scan_once(self) -> list[SourceEvent]:
        """在线程池中执行一次只读扫描。"""

        return await asyncio.to_thread(self._scan_sync)

    def _scan_sync(self) -> list[SourceEvent]:
        """发现近期文件并读取可用增量。"""

        events: list[SourceEvent] = []
        for path in self._discover_files():
            try:
                metadata = path.stat()
            except OSError:
                continue
            cursor = self._cursors.get(path)
            if (
                cursor is None
                or cursor.inode != metadata.st_ino
                or metadata.st_size < cursor.offset
            ):
                cursor = FileCursor(inode=metadata.st_ino, offset=metadata.st_size)
                self._cursors[path] = cursor
                events.extend(self._bootstrap(path, cursor, metadata.st_size))
                continue
            if metadata.st_size == cursor.offset:
                continue
            events.extend(self._read_increment(path, cursor, metadata.st_size))
        return events

    def _discover_files(self) -> list[Path]:
        """按最近修改时间返回有限数量的会话文件。"""

        if not self.sessions_root.exists():
            return []
        candidates: list[tuple[float, Path]] = []
        for path in self.sessions_root.rglob("*.jsonl"):
            try:
                candidates.append((path.stat().st_mtime, path))
            except OSError:
                continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [path for _, path in candidates[: self.max_files]]

    def _bootstrap(
        self,
        path: Path,
        cursor: FileCursor,
        size: int,
    ) -> list[SourceEvent]:
        """读取元数据头和有界尾部以建立当前状态基线。"""

        needs_lifecycle_scan = False
        try:
            with path.open("rb") as stream:
                if size <= self.bootstrap_tail_bytes:
                    data = stream.read()
                    events = self._parse_bytes(
                        cursor.parser,
                        data,
                        baseline=True,
                    )
                else:
                    head = stream.read(self.bootstrap_head_bytes)
                    stream.seek(max(0, size - self.bootstrap_tail_bytes))
                    tail = stream.read()
                    newline = tail.find(b"\n")
                    if newline >= 0:
                        tail = tail[newline + 1 :]
                    complete_head, separator, _ = head.rpartition(b"\n")
                    head_data = (
                        complete_head + b"\n" if separator else b""
                    )
                    head_events = self._parse_bytes(
                        cursor.parser,
                        head_data,
                        baseline=True,
                    )
                    cursor.parser.resume_canonical_section()
                    tail_events = self._parse_bytes(
                        cursor.parser,
                        tail,
                        baseline=True,
                    )
                    events = [
                        event
                        for event in head_events
                        if event.status is TaskStatus.UNKNOWN
                    ]
                    events.extend(tail_events)
                    needs_lifecycle_scan = not any(
                        event.status in LIFECYCLE_STATUSES
                        for event in tail_events
                    )
        except OSError:
            return []
        if needs_lifecycle_scan:
            lifecycle = self._find_latest_canonical_lifecycle(
                path,
                cursor.parser.canonical_thread_id,
                size,
            )
            if lifecycle is not None:
                cursor.parser.resume_canonical_section()
                events.extend(
                    cursor.parser.parse(lifecycle, baseline=True)
                )
        cursor.offset = size
        cursor.buffer = b""
        return events

    def _find_latest_canonical_lifecycle(
        self,
        path: Path,
        canonical_thread_id: str | None,
        size: int,
    ) -> dict[str, Any] | None:
        """从文件尾向前寻找最近且属于规范区段的生命周期。"""

        if not canonical_thread_id:
            return None
        candidate: dict[str, Any] | None = None
        following_section_thread_id: str | None = None
        try:
            lines = self._iter_lines_reverse(path, size)
            for raw_line in lines:
                record = self._decode_record(raw_line)
                if record is None:
                    continue
                section_thread_id = self._session_meta_thread_id(record)
                if section_thread_id is not None:
                    if (
                        candidate is not None
                        and section_thread_id == canonical_thread_id
                    ):
                        return candidate
                    candidate = None
                    following_section_thread_id = section_thread_id
                    continue
                if candidate is None:
                    if self._is_lifecycle_record(record):
                        if (
                            following_section_thread_id
                            == canonical_thread_id
                            and self._lifecycle_message_type(record)
                            == "task_started"
                        ):
                            return record
                        candidate = record
                    continue
        except OSError:
            return None
        return None

    def _iter_lines_reverse(
        self,
        path: Path,
        size: int,
    ) -> Iterator[bytes]:
        """按从新到旧顺序迭代有界完整行，并跳过超长行。"""

        lower_bound = max(0, size - self.bootstrap_lifecycle_scan_bytes)
        position = size
        fragment = b""
        fragment_too_large = False
        chunk_size = max(1, self.bootstrap_scan_chunk_bytes)
        maximum_line = max(1, self.bootstrap_scan_max_line_bytes)
        with path.open("rb") as stream:
            while position > lower_bound:
                start = max(lower_bound, position - chunk_size)
                stream.seek(start)
                chunk = stream.read(position - start)
                position = start
                parts = chunk.split(b"\n")
                if len(parts) == 1:
                    if not fragment_too_large:
                        combined_size = len(parts[0]) + len(fragment)
                        if combined_size <= maximum_line:
                            fragment = parts[0] + fragment
                        else:
                            fragment = b""
                            fragment_too_large = True
                    continue

                rightmost = parts[-1]
                if (
                    not fragment_too_large
                    and len(rightmost) + len(fragment) <= maximum_line
                ):
                    complete_rightmost = rightmost + fragment
                    if complete_rightmost.strip():
                        yield complete_rightmost

                fragment_too_large = False
                fragment = b""
                for raw_line in reversed(parts[1:-1]):
                    if 0 < len(raw_line) <= maximum_line and raw_line.strip():
                        yield raw_line

                leftmost = parts[0]
                if len(leftmost) <= maximum_line:
                    fragment = leftmost
                else:
                    fragment_too_large = True

        if (
            lower_bound == 0
            and not fragment_too_large
            and fragment.strip()
        ):
            yield fragment

    @staticmethod
    def _decode_record(raw_line: bytes) -> dict[str, Any] | None:
        """安全解码一条 JSONL 记录。"""

        try:
            record = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(record, dict):
            return None
        return _dict_record(record)

    @staticmethod
    def _is_lifecycle_record(record: dict[str, Any]) -> bool:
        """判断记录是否为支持的任务生命周期消息。"""

        return (
            SessionObserver._lifecycle_message_type(record)
            in LIFECYCLE_MESSAGE_TYPES
        )

    @staticmethod
    def _lifecycle_message_type(record: dict[str, Any]) -> str | None:
        """读取事件记录中的生命周期消息类型。"""

        if record.get("type") != "event_msg":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        value = payload.get("type")
        return value if isinstance(value, str) else None

    @staticmethod
    def _session_meta_thread_id(record: dict[str, Any]) -> str | None:
        """读取会话区段元数据中的任务 ID。"""

        if record.get("type") != "session_meta":
            return None
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return None
        value = payload.get("id") or payload.get("session_id")
        if value is None:
            return None
        result = str(value).strip()
        return result or None

    def _read_increment(
        self,
        path: Path,
        cursor: FileCursor,
        size: int,
    ) -> list[SourceEvent]:
        """从游标位置读取一段增量并保留半行。"""

        bytes_to_read = min(size - cursor.offset, self.max_increment_bytes)
        try:
            with path.open("rb") as stream:
                stream.seek(cursor.offset)
                chunk = stream.read(bytes_to_read)
        except OSError:
            return []
        cursor.offset += len(chunk)
        combined = cursor.buffer + chunk
        complete, separator, remainder = combined.rpartition(b"\n")
        if not separator:
            cursor.buffer = combined
            return []
        cursor.buffer = remainder
        return self._parse_bytes(cursor.parser, complete + b"\n", baseline=False)

    @staticmethod
    def _parse_bytes(
        parser: SessionParser,
        data: bytes,
        *,
        baseline: bool,
    ) -> list[SourceEvent]:
        """解析完整 JSONL 行并忽略局部损坏记录。"""

        events: list[SourceEvent] = []
        for raw_line in data.splitlines():
            if not raw_line.strip():
                continue
            try:
                record = json.loads(raw_line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(record, dict):
                continue
            events.extend(parser.parse(_dict_record(record), baseline=baseline))
        return events


def _dict_record(record: dict[Any, Any]) -> dict[str, Any]:
    """把 JSON 对象收窄为字符串键字典。"""

    return {str(key): value for key, value in record.items()}
