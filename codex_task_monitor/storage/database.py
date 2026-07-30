"""SQLite 连接和表结构管理。"""

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    thread_id TEXT PRIMARY KEY,
    mode TEXT NOT NULL,
    turn_id TEXT,
    baseline_status TEXT,
    active INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedupe_key TEXT NOT NULL UNIQUE,
    thread_id TEXT NOT NULL DEFAULT '',
    turn_id TEXT,
    status TEXT,
    state TEXT NOT NULL DEFAULT 'pending',
    message TEXT NOT NULL DEFAULT '',
    external_message_id TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_snapshots (
    thread_id TEXT PRIMARY KEY,
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS manual_completions (
    thread_id TEXT PRIMARY KEY,
    turn_id TEXT,
    started_at TEXT,
    marked_at TEXT NOT NULL
);
"""


class Database:
    """提供短生命周期 SQLite 连接和事务。"""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def initialize(self) -> None:
        """创建数据目录、数据库和表结构。"""

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
        os.chmod(self.path, 0o600)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        """打开启用行访问和外键约束的数据库连接。"""

        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()
