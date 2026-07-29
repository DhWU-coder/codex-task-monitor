"""任务监控模式、状态转换和通知决策。"""

from datetime import datetime

from codex_task_monitor.models import (
    NotificationEvent,
    TaskSnapshot,
    TaskStatus,
    WatchMode,
    WatchRecord,
)
from codex_task_monitor.storage.repository import Repository

ACTIVE_STATUSES = {
    TaskStatus.RUNNING,
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.WAITING_INPUT,
}
TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.FAILED,
    TaskStatus.INTERRUPTED,
}
WAITING_STATUSES = {
    TaskStatus.WAITING_APPROVAL,
    TaskStatus.WAITING_INPUT,
}


class MonitoringService:
    """根据用户选择把任务状态变化转换为通知事件。"""

    def __init__(self, repository: Repository) -> None:
        self.repository = repository
        self._last_statuses: dict[tuple[str, str | None], TaskStatus] = {}

    async def start_watch(
        self,
        task: TaskSnapshot,
        mode: WatchMode,
    ) -> WatchRecord:
        """从任务当前状态建立监控基线。"""

        if task.status not in ACTIVE_STATUSES:
            raise ValueError("只能监控正在运行或等待处理的任务")
        if not task.turn_id:
            raise ValueError("任务缺少当前 Turn ID")
        watch = self.repository.save_watch(
            thread_id=task.thread_id,
            mode=mode,
            turn_id=task.turn_id,
            baseline_status=task.status,
            active=True,
        )
        self._last_statuses[(task.thread_id, task.turn_id)] = task.status
        return watch

    async def stop_watch(self, thread_id: str) -> None:
        """停用指定线程的监控。"""

        self.repository.deactivate_watch(thread_id)

    def watch_for(self, thread_id: str) -> WatchRecord | None:
        """返回指定线程的监控记录。"""

        return self.repository.get_watch(thread_id)

    async def apply(self, task: TaskSnapshot) -> list[NotificationEvent]:
        """处理一个新任务快照并返回待发送通知。"""

        watch = self.repository.get_watch(task.thread_id)
        if not watch or not watch.active:
            return []
        if watch.mode is WatchMode.CURRENT_TURN and task.turn_id != watch.turn_id:
            return []

        state_key = (task.thread_id, task.turn_id)
        had_observation = state_key in self._last_statuses
        previous = self._last_statuses.get(state_key)
        if previous is None and task.turn_id == watch.turn_id:
            previous = watch.baseline_status
        self._last_statuses[state_key] = task.status

        if not had_observation and previous is task.status:
            return []
        if task.status not in WAITING_STATUSES | TERMINAL_STATUSES:
            return []

        dedupe_key = self._dedupe_key(task)
        if not self.repository.reserve_notification(
            dedupe_key,
            thread_id=task.thread_id,
            turn_id=task.turn_id,
            status=task.status,
        ):
            return []

        event = self._build_event(task, dedupe_key)
        if task.status in TERMINAL_STATUSES and watch.mode is WatchMode.CURRENT_TURN:
            self.repository.deactivate_watch(task.thread_id)
        else:
            self.repository.save_watch(
                thread_id=task.thread_id,
                mode=watch.mode,
                turn_id=task.turn_id,
                baseline_status=task.status,
                active=True,
            )
        return [event]

    @staticmethod
    def _dedupe_key(task: TaskSnapshot) -> str:
        """为等待或终态事件创建稳定幂等键。"""

        if task.status in WAITING_STATUSES:
            event_identity = task.request_id or task.status.value
            return f"{task.thread_id}:{task.turn_id}:{event_identity}"
        return f"{task.thread_id}:{task.turn_id}:{task.status.value}"

    @staticmethod
    def _build_event(task: TaskSnapshot, dedupe_key: str) -> NotificationEvent:
        """把任务安全投影转换为通知领域事件。"""

        duration = _duration_seconds(task.started_at, task.completed_at)
        return NotificationEvent(
            dedupe_key=dedupe_key,
            thread_id=task.thread_id,
            turn_id=task.turn_id,
            status=task.status,
            title=task.title,
            project_name=task.project_name,
            cwd=task.cwd,
            branch=task.branch,
            duration_seconds=duration,
            occurred_at=task.completed_at or task.updated_at,
            summary=task.latest_summary,
            waiting_reason=task.waiting_reason,
            error_summary=task.error_summary,
        )


def _duration_seconds(
    started_at: datetime | None,
    ended_at: datetime | None,
) -> float | None:
    """计算非负任务运行时长。"""

    if not started_at:
        return None
    effective_end = ended_at or datetime.now(started_at.tzinfo)
    return max(0.0, (effective_end - started_at).total_seconds())
