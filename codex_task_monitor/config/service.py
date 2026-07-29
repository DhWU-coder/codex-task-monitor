"""YAML 配置文件的安全读写。"""

import os
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from codex_task_monitor.config.models import AppConfig


def _merge_dict(base: dict[str, Any], changes: Mapping[str, Any]) -> dict[str, Any]:
    """递归合并配置映射并返回新字典。"""

    result = dict(base)
    for key, value in changes.items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


class ConfigService:
    """负责验证、遮罩和原子保存应用配置。"""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()

    def create_default(self) -> AppConfig:
        """当配置不存在时创建默认配置。"""

        if self.path.exists():
            return self.load()
        config = AppConfig()
        self.save(config)
        return config

    def load(self) -> AppConfig:
        """读取并验证当前配置。"""

        if not self.path.exists():
            return self.create_default()
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        return AppConfig.model_validate(raw)

    def save(self, config: AppConfig) -> None:
        """将完整配置原子写入磁盘。"""

        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = yaml.safe_dump(
            config.model_dump(mode="json"),
            allow_unicode=True,
            sort_keys=False,
        )
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            dir=self.path.parent,
            text=True,
        )
        temporary_path = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if temporary_path.exists():
                temporary_path.unlink()

    def update_from_public(self, changes: Mapping[str, Any]) -> AppConfig:
        """应用来自 UI 的局部配置，并保护已有密钥。"""

        current = self.load()
        current_data = current.model_dump(mode="python")
        sanitized_changes = {
            key: dict(value) if isinstance(value, Mapping) else value
            for key, value in changes.items()
        }
        feishu_changes = sanitized_changes.get("feishu")
        if isinstance(feishu_changes, dict):
            clear_secret = bool(feishu_changes.pop("clear_app_secret", False))
            if clear_secret:
                feishu_changes["app_secret"] = ""
            elif not feishu_changes.get("app_secret"):
                feishu_changes.pop("app_secret", None)
            feishu_changes.pop("app_secret_configured", None)
        updated = AppConfig.model_validate(_merge_dict(current_data, sanitized_changes))
        self.save(updated)
        return updated

    def to_public_dict(self) -> dict[str, Any]:
        """返回不会暴露完整密钥的配置投影。"""

        config = self.load()
        public = config.model_dump(mode="json")
        public["feishu"]["app_secret_configured"] = bool(config.feishu.app_secret)
        public["feishu"]["app_secret"] = ""
        return public
