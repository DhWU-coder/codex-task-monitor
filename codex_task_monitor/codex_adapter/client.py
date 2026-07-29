"""基于 stdio JSONL 的 Codex App Server 客户端。"""

import asyncio
import contextlib
import json
import logging
from collections.abc import Sequence
from typing import Any

LOGGER = logging.getLogger(__name__)


class AppServerProtocolError(RuntimeError):
    """App Server 返回协议错误或异常退出。"""


class AppServerClient:
    """管理一个 App Server 子进程和并发 JSON-RPC 请求。"""

    def __init__(
        self,
        command: Sequence[str],
        *,
        request_timeout: float = 10,
        stdio_limit: int = 32 * 1024 * 1024,
    ) -> None:
        self.command = list(command)
        self.request_timeout = request_timeout
        self.stdio_limit = stdio_limit
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[Any]] = {}
        self._notifications: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1000)
        self._next_id = 1
        self._initialized = False
        self._stopping = False

    @property
    def connected(self) -> bool:
        """返回子进程是否仍可收发请求。"""

        return bool(
            self._process
            and self._process.returncode is None
            and self._initialized
        )

    @property
    def pending_request_count(self) -> int:
        """返回等待响应的请求数量。"""

        return len(self._pending)

    async def start(self) -> None:
        """启动子进程并完成协议握手。"""

        if self.connected:
            return
        if not self.command:
            raise ValueError("App Server 命令不能为空")
        self._stopping = False
        self._initialized = False
        self._process = await asyncio.create_subprocess_exec(
            *self.command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self.stdio_limit,
        )
        self._reader_task = asyncio.create_task(self._read_stdout())
        self._stderr_task = asyncio.create_task(self._read_stderr())
        await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex_task_monitor",
                    "title": "Codex Task Monitor",
                    "version": "0.1.0",
                }
            },
        )
        await self.notify("initialized", {})
        self._initialized = True

    async def stop(self) -> None:
        """优雅停止子进程并清理异步任务。"""

        process = self._process
        if process is None:
            self._initialized = False
            return
        self._stopping = True
        self._initialized = False
        if process.stdin and not process.stdin.is_closing():
            process.stdin.close()
            with contextlib.suppress(BrokenPipeError, ConnectionResetError):
                await process.stdin.wait_closed()
        if process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except TimeoutError:
                process.terminate()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(process.wait(), timeout=1)
        await self._cancel_task(self._reader_task)
        await self._cancel_task(self._stderr_task)
        self._fail_pending(AppServerProtocolError("App Server 已停止"))
        self._process = None
        self._reader_task = None
        self._stderr_task = None

    async def request(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """发送已初始化连接上的请求。"""

        if not self.connected:
            raise AppServerProtocolError("App Server 尚未初始化")
        return await self._request(method, params or {})

    async def notify(
        self,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        """发送无需响应的客户端通知。"""

        await self._write({"method": method, "params": params or {}})

    async def next_notification(
        self,
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """读取下一条服务器通知。"""

        if timeout is None:
            return await self._notifications.get()
        return await asyncio.wait_for(self._notifications.get(), timeout)

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        """发送请求并按 ID 等待响应。"""

        request_id = self._next_id
        self._next_id += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending[request_id] = future
        try:
            await self._write(
                {
                    "id": request_id,
                    "method": method,
                    "params": params,
                }
            )
            return await asyncio.wait_for(future, timeout=self.request_timeout)
        finally:
            self._pending.pop(request_id, None)

    async def _write(self, message: dict[str, Any]) -> None:
        """把一条 JSONL 消息写入子进程标准输入。"""

        process = self._process
        if not process or not process.stdin or process.returncode is not None:
            raise AppServerProtocolError("App Server 连接不可用")
        process.stdin.write(
            f"{json.dumps(message, ensure_ascii=False, separators=(',', ':'))}\n".encode()
        )
        try:
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError) as error:
            raise AppServerProtocolError("App Server 连接已断开") from error

    async def _read_stdout(self) -> None:
        """持续读取响应与通知。"""

        process = self._process
        if not process or not process.stdout:
            return
        try:
            while raw_line := await process.stdout.readline():
                try:
                    message = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    LOGGER.warning("忽略 App Server 的无效 JSONL 输出")
                    continue
                if not isinstance(message, dict):
                    continue
                request_id = message.get("id")
                if isinstance(request_id, int):
                    self._resolve_response(request_id, message)
                elif isinstance(message.get("method"), str):
                    self._publish_notification(message)
        except (OSError, ValueError) as error:
            LOGGER.warning("App Server 输出流读取失败：%s", error)
        finally:
            if not self._stopping:
                self._initialized = False
                self._fail_pending(AppServerProtocolError("App Server 意外退出"))

    async def _read_stderr(self) -> None:
        """排空 stderr，避免子进程因缓冲区阻塞。"""

        process = self._process
        if not process or not process.stderr:
            return
        while raw_line := await process.stderr.readline():
            message = raw_line.decode("utf-8", errors="replace").strip()
            if message:
                LOGGER.debug("App Server stderr: %s", message[:500])

    def _resolve_response(self, request_id: int, message: dict[str, Any]) -> None:
        """将响应交付给对应的等待 Future。"""

        future = self._pending.get(request_id)
        if not future or future.done():
            return
        error = message.get("error")
        if isinstance(error, dict):
            future.set_exception(
                AppServerProtocolError(
                    f"App Server 请求失败：{error.get('message', '未知错误')}"
                )
            )
            return
        future.set_result(message.get("result"))

    def _publish_notification(self, message: dict[str, Any]) -> None:
        """把服务器通知放入有界队列。"""

        if self._notifications.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._notifications.get_nowait()
        self._notifications.put_nowait(message)

    def _fail_pending(self, error: Exception) -> None:
        """让所有未完成请求以同一个连接错误结束。"""

        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)

    @staticmethod
    async def _cancel_task(task: asyncio.Task[None] | None) -> None:
        """取消并等待后台读取任务。"""

        if task is None or task.done():
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
