import os
import stat
from pathlib import Path

import pytest
from pydantic import ValidationError


def _service(config_path: Path):
    from codex_task_monitor.config.service import ConfigService

    return ConfigService(config_path)


def test_default_port_is_6664(config_path: Path) -> None:
    service = _service(config_path)
    service.create_default()

    assert service.load().server.port == 6664


def test_default_feishu_recipient_type_is_email(config_path: Path) -> None:
    service = _service(config_path)

    config = service.create_default()

    assert config.feishu.receive_id_type == "email"


def test_default_orphaned_running_timeout_is_60_minutes(
    config_path: Path,
) -> None:
    service = _service(config_path)

    config = service.create_default()

    assert config.codex.orphaned_running_timeout_minutes == 60


def test_rejects_orphaned_running_timeout_below_five_minutes(
    config_path: Path,
) -> None:
    service = _service(config_path)
    service.create_default()

    with pytest.raises(ValidationError):
        service.update_from_public(
            {"codex": {"orphaned_running_timeout_minutes": 4}}
        )


def test_masked_config_never_exposes_app_secret(config_path: Path) -> None:
    service = _service(config_path)
    service.create_default()
    service.update_from_public(
        {
            "feishu": {
                "app_id": "cli_test",
                "app_secret": "secret-test",
                "receive_id": "ou_test",
                "receive_id_type": "open_id",
            }
        }
    )

    masked = service.to_public_dict()

    assert masked["feishu"]["app_secret"] == ""
    assert masked["feishu"]["app_secret_configured"] is True
    assert masked["feishu"]["receive_id_type"] == "open_id"
    assert "secret-test" not in repr(masked)


def test_blank_secret_keeps_existing_value(config_path: Path) -> None:
    service = _service(config_path)
    service.create_default()
    service.update_from_public({"feishu": {"app_secret": "secret-test"}})

    service.update_from_public({"feishu": {"app_secret": ""}})

    assert service.load().feishu.app_secret == "secret-test"


def test_explicit_clear_removes_secret(config_path: Path) -> None:
    service = _service(config_path)
    service.create_default()
    service.update_from_public({"feishu": {"app_secret": "secret-test"}})

    service.update_from_public(
        {"feishu": {"app_secret": "", "clear_app_secret": True}}
    )

    assert service.load().feishu.app_secret == ""


def test_rejects_non_loopback_host(config_path: Path) -> None:
    service = _service(config_path)
    service.create_default()

    with pytest.raises(ValidationError):
        service.update_from_public({"server": {"host": "0.0.0.0"}})


@pytest.mark.skipif(os.name == "nt", reason="Windows 不支持 POSIX 权限位")
def test_saved_config_is_owner_only(config_path: Path) -> None:
    service = _service(config_path)
    service.create_default()

    mode = stat.S_IMODE(config_path.stat().st_mode)

    assert mode == 0o600


def test_environment_config_path_is_stable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from codex_task_monitor.paths import resolve_config_path

    expected = (tmp_path / "custom.yaml").resolve()
    monkeypatch.setenv("CODEX_TASK_MONITOR_CONFIG", str(expected))
    monkeypatch.chdir(tmp_path.parent)

    assert resolve_config_path() == expected
