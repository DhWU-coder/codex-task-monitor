"""跨模块使用的领域模型。"""

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TaskStatus(StrEnum):
    """归一化任务状态。"""

    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_INPUT = "waiting_input"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    MANUALLY_COMPLETED = "manually_completed"
    UNKNOWN = "unknown"
    SOURCE_ERROR = "source_error"


class WatchMode(StrEnum):
    """用户可选择的监控模式。"""

    CURRENT_TURN = "current_turn"
    PERSISTENT = "persistent"


class SourceKind(StrEnum):
    """任务状态的数据来源。"""

    APP_SERVER = "app_server"
    SESSION = "session"
    MERGED = "merged"


class DomainModel(BaseModel):
    """不可变领域模型基类。"""

    model_config = ConfigDict(frozen=True)


class ProjectInfo(DomainModel):
    """任务所属项目的安全投影。"""

    project_name: str | None = None
    cwd: str | None = None
    branch: str | None = None


class TurnSnapshot(DomainModel):
    """单个 Codex Turn 的状态快照。"""

    turn_id: str
    status: TaskStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    latest_summary: str = ""
    error_summary: str = ""


class TaskSnapshot(DomainModel):
    """用于 UI 和监控决策的任务快照。"""

    thread_id: str
    turn_id: str | None = None
    title: str
    status: TaskStatus
    source: SourceKind = SourceKind.MERGED
    project_name: str | None = None
    cwd: str | None = None
    branch: str | None = None
    source_label: str = "Codex"
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latest_summary: str = ""
    waiting_reason: str = ""
    request_id: str | None = None
    error_summary: str = ""
    monitored: bool = False
    watch_mode: WatchMode | None = None


class WatchRecord(DomainModel):
    """持久化的任务监控选择。"""

    thread_id: str
    mode: WatchMode
    turn_id: str | None = None
    baseline_status: TaskStatus | None = None
    active: bool = True
    created_at: datetime
    updated_at: datetime


class ManualCompletionRecord(DomainModel):
    """用户手动结束某个任务轮次的持久化记录。"""

    thread_id: str
    turn_id: str | None = None
    started_at: datetime | None = None
    marked_at: datetime


class NotificationEvent(DomainModel):
    """准备发送给通知通道的领域事件。"""

    dedupe_key: str
    thread_id: str
    turn_id: str | None
    status: TaskStatus
    title: str
    project_name: str | None = None
    cwd: str | None = None
    branch: str | None = None
    duration_seconds: float | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    summary: str = ""
    waiting_reason: str = ""
    error_summary: str = ""


class SourceHealth(DomainModel):
    """单个数据源的连接健康状态。"""

    name: str
    connected: bool
    message: str = ""
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class SourceEvent(DomainModel):
    """适配器交给聚合器的标准化事件。"""

    source: SourceKind
    thread_id: str
    parent_thread_id: str | None = None
    turn_id: str | None = None
    title: str | None = None
    status: TaskStatus | None = None
    cwd: str | None = None
    branch: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    latest_summary: str | None = None
    waiting_reason: str | None = None
    request_id: str | None = None
    error_summary: str | None = None
    authoritative: bool = False
    baseline: bool = False
