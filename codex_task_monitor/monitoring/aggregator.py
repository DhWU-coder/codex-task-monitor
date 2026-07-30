"""多个 Codex 数据源的任务状态聚合。"""

from datetime import UTC, datetime
from pathlib import Path

from codex_task_monitor.models import (
    SourceEvent,
    SourceKind,
    TaskSnapshot,
    TaskStatus,
    WatchMode,
)

TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.INTERRUPTED,
    TaskStatus.MANUALLY_COMPLETED,
}
ACTIVE_STATUSES = {
    TaskStatus.RUNNING,
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.WAITING_INPUT,
}
MIN_STARTED_AT = datetime.min.replace(tzinfo=UTC)


class TaskAggregator:
    """按线程维护最新的安全任务快照。"""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSnapshot] = {}
        self._app_server_titles: dict[str, str] = {}
        self._parent_thread_ids: dict[str, str] = {}
        self._app_server_thread_ids: set[str] = set()
        self._internal_thread_ids: set[str] = set()
        self._orphaned_thread_ids: set[str] = set()

    def apply(self, event: SourceEvent) -> TaskSnapshot:
        """合并一条标准来源事件。"""

        if (
            event.parent_thread_id
            and event.parent_thread_id != event.thread_id
        ):
            self._parent_thread_ids[event.thread_id] = event.parent_thread_id
            self._reconcile_internal_threads()
        current = self._tasks.get(event.thread_id)
        if (
            current is not None
            and event.source is SourceKind.SESSION
            and event.thread_id in self._orphaned_thread_ids
        ):
            self._orphaned_thread_ids.discard(event.thread_id)
            current = current.model_copy(
                update={
                    "status": TaskStatus.RUNNING,
                    "completed_at": None,
                    "waiting_reason": "",
                    "request_id": None,
                }
            )
        snapshot = (
            self._new_snapshot(event)
            if current is None
            else self._merge(current, event)
        )
        authoritative_title = self._app_server_titles.get(event.thread_id)
        if authoritative_title and snapshot.title != authoritative_title:
            snapshot = snapshot.model_copy(
                update={"title": authoritative_title}
            )
        self._tasks[event.thread_id] = snapshot
        return snapshot

    def set_app_server_thread_ids(self, thread_ids: set[str]) -> None:
        """使用一次完整 App Server 列表更新侧栏可见任务。"""

        self._app_server_thread_ids = {
            thread_id for thread_id in thread_ids if thread_id
        }
        self._reconcile_internal_threads()

    def set_app_server_title(
        self,
        thread_id: str,
        title: str | None,
    ) -> None:
        """注册 App Server 提供的任务名称。"""

        normalized_thread_id = thread_id.strip()
        normalized_title = title.strip() if title else ""
        if not normalized_thread_id or not normalized_title:
            return
        self._app_server_titles[normalized_thread_id] = normalized_title
        current = self._tasks.get(normalized_thread_id)
        if current is not None and current.title != normalized_title:
            self._tasks[normalized_thread_id] = current.model_copy(
                update={"title": normalized_title}
            )

    def mark_orphaned_interrupted(
        self,
        thread_id: str,
        *,
        completed_at: datetime,
    ) -> TaskSnapshot | None:
        """把缺失终态且超时的活动任务标记为推断中断。"""

        current = self._tasks.get(thread_id)
        if current is None or current.status not in ACTIVE_STATUSES:
            return None
        self._orphaned_thread_ids.add(thread_id)
        updated = current.model_copy(
            update={
                "status": TaskStatus.INTERRUPTED,
                "completed_at": completed_at,
                "updated_at": max(current.updated_at, completed_at),
                "waiting_reason": "",
                "request_id": None,
            }
        )
        self._tasks[thread_id] = updated
        return updated

    def mark_manually_completed(
        self,
        thread_id: str,
        *,
        completed_at: datetime,
    ) -> TaskSnapshot | None:
        """把当前任务轮次标记为手动结束。"""

        current = self._tasks.get(thread_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={
                "status": TaskStatus.MANUALLY_COMPLETED,
                "completed_at": completed_at,
                "updated_at": max(current.updated_at, completed_at),
                "waiting_reason": "",
                "request_id": None,
            }
        )
        self._tasks[thread_id] = updated
        return updated

    def clear_manual_completion(
        self,
        thread_id: str,
    ) -> TaskSnapshot | None:
        """清除旧轮次的手动结束投影，等待新事件重新赋值。"""

        current = self._tasks.get(thread_id)
        if current is None or current.status is not TaskStatus.MANUALLY_COMPLETED:
            return current
        updated = current.model_copy(
            update={
                "status": TaskStatus.UNKNOWN,
                "completed_at": None,
                "waiting_reason": "",
                "request_id": None,
            }
        )
        self._tasks[thread_id] = updated
        return updated

    def hidden_thread_ids(self) -> set[str]:
        """返回当前已确认且不在侧栏中的内部节点。"""

        return {
            thread_id
            for thread_id in self._internal_thread_ids
            if thread_id not in self._app_server_thread_ids
        }

    def is_hidden(self, thread_id: str) -> bool:
        """判断任务是否为当前不可见的内部续接节点。"""

        return (
            thread_id in self._internal_thread_ids
            and thread_id not in self._app_server_thread_ids
        )

    def apply_snapshot(self, snapshot: TaskSnapshot) -> TaskSnapshot:
        """合并一个已经映射的 App Server 快照。"""

        self.set_app_server_title(snapshot.thread_id, snapshot.title)
        event = SourceEvent(
            source=snapshot.source,
            thread_id=snapshot.thread_id,
            turn_id=snapshot.turn_id,
            title=snapshot.title,
            status=snapshot.status,
            cwd=snapshot.cwd,
            branch=snapshot.branch,
            started_at=snapshot.started_at,
            completed_at=snapshot.completed_at,
            updated_at=snapshot.updated_at,
            latest_summary=snapshot.latest_summary,
            waiting_reason=snapshot.waiting_reason,
            request_id=snapshot.request_id,
            error_summary=snapshot.error_summary,
            authoritative=snapshot.status in TERMINAL_STATUSES,
        )
        merged = self.apply(event)
        if merged.source_label != snapshot.source_label:
            merged = merged.model_copy(update={"source_label": snapshot.source_label})
            self._tasks[snapshot.thread_id] = merged
        return merged

    def set_watch(
        self,
        thread_id: str,
        *,
        monitored: bool,
        mode: WatchMode | None,
    ) -> TaskSnapshot | None:
        """更新任务卡片上的监控状态。"""

        current = self._tasks.get(thread_id)
        if current is None:
            return None
        updated = current.model_copy(
            update={"monitored": monitored, "watch_mode": mode}
        )
        self._tasks[thread_id] = updated
        return updated

    def get(self, thread_id: str) -> TaskSnapshot | None:
        """按线程 ID 返回任务。"""

        if self.is_hidden(thread_id):
            return None
        return self._tasks.get(thread_id)

    def list_tasks(self) -> list[TaskSnapshot]:
        """按开始时间倒序和任务 ID 升序稳定返回任务。"""

        tasks = sorted(
            (
                task
                for task in self._tasks.values()
                if not self.is_hidden(task.thread_id)
            ),
            key=lambda task: task.thread_id,
        )
        return sorted(
            tasks,
            key=lambda task: task.started_at or MIN_STARTED_AT,
            reverse=True,
        )

    def _reconcile_internal_threads(self) -> None:
        """从侧栏可见任务向上确认不可见的内部续接祖先。"""

        for thread_id in self._app_server_thread_ids:
            current_thread_id = thread_id
            visited = {current_thread_id}
            while True:
                parent_thread_id = self._parent_thread_ids.get(
                    current_thread_id
                )
                if (
                    not parent_thread_id
                    or parent_thread_id in visited
                ):
                    break
                visited.add(parent_thread_id)
                if parent_thread_id not in self._app_server_thread_ids:
                    self._internal_thread_ids.add(parent_thread_id)
                current_thread_id = parent_thread_id

    @staticmethod
    def _new_snapshot(event: SourceEvent) -> TaskSnapshot:
        """从首条来源事件创建任务。"""

        cwd = event.cwd
        return TaskSnapshot(
            thread_id=event.thread_id,
            turn_id=event.turn_id,
            title=event.title or event.thread_id[:8],
            status=event.status or TaskStatus.UNKNOWN,
            source=event.source,
            project_name=Path(cwd).name if cwd else None,
            cwd=cwd,
            branch=event.branch,
            started_at=event.started_at,
            completed_at=event.completed_at,
            updated_at=event.updated_at,
            latest_summary=event.latest_summary or "",
            waiting_reason=event.waiting_reason or "",
            request_id=event.request_id,
            error_summary=event.error_summary or "",
        )

    @staticmethod
    def _merge(current: TaskSnapshot, event: SourceEvent) -> TaskSnapshot:
        """根据终态保护和最新 Turn 规则合并事件。"""

        different_turn = bool(
            event.turn_id
            and current.turn_id
            and event.turn_id != current.turn_id
        )
        manually_completed_same_turn = (
            current.status is TaskStatus.MANUALLY_COMPLETED
            and not different_turn
        )
        new_status = current.status
        if event.status and event.status not in {
            TaskStatus.UNKNOWN,
            TaskStatus.SOURCE_ERROR,
        }:
            if manually_completed_same_turn:
                pass
            elif current.status in TERMINAL_STATUSES and not different_turn:
                if event.status in TERMINAL_STATUSES and event.authoritative:
                    new_status = event.status
            else:
                new_status = event.status

        source = (
            current.source
            if current.source is event.source
            else SourceKind.MERGED
        )
        return current.model_copy(
            update={
                "turn_id": event.turn_id or current.turn_id,
                "title": event.title or current.title,
                "status": new_status,
                "source": source,
                "project_name": (
                    Path(event.cwd).name if event.cwd else current.project_name
                ),
                "cwd": event.cwd or current.cwd,
                "branch": event.branch or current.branch,
                "started_at": (
                    event.started_at
                    if different_turn or event.started_at
                    else current.started_at
                ),
                "completed_at": (
                    current.completed_at
                    if manually_completed_same_turn
                    else (
                        event.completed_at
                        if event.completed_at or different_turn
                        else current.completed_at
                    )
                ),
                "updated_at": max(current.updated_at, event.updated_at),
                "latest_summary": (
                    event.latest_summary
                    if event.latest_summary is not None
                    else current.latest_summary
                ),
                "waiting_reason": (
                    event.waiting_reason
                    if event.waiting_reason is not None
                    else current.waiting_reason
                ),
                "request_id": event.request_id or current.request_id,
                "error_summary": (
                    event.error_summary
                    if event.error_summary is not None
                    else current.error_summary
                ),
            }
        )
