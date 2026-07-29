"""监控记录、通知幂等和任务快照仓储。"""

import json
import sqlite3
from datetime import UTC, datetime

from codex_task_monitor.models import TaskSnapshot, TaskStatus, WatchMode, WatchRecord
from codex_task_monitor.storage.database import Database


def _now_text() -> str:
    """返回可按字典序排序的 UTC 时间。"""

    return datetime.now(UTC).isoformat()


class Repository:
    """封装任务监控器需要的 SQLite 访问。"""

    def __init__(self, database: Database) -> None:
        self.database = database

    def save_watch(
        self,
        *,
        thread_id: str,
        mode: WatchMode,
        turn_id: str | None = None,
        baseline_status: TaskStatus | None = None,
        active: bool = True,
    ) -> WatchRecord:
        """新增或覆盖一个线程的监控选择。"""

        now = _now_text()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO watches (
                    thread_id, mode, turn_id, baseline_status, active, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    mode = excluded.mode,
                    turn_id = excluded.turn_id,
                    baseline_status = excluded.baseline_status,
                    active = excluded.active,
                    updated_at = excluded.updated_at
                """,
                (
                    thread_id,
                    mode.value,
                    turn_id,
                    baseline_status.value if baseline_status else None,
                    int(active),
                    now,
                    now,
                ),
            )
        result = self.get_watch(thread_id)
        if result is None:
            raise RuntimeError("保存监控记录后未能重新读取")
        return result

    def get_watch(self, thread_id: str) -> WatchRecord | None:
        """按线程 ID 返回监控记录。"""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM watches WHERE thread_id = ?",
                (thread_id,),
            ).fetchone()
        return self._watch_from_row(row) if row else None

    def list_active_watches(self) -> list[WatchRecord]:
        """返回所有仍启用的监控记录。"""

        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM watches WHERE active = 1 ORDER BY created_at"
            ).fetchall()
        return [self._watch_from_row(row) for row in rows]

    def deactivate_watch(self, thread_id: str) -> None:
        """停用指定线程的监控。"""

        with self.database.connect() as connection:
            connection.execute(
                "UPDATE watches SET active = 0, updated_at = ? WHERE thread_id = ?",
                (_now_text(), thread_id),
            )

    def restore_watches(self, statuses: dict[str, TaskStatus]) -> list[WatchRecord]:
        """只保留启动时仍处于活动状态的监控记录。"""

        resumable = {
            TaskStatus.RUNNING,
            TaskStatus.WAITING_APPROVAL,
            TaskStatus.WAITING_INPUT,
        }
        for watch in self.list_active_watches():
            if statuses.get(watch.thread_id) not in resumable:
                self.deactivate_watch(watch.thread_id)
        return self.list_active_watches()

    def reserve_notification(
        self,
        dedupe_key: str,
        *,
        thread_id: str = "",
        turn_id: str | None = None,
        status: TaskStatus | None = None,
        message: str = "",
    ) -> bool:
        """原子预留通知幂等键。"""

        now = _now_text()
        try:
            with self.database.connect() as connection:
                connection.execute(
                    """
                    INSERT INTO notifications (
                        dedupe_key, thread_id, turn_id, status, state, message,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)
                    """,
                    (
                        dedupe_key,
                        thread_id,
                        turn_id,
                        status.value if status else None,
                        message,
                        now,
                        now,
                    ),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def mark_notification_sent(self, dedupe_key: str, message_id: str) -> None:
        """记录飞书已确认发送成功。"""

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE notifications
                SET state = 'sent', external_message_id = ?, error = NULL, updated_at = ?
                WHERE dedupe_key = ?
                """,
                (message_id, _now_text(), dedupe_key),
            )

    def mark_notification_failed(self, dedupe_key: str, error: str) -> None:
        """记录通知最终失败。"""

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE notifications
                SET state = 'failed', error = ?, updated_at = ?
                WHERE dedupe_key = ?
                """,
                (error[:1000], _now_text(), dedupe_key),
            )

    def update_notification_message(
        self,
        dedupe_key: str,
        message: str,
    ) -> None:
        """保存经过脱敏和截断的最终通知正文。"""

        with self.database.connect() as connection:
            connection.execute(
                """
                UPDATE notifications
                SET message = ?, updated_at = ?
                WHERE dedupe_key = ?
                """,
                (message, _now_text(), dedupe_key),
            )

    def get_notification(
        self,
        notification_id: int,
    ) -> dict[str, object] | None:
        """按自增 ID 返回一条通知记录。"""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM notifications WHERE id = ?",
                (notification_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_notification_by_key(
        self,
        dedupe_key: str,
    ) -> dict[str, object] | None:
        """按幂等键返回一条通知记录。"""

        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM notifications WHERE dedupe_key = ?",
                (dedupe_key,),
            ).fetchone()
        return dict(row) if row else None

    def prepare_notification_retry(
        self,
        notification_id: int,
    ) -> dict[str, object] | None:
        """仅把正文非空的失败通知原子切换为待发送。"""

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE notifications
                SET state = 'pending', error = NULL, updated_at = ?
                WHERE id = ? AND state = 'failed' AND message <> ''
                """,
                (_now_text(), notification_id),
            )
            if cursor.rowcount != 1:
                return None
            row = connection.execute(
                "SELECT * FROM notifications WHERE id = ?",
                (notification_id,),
            ).fetchone()
        return dict(row) if row else None

    def save_snapshot(self, snapshot: TaskSnapshot) -> None:
        """保存任务的安全投影。"""

        payload = snapshot.model_dump_json()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO task_snapshots (thread_id, payload, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(thread_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (snapshot.thread_id, payload, snapshot.updated_at.isoformat()),
            )

    def list_snapshots(self) -> list[TaskSnapshot]:
        """读取保存的任务安全投影。"""

        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM task_snapshots ORDER BY updated_at DESC"
            ).fetchall()
        return [TaskSnapshot.model_validate(json.loads(row["payload"])) for row in rows]

    @staticmethod
    def _watch_from_row(row: sqlite3.Row) -> WatchRecord:
        """把数据库行转换为监控领域模型。"""

        return WatchRecord(
            thread_id=row["thread_id"],
            mode=WatchMode(row["mode"]),
            turn_id=row["turn_id"],
            baseline_status=(
                TaskStatus(row["baseline_status"]) if row["baseline_status"] else None
            ),
            active=bool(row["active"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )
