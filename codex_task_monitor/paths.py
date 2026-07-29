"""应用文件路径解析。"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def resolve_config_path() -> Path:
    """返回不依赖终端当前目录的配置文件路径。"""

    configured = os.environ.get("CODEX_TASK_MONITOR_CONFIG")
    if configured:
        return Path(configured).expanduser().resolve()
    return (PROJECT_ROOT / "config.yaml").resolve()


def data_directory(config_path: Path | None = None) -> Path:
    """返回有效配置文件旁的数据目录。"""

    path = config_path or resolve_config_path()
    return path.parent / "data"


def database_path(config_path: Path | None = None) -> Path:
    """返回 SQLite 数据库路径。"""

    return data_directory(config_path) / "monitor.db"


def runtime_state_path(config_path: Path | None = None) -> Path:
    """返回后台服务运行状态文件路径。"""

    return data_directory(config_path) / "runtime.json"


def log_path(config_path: Path | None = None) -> Path:
    """返回后台服务日志路径。"""

    return data_directory(config_path) / "codex-task-monitor.log"


def codex_sessions_directory() -> Path:
    """返回 Codex 本地会话的默认只读目录。"""

    codex_home = os.environ.get("CODEX_HOME")
    root = (
        Path(codex_home).expanduser()
        if codex_home
        else Path.home() / ".codex"
    )
    return (root / "sessions").resolve()
