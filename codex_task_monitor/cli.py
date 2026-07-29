"""Codex 任务监控器命令行生命周期管理。"""

import json
import os
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
import uvicorn

from codex_task_monitor.codex_adapter.client import AppServerClient
from codex_task_monitor.config.service import ConfigService
from codex_task_monitor.notifications.feishu import FeishuClient
from codex_task_monitor.paths import (
    codex_sessions_directory,
    data_directory,
    database_path,
    log_path,
    resolve_config_path,
    runtime_state_path,
)
from codex_task_monitor.runtime import RuntimeService
from codex_task_monitor.session_observer.observer import SessionObserver
from codex_task_monitor.storage.database import Database
from codex_task_monitor.storage.repository import Repository
from codex_task_monitor.web.app import create_app

app = typer.Typer(
    help="监控本机 Codex 任务并发送飞书通知。",
    no_args_is_help=True,
)


@dataclass(frozen=True)
class StartResult:
    """后台启动结果。"""

    url: str
    already_running: bool


@dataclass(frozen=True)
class StopResult:
    """后台停止结果。"""

    stopped: bool
    message: str


@app.command("run")
def run_command() -> None:
    """在前台运行监控器。"""

    service = _load_config_service()
    typer.echo(f"UI 地址：{_ui_url(service)}")
    _run_foreground(service)


@app.command("start")
def start_command() -> None:
    """在后台启动监控器。"""

    service = _load_config_service()
    try:
        result = _start_background(service)
    except RuntimeError as error:
        typer.echo(f"启动失败：{error}", err=True)
        raise typer.Exit(code=1) from error
    if result.already_running:
        typer.echo("监控器已在运行。")
    typer.echo(f"UI 地址：{result.url}")


@app.command("stop")
def stop_command() -> None:
    """停止后台监控器。"""

    service = _load_config_service()
    result = _stop_background(service)
    typer.echo(result.message)


@app.command("restart")
def restart_command() -> None:
    """重启后台监控器。"""

    service = _load_config_service()
    _stop_background(service)
    try:
        result = _start_background(service)
    except RuntimeError as error:
        typer.echo(f"重启失败：{error}", err=True)
        raise typer.Exit(code=1) from error
    typer.echo(f"UI 地址：{result.url}")


@app.command("_serve", hidden=True)
def serve_command() -> None:
    """供 start 启动的内部前台服务命令。"""

    _run_foreground(_load_config_service())


def _load_config_service() -> ConfigService:
    """解析稳定配置路径并确保默认文件存在。"""

    service = ConfigService(resolve_config_path())
    service.create_default()
    return service


def _ui_url(service: ConfigService) -> str:
    """按配置生成可在浏览器打开的 UI 地址。"""

    config = service.load().server
    host = f"[{config.host}]" if config.host == "::1" else config.host
    return f"http://{host}:{config.port}"


def _build_runtime(service: ConfigService) -> RuntimeService:
    """创建生产环境使用的运行时依赖。"""

    config = service.load()
    database = Database(database_path(service.path))
    database.initialize()
    command = shlex.split(config.codex.command)
    if not command:
        raise RuntimeError("codex.command 不能为空")
    if command[-1] != "app-server":
        command.append("app-server")
    return RuntimeService(
        config_service=service,
        repository=Repository(database),
        app_client=AppServerClient(command),
        observer=SessionObserver(codex_sessions_directory()),
        notifier=FeishuClient(config.feishu),
    )


def _run_foreground(service: ConfigService) -> None:
    """构建应用并交给 Uvicorn 阻塞运行。"""

    config = service.load()
    web_app = create_app(
        runtime=_build_runtime(service),
        config_service=service,
    )
    uvicorn.run(
        web_app,
        host=config.server.host,
        port=config.server.port,
        log_level="info",
    )


