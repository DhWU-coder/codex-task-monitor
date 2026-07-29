"""Codex 会话文件的只读增量观察器。"""

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codex_task_monitor.models import SourceEvent
from codex_task_monitor.session_observer.parser import SessionParser


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
        bootstrap_tail_bytes: int = 2 * 1024 * 1024,
        max_increment_bytes: int = 512 * 1024,
    ) -> None:
        self.sessions_root = sessions_root.expanduser().resolve()
        self.max_files = max_files
        self.bootstrap_tail_bytes = bootstrap_tail_bytes
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

        try:
            with path.open("rb") as stream:
                if size <= self.bootstrap_tail_bytes:
                    data = stream.read()
                else:
                    head = stream.read(64 * 1024)
                    stream.seek(max(0, size - self.bootstrap_tail_bytes))
                    tail = stream.read()
                    newline = tail.find(b"\n")
                    if newline >= 0:
                        tail = tail[newline + 1 :]
                    data = head + b"\n" + tail
        except OSError:
            return []
        cursor.offset = size
        cursor.buffer = b""
        return self._parse_bytes(cursor.parser, data, baseline=True)

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
