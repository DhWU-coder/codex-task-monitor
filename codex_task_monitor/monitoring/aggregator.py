"""多个 Codex 数据源的任务状态聚合。"""

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
}


class TaskAggregator:
    """按线程维护最新的安全任务快照。"""

    def __init__(self) -> None:
        self._tasks: dict[str, TaskSnapshot] = {}

    def apply(self, event: SourceEvent) -> TaskSnapshot:
        """合并一条标准来源事件。"""

        current = self._tasks.get(event.thread_id)
        snapshot = (
            self._new_snapshot(event)
            if current is None
            else self._merge(current, event)
        )
        self._tasks[event.thread_id] = snapshot
        return snapshot

    def apply_snapshot(self, snapshot: TaskSnapshot) -> TaskSnapshot:
        """合并一个已经映射的 App Server 快照。"""

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

        return self._tasks.get(thread_id)

    def list_tasks(self) -> list[TaskSnapshot]:
        """按最近更新时间倒序返回任务。"""

        return sorted(
            self._tasks.values(),
            key=lambda task: task.updated_at,
            reverse=True,
        )

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
        new_status = current.status
        if event.status and event.status not in {
            TaskStatus.UNKNOWN,
            TaskStatus.SOURCE_ERROR,
        }:
            if current.status in TERMINAL_STATUSES and not different_turn:
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
                    event.completed_at
                    if event.completed_at or different_turn
                    else current.completed_at
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