def _start_background(
    service: ConfigService,
    timeout_seconds: float = 30,
) -> StartResult:
    """启动独立后台进程并等待健康检查通过。"""

    url = _ui_url(service)
    state_path = runtime_state_path(service.path)
    state = _read_runtime_state(state_path)
    if state:
        pid = state.get("pid")
        if (
            isinstance(pid, int)
            and _process_alive(pid)
            and _process_is_monitor(pid)
        ):
            existing_url = state.get("url")
            return StartResult(
                str(existing_url) if existing_url else url,
                True,
            )
        state_path.unlink(missing_ok=True)

    server = service.load().server
    if not _wait_for_port_available(server.host, server.port):
        raise RuntimeError(
            f"端口 {server.port} 已被占用；配置文件：{service.path}"
        )

    directory = data_directory(service.path)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    output_path = log_path(service.path)
    environment = os.environ.copy()
    environment["CODEX_TASK_MONITOR_CONFIG"] = str(service.path)
    with output_path.open("a", encoding="utf-8") as output:
        os.chmod(output_path, 0o600)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "codex_task_monitor.cli",
                "_serve",
            ],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
            env=environment,
        )
    _write_runtime_state(
        state_path,
        {
            "pid": process.pid,
            "started_at": datetime.now(UTC).isoformat(),
            "config_path": str(service.path),
            "url": url,
        },
    )
    if not _wait_for_health(
        f"{url}/healthz",
        process,
        timeout_seconds,
    ):
        if process.poll() is None:
            os.kill(process.pid, signal.SIGTERM)
        state_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"健康检查未通过；请查看日志：{output_path}"
        )
    return StartResult(url, False)


def _stop_background(
    service: ConfigService,
    timeout_seconds: float = 8,
) -> StopResult:
    """验证后台进程身份后优雅停止。"""

    state_path = runtime_state_path(service.path)
    state = _read_runtime_state(state_path)
    if not state:
        state_path.unlink(missing_ok=True)
        return StopResult(False, "服务未运行。")
    pid = state.get("pid")
    if not isinstance(pid, int) or not _process_alive(pid):
        state_path.unlink(missing_ok=True)
        return StopResult(False, "已清理陈旧运行状态，服务未运行。")
    if not _process_is_monitor(pid):
        state_path.unlink(missing_ok=True)
        return StopResult(
            False,
            "运行状态已失效，未终止其他进程。",
        )

    os.kill(pid, signal.SIGTERM)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline and _process_alive(pid):
        time.sleep(0.1)
    if _process_alive(pid) and _process_is_monitor(pid):
        os.kill(pid, signal.SIGKILL)
    state_path.unlink(missing_ok=True)
    return StopResult(True, "监控器已停止。")


def _read_runtime_state(path: Path) -> dict[str, Any] | None:
    """安全读取后台运行状态。"""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_runtime_state(path: Path, state: dict[str, Any]) -> None:
    """原子保存后台运行状态并限制文件权限。"""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(state, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def _process_alive(pid: int) -> bool:
    """通过信号零检查进程是否存在。"""

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _process_is_monitor(pid: int) -> bool:
    """使用系统进程命令校验目标是否为本工具内部服务。"""

    try:
        result = subprocess.run(
            ["ps", "-p", str(pid), "-o", "command="],
            capture_output=True,
            text=True,
            timeout=1,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    command = result.stdout
    return (
        result.returncode == 0
        and "codex_task_monitor.cli" in command
        and "_serve" in command
    )


def _port_available(host: str, port: int) -> bool:
    """尝试绑定配置地址以检查端口是否可用。"""

    try:
        addresses = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror:
        return False
    for family, socket_type, protocol, _, address in addresses:
        probe = socket.socket(family, socket_type, protocol)
        try:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(address)
        except OSError:
            continue
        finally:
            probe.close()
        return True
    return False


def _wait_for_port_available(
    host: str,
    port: int,
    *,
    attempts: int = 20,
    delay: float = 0.1,
) -> bool:
    """短时等待刚停止的服务释放监听端口。"""

    for attempt in range(attempts):
        if _port_available(host, port):
            return True
        if attempt < attempts - 1:
            time.sleep(delay)
    return False


def _wait_for_health(
    url: str,
    process: subprocess.Popen[Any],
    timeout_seconds: float,
) -> bool:
    """轮询健康接口，子进程退出时提前失败。"""

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(url, timeout=0.5) as response:
                if response.status == 200:
                    payload = json.loads(response.read())
                    if payload.get("status") == "ok":
                        return True
        except (
            OSError,
            ValueError,
            urllib.error.URLError,
        ):
            pass
        time.sleep(0.1)
    return False


if __name__ == "__main__":
    app()
