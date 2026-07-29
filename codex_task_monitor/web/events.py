"""供浏览器实时订阅的进程内事件广播器。"""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any


class EventBroker:
    """向所有 SSE 订阅者广播安全事件。"""

    def __init__(self, *, queue_size: int = 32) -> None:
        self._queue_size = queue_size
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()

    def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        """创建一个有界订阅队列。"""

        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=self._queue_size
        )
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[dict[str, Any]]) -> None:
        """移除订阅队列。"""

        self._subscribers.discard(queue)

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        """广播事件；慢客户端只保留最新的有限事件。"""

        event = {"type": event_type, "payload": payload}
        for queue in tuple(self._subscribers):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def stream(self) -> AsyncIterator[str]:
        """把内部事件转换成 SSE 数据帧。"""

        queue = self.subscribe()
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                payload = json.dumps(
                    event["payload"],
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                yield f"event: {event['type']}\ndata: {payload}\n\n"
        finally:
            self.unsubscribe(queue)
