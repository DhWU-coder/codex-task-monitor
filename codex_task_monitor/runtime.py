"""Codex 采集、监控决策、通知和实时发布的运行时编排。"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from codex_task_monitor.codex_adapter.mapper import map_notification, map_thread
from codex_task_monitor.config.service import ConfigService
from codex_task_monitor.models import (
    SourceEvent,
    SourceHealth,
    TaskSnapshot,
    TaskStatus,
    WatchMode,
    WatchRecord,
)
from codex_task_monitor.monitoring.aggregator import TaskAggregator
from codex_task_monitor.monitoring.project_info import resolve_project_info
from codex_task_monitor.monitoring.service import MonitoringService
from codex_task_monitor.notifications.feishu import FeishuClient
from codex_task_monitor.notifications.formatter import format_notification
from codex_task_monitor.storage.repository import Repository

LOGGER = logging.getLogger(__name__)
SOURCE_KINDS = ["cli", "vscode", "exec", "appServer", "unknown"]
ACTIVE_STATUSES = frozenset(
    {
        TaskStatus.RUNNING,
        TaskStatus.WAITING_APPROVAL,
        TaskStatus.WAITING_INPUT,
    }
)


class AppClientProtocol(Protocol):
    """运行时需要的 App Server 客户端能力。"""

    @property
    def connected(self) -> bool: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...

    async def request(
        self,
        method: str,
        params: dict[str, Any],
    ) -> Any: ...

    async def next_notification(
        self,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]: ...


class ObserverProtocol(Protocol):
    """运行时需要的本地会话观察能力。"""

    async def scan_once(self) -> list[SourceEvent]: ...


class NotifierProtocol(Protocol):
    """运行时需要的通知通道能力。"""

    async def send_text(self, text: str) -> str: ...

    async def close(self) -> None: ...


class PublisherProtocol(Protocol):
    """向 Web SSE 层广播安全事件。"""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None: ...


class NullPublisher:
    """未连接 Web 层时丢弃广播。"""

    async def publish(self, event_type: str, payload: dict[str, Any]) -> None:
        return None


class RuntimeService:
    """组合只读数据源并执行监控通知规则。"""

    def __init__(
        self,
        *,
        config_service: ConfigService,
        repository: Repository,
        app_client: AppClientProtocol,
        observer: ObserverProtocol,
        notifier: NotifierProtocol,
        publisher: PublisherProtocol | None = None,
    ) -> None:
        self.config_service = config_service
        self.repository = repository
        self.app_client = app_client
        self.observer = observer
        self.notifier = notifier
        self.publisher = publisher or NullPublisher()
        self.aggregator = TaskAggregator()
        self.monitoring = MonitoringService(repository)
        self.health: dict[str, SourceHealth] = {
            "app_server": SourceHealth(name="app_server", connected=False),
            "session_observer": SourceHealth(
                name="session_observer",
                connected=True,
            ),
        }
        self._stop_event = asyncio.Event()
        self._tasks: list[asyncio.Task[None]] = []
        self._notifier_lock = asyncio.Lock()

    async def start(self) -> None:
        """建立数据源基线并启动后台循环。"""

        self._stop_event.clear()
        try:
            await self.app_client.start()
            self._set_health("app_server", True, "")
            await self.refresh_once(allow_notifications=False)
        except Exception as error:
            self._set_health("app_server", False, str(error))
            LOGGER.warning("Codex App Server 初次连接失败：%s", error)
        await self.observe_once(allow_notifications=False)
        statuses = {task.thread_id: task.status for task in self.list_tasks()}
        restored = self.repository.restore_watches(statuses)
        for watch in restored:
            self.aggregator.set_watch(
                watch.thread_id,
                monitored=True,
                mode=watch.mode,
            )
        self._tasks = [
            asyncio.create_task(self._refresh_loop()),
            asyncio.create_task(self._observer_loop()),
            asyncio.create_task(self._notification_loop()),
        ]
        await self._publish_tasks()
        await self._publish_health()

    async def stop(self) -> None:
        """停止所有循环并关闭外部客户端。"""

        self._stop_event.set()
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()
        await self.app_client.stop()
        async with self._notifier_lock:
            await self.notifier.close()
        self._set_health("app_server", False, "已停止")

    async def refresh_once(self, *, allow_notifications: bool = True) -> None:
        """读取 App Server 的全部非归档顶层任务。"""

        config = self.config_service.load()
        recent_cutoff = datetime.now(UTC) - timedelta(
            hours=config.codex.recent_completed_hours
        )
        cursor: str | None = None
        while True:
            result = await self.app_client.request(
                "thread/list",
                {
                    "cursor": cursor,
                    "limit": 100,
                    "sortKey": "updated_at",
                    "sortDirection": "desc",
                    "sourceKinds": SOURCE_KINDS,
                    "archived": False,
                    "useStateDbOnly": True,
                },
            )
            if not isinstance(result, dict):
                break
            rows = result.get("data")
            if not isinstance(rows, list):
                break
            for raw_thread in rows:
                if not isinstance(raw_thread, dict):
                    continue
                snapshot = map_thread(raw_thread)
                if not _should_include_snapshot(snapshot, recent_cutoff):
                    continue
                current = self.aggregator.get(snapshot.thread_id)
                if _needs_thread_details(snapshot, current):
                    snapshot = await self._read_active_thread(snapshot)
                await self._accept_snapshot(
                    snapshot,
                    allow_notifications=allow_notifications,
                )
            next_cursor = result.get("nextCursor")
            cursor = next_cursor if isinstance(next_cursor, str) else None
            if not cursor:
                break
        self._set_health("app_server", True, "")
        await self._publish_tasks()
        await self._publish_health()

    async def observe_once(self, *, allow_notifications: bool = True) -> None:
        """读取本地会话增量并合并。"""

        events = await self.observer.scan_once()
        recent_cutoff = datetime.now(UTC) - timedelta(
            hours=self.config_service.load().codex.recent_completed_hours
        )
        accepted_events = [
            event for event in events if event.updated_at >= recent_cutoff
        ]
        for event in accepted_events:
            snapshot = self.aggregator.apply(event)
            await self._process_snapshot(
                snapshot,
                allow_notifications=allow_notifications and not event.baseline,
            )
            if event.baseline and snapshot.status in {
                TaskStatus.COMPLETED,
                TaskStatus.FAILED,
                TaskStatus.INTERRUPTED,
            }:
                self.repository.deactivate_watch(snapshot.thread_id)
                self.aggregator.set_watch(
                    snapshot.thread_id,
                    monitored=False,
                    mode=None,
                )
        self._set_health("session_observer", True, "")
        if accepted_events:
            await self._publish_tasks()
            await self._publish_health()

    async def handle_notification(self, message: dict[str, Any]) -> None:
        """处理一条 App Server 主动通知。"""

        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        event = map_notification(method, params)
        if event is None:
            return
        snapshot = self.aggregator.apply(event)
        await self._process_snapshot(snapshot, allow_notifications=True)
        await self._publish_tasks()

    async def start_watch(
        self,
        thread_id: str,
        mode: WatchMode,
    ) -> WatchRecord:
        """为当前活动任务启用监控。"""

        task = self.aggregator.get(thread_id)
        if task is None:
            raise KeyError(thread_id)
        watch = await self.monitoring.start_watch(task, mode)
        self.aggregator.set_watch(thread_id, monitored=True, mode=mode)
        await self._publish_tasks()
        return watch

    async def stop_watch(self, thread_id: str) -> None:
        """停止任务监控并更新任务卡片。"""

        await self.monitoring.stop_watch(thread_id)
        self.aggregator.set_watch(thread_id, monitored=False, mode=None)
        await self._publish_tasks()

    async def test_notification(self) -> str:
        """通过当前飞书配置显式发送测试消息。"""

        message = (
            "【Codex 任务监控器】测试消息\n"
            "飞书通知配置有效，后续受监控任务的状态变化将发送到这里。"
        )
        async with self._notifier_lock:
            return await self.notifier.send_text(message)

    async def retry_notification(self, notification_id: int) -> str:
        """显式重试一条已保存正文的失败通知。"""

        notification = self.repository.prepare_notification_retry(
            notification_id
        )
        if notification is None:
            raise KeyError(notification_id)
        dedupe_key = str(notification["dedupe_key"])
        message = str(notification["message"])
        try:
            async with self._notifier_lock:
                message_id = await self.notifier.send_text(message)
        except Exception as error:
            self.repository.mark_notification_failed(
                dedupe_key,
                str(error),
            )
            await self.publisher.publish(
                "notification",
                {
                    "dedupe_key": dedupe_key,
                    "state": "failed",
                    "error": str(error)[:500],
                },
            )
            raise
        self.repository.mark_notification_sent(dedupe_key, message_id)
        await self.publisher.publish(
            "notification",
            {
                "dedupe_key": dedupe_key,
                "state": "sent",
                "message_id": message_id,
            },
        )
        return message_id

    async def apply_config(self, changes: dict[str, Any]) -> None:
        """热应用无需重启的运行时配置。"""

        if "feishu" not in changes:
            return
        replacement = FeishuClient(self.config_service.load().feishu)
        async with self._notifier_lock:
            previous = self.notifier
            self.notifier = replacement
            await previous.close()

    def list_tasks(self) -> list[TaskSnapshot]:
        """返回带持久化监控标记的任务列表。"""

        tasks = self.aggregator.list_tasks()
        for task in tasks:
            watch = self.repository.get_watch(task.thread_id)
            self.aggregator.set_watch(
                task.thread_id,
                monitored=bool(watch and watch.active),
                mode=watch.mode if watch and watch.active else None,
            )
        return self.aggregator.list_tasks()

    def get_task(self, thread_id: str) -> TaskSnapshot | None:
        """返回指定任务。"""

        self.list_tasks()
        return self.aggregator.get(thread_id)

    async def _read_active_thread(self, fallback: TaskSnapshot) -> TaskSnapshot:
        """读取活动线程的 Turn 详情，失败时保留列表快照。"""

        try:
            result = await self.app_client.request(
                "thread/read",
                {"threadId": fallback.thread_id, "includeTurns": True},
            )
        except Exception:
            return fallback
        if not isinstance(result, dict) or not isinstance(result.get("thread"), dict):
            return fallback
        return map_thread(result["thread"])

    async def _accept_snapshot(
        self,
        snapshot: TaskSnapshot,
        *,
        allow_notifications: bool,
    ) -> None:
        """补全项目信息并交给聚合与监控层。"""

        info = await resolve_project_info(
            snapshot.cwd,
            {"branch": snapshot.branch} if snapshot.branch else None,
        )
        enriched = snapshot.model_copy(
            update={
                "project_name": info.project_name or snapshot.project_name,
                "cwd": info.cwd or snapshot.cwd,
                "branch": info.branch or snapshot.branch,
            }
        )
        merged = self.aggregator.apply_snapshot(enriched)
        await self._process_snapshot(
            merged,
            allow_notifications=allow_notifications,
        )

    async def _process_snapshot(
        self,
        snapshot: TaskSnapshot,
        *,
        allow_notifications: bool,
    ) -> None:
        """持久化快照并发送监控产生的通知。"""

        self.repository.save_snapshot(snapshot)
        if not allow_notifications:
            return
        events = await self.monitoring.apply(snapshot)
        config = self.config_service.load()
        for event in events:
            if not _notification_enabled(event.status, config.notifications):
                self.repository.mark_notification_failed(
                    event.dedupe_key,
                    "该状态通知已在配置中关闭",
                )
                continue
            message = format_notification(
                event,
                max_length=config.notifications.summary_max_length,
            )
            self.repository.update_notification_message(
                event.dedupe_key,
                message,
            )
            if not config.notifications.enabled:
                self.repository.mark_notification_failed(
                    event.dedupe_key,
                    "自动通知已关闭",
                )
                continue
            try:
                async with self._notifier_lock:
                    message_id = await self.notifier.send_text(message)
            except Exception as error:
                self.repository.mark_notification_failed(
                    event.dedupe_key,
                    str(error),
                )
                await self.publisher.publish(
                    "notification",
                    {
                        "dedupe_key": event.dedupe_key,
                        "state": "failed",
                        "error": str(error)[:500],
                    },
                )
            else:
                self.repository.mark_notification_sent(
                    event.dedupe_key,
                    message_id,
                )
                await self.publisher.publish(
                    "notification",
                    {
                        "dedupe_key": event.dedupe_key,
                        "state": "sent",
                        "message_id": message_id,
                    },
                )

    async def _refresh_loop(self) -> None:
        """按配置频率刷新 App Server 快照并负责重连。"""

        backoff = 1.0
        while not self._stop_event.is_set():
            config = self.config_service.load()
            try:
                if not self.app_client.connected:
                    await self.app_client.start()
                await self.refresh_once()
                backoff = 1.0
                delay = config.codex.refresh_interval_seconds
            except Exception as error:
                self._set_health("app_server", False, str(error))
                await self._publish_health()
                delay = min(30.0, backoff)
                backoff = min(30.0, backoff * 2)
            await _wait_or_stop(self._stop_event, delay)

    async def _observer_loop(self) -> None:
        """按配置频率读取本地会话增量。"""

        while not self._stop_event.is_set():
            try:
                await self.observe_once()
            except Exception as error:
                self._set_health("session_observer", False, str(error))
                await self._publish_health()
            delay = self.config_service.load().codex.refresh_interval_seconds
            await _wait_or_stop(self._stop_event, delay)

    async def _notification_loop(self) -> None:
        """持续消费 App Server 主动通知。"""

        while not self._stop_event.is_set():
            if not self.app_client.connected:
                await _wait_or_stop(self._stop_event, 1)
                continue
            try:
                message = await self.app_client.next_notification(timeout=1)
            except TimeoutError:
                continue
            except Exception as error:
                self._set_health("app_server", False, str(error))
                continue
            await self.handle_notification(message)

    async def _publish_tasks(self) -> None:
        """向 Web 层发布完整安全任务投影。"""

        await self.publisher.publish(
            "tasks",
            {
                "tasks": [
                    task.model_dump(mode="json")
                    for task in self.list_tasks()
                ]
            },
        )

    async def _publish_health(self) -> None:
        """向 Web 层发布数据源健康状态。"""

        await self.publisher.publish(
            "health",
            {
                "sources": {
                    name: health.model_dump(mode="json")
                    for name, health in self.health.items()
                }
            },
        )

    def _set_health(self, name: str, connected: bool, message: str) -> None:
        """更新单个数据源健康状态。"""

        self.health[name] = SourceHealth(
            name=name,
            connected=connected,
            message=message[:500],
        )


def _notification_enabled(status: TaskStatus, config: Any) -> bool:
    """按状态读取对应通知开关。"""

    mapping = {
        TaskStatus.COMPLETED: config.notify_completed,
        TaskStatus.FAILED: config.notify_failed,
        TaskStatus.INTERRUPTED: config.notify_interrupted,
        TaskStatus.WAITING_INPUT: config.notify_waiting_input,
        TaskStatus.WAITING_APPROVAL: config.notify_waiting_approval,
    }
    return bool(mapping.get(status, False))


def _should_include_snapshot(
    snapshot: TaskSnapshot,
    recent_cutoff: datetime,
) -> bool:
    """始终保留活动任务，只保留时间窗内的其他任务。"""

    if snapshot.status in ACTIVE_STATUSES:
        return True
    return snapshot.updated_at >= recent_cutoff


def _needs_thread_details(
    listed: TaskSnapshot,
    current: TaskSnapshot | None,
) -> bool:
    """判断列表快照是否需要通过线程详情补充权威状态。"""

    if listed.status in ACTIVE_STATUSES:
        return True
    return (
        listed.status is TaskStatus.UNKNOWN
        and current is not None
        and current.status in ACTIVE_STATUSES
    )


async def _wait_or_stop(stop_event: asyncio.Event, delay: float) -> None:
    """等待下一轮或在停止事件出现时立即返回。"""

    with contextlib.suppress(TimeoutError):
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
