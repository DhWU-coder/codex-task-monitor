"""应用配置的数据模型。"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictConfigModel(BaseModel):
    """拒绝未声明字段的配置基类。"""

    model_config = ConfigDict(extra="forbid")


class ServerConfig(StrictConfigModel):
    """本地 Web 服务配置。"""

    host: Literal["127.0.0.1", "localhost", "::1"] = "127.0.0.1"
    port: int = Field(default=6664, ge=1024, le=65535)


class CodexConfig(StrictConfigModel):
    """Codex 数据采集配置。"""

    command: str = "codex"
    refresh_interval_seconds: float = Field(default=2, gt=0, le=60)
    reconcile_interval_seconds: float = Field(default=30, gt=0, le=3600)
    recent_completed_hours: int = Field(default=24, ge=1, le=720)


class FeishuConfig(StrictConfigModel):
    """飞书自建应用配置。"""

    app_id: str = ""
    app_secret: str = ""
    receive_id: str = ""
    receive_id_type: Literal["open_id", "union_id", "user_id", "email"] = "open_id"


class NotificationConfig(StrictConfigModel):
    """通知事件开关配置。"""

    enabled: bool = True
    summary_max_length: int = Field(default=500, ge=50, le=4000)
    notify_completed: bool = True
    notify_failed: bool = True
    notify_interrupted: bool = True
    notify_waiting_input: bool = True
    notify_waiting_approval: bool = True


class AppConfig(StrictConfigModel):
    """完整应用配置。"""

    server: ServerConfig = Field(default_factory=ServerConfig)
    codex: CodexConfig = Field(default_factory=CodexConfig)
    feishu: FeishuConfig = Field(default_factory=FeishuConfig)
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)
