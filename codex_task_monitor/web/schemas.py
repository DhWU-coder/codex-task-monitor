"""Web API 的请求模型。"""

from pydantic import BaseModel, ConfigDict

from codex_task_monitor.models import WatchMode


class ApiRequest(BaseModel):
    """拒绝多余字段的 API 请求基类。"""

    model_config = ConfigDict(extra="forbid")


class WatchRequest(ApiRequest):
    """启动监控时选择的模式。"""

    mode: WatchMode
