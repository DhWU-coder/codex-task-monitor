import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from codex_task_monitor.config.service import ConfigService


class FakeProcess:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs
        self.pid = 43210

    def poll(self) -> None:
        return None


def _config(tmp_path: Path, *, port: int = 6664) -> ConfigService:
    service = ConfigService(tmp_path / "config.yaml")
    service.create_default()
    if port != 6664:
        service.update_from_public({"server": {"port": port}})
    return service


def test_run_prints_default_ui_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli

    service = _config(tmp_path)
    monkeypatch.setenv("CODEX_TASK_MONITOR_CONFIG", str(service.path))
    called: list[Path] = []
    monkeypatch.setattr(
        cli,
        "_run_foreground",
        lambda config_service: called.append(config_service.path),
    )

    result = CliRunner().invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert "UI 地址：http://127.0.0.1:6664" in result.stdout
    assert called == [service.path]


def test_run_uses_configured_port(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli

    service = _config(tmp_path, port=6670)
    monkeypatch.setenv("CODEX_TASK_MONITOR_CONFIG", str(service.path))
    monkeypatch.setattr(cli, "_run_foreground", lambda _: None)

    result = CliRunner().invoke(cli.app, ["run"])

    assert result.exit_code == 0
    assert "UI 地址：http://127.0.0.1:6670" in result.stdout


def test_start_waits_for_health_and_writes_private_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli
    from codex_task_monitor.paths import runtime_state_path

    service = _config(tmp_path)
    health_checks: list[tuple[str, float]] = []
    monkeypatch.setattr(cli, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(
        cli,
        "_wait_for_health",
        lambda url, _process, timeout: health_checks.append((url, timeout))
        or True,
    )

    result = cli._start_background(service)
    state = json.loads(runtime_state_path(service.path).read_text())

    assert result.url == "http://127.0.0.1:6664"
    assert result.already_running is False
    assert health_checks == [("http://127.0.0.1:6664/healthz", 30)]
    assert state["pid"] == 43210
    assert state["config_path"] == str(service.path)


def test_repeated_start_does_not_spawn_second_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli

    service = _config(tmp_path)
    monkeypatch.setattr(cli, "_port_available", lambda _host, _port: True)
    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(cli, "_wait_for_health", lambda *_: True)
    first = cli._start_background(service)
    monkeypatch.setattr(cli, "_process_alive", lambda _pid: True)
    monkeypatch.setattr(cli, "_process_is_monitor", lambda _pid: True)
    spawned = 0

    def count_spawn(*args: Any, **kwargs: Any) -> FakeProcess:
        nonlocal spawned
        spawned += 1
        return FakeProcess(*args, **kwargs)

    monkeypatch.setattr(cli.subprocess, "Popen", count_spawn)

    second = cli._start_background(service)

    assert first.already_running is False
    assert second.already_running is True
    assert spawned == 0


def test_start_waits_briefly_for_recently_released_port(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli

    service = _config(tmp_path)
    checks = iter([False, False, True])
    monkeypatch.setattr(
        cli,
        "_port_available",
        lambda _host, _port: next(checks),
    )
    monkeypatch.setattr(cli.time, "sleep", lambda _delay: None)
    monkeypatch.setattr(cli.subprocess, "Popen", FakeProcess)
    monkeypatch.setattr(cli, "_wait_for_health", lambda *_: True)

    result = cli._start_background(service)

    assert result.already_running is False


def test_stop_cleans_stale_pid_without_signalling(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli
    from codex_task_monitor.paths import runtime_state_path

    service = _config(tmp_path)
    state_path = runtime_state_path(service.path)
    state_path.parent.mkdir(mode=0o700)
    state_path.write_text(
        json.dumps({"pid": 99999, "url": "http://127.0.0.1:6664"})
    )
    monkeypatch.setattr(cli, "_process_alive", lambda _pid: False)
    signals: list[tuple[int, int]] = []
    monkeypatch.setattr(
        cli.os,
        "kill",
        lambda pid, signal_number: signals.append((pid, signal_number)),
    )

    result = cli._stop_background(service)

    assert result.stopped is False
    assert "陈旧" in result.message
    assert not state_path.exists()
    assert signals == []


def test_restart_calls_stop_then_start(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor import cli

    service = _config(tmp_path)
    monkeypatch.setenv("CODEX_TASK_MONITOR_CONFIG", str(service.path))
    order: list[str] = []
    monkeypatch.setattr(
        cli,
        "_stop_background",
        lambda _service: order.append("stop")
        or cli.StopResult(False, "服务未运行"),
    )
    monkeypatch.setattr(
        cli,
        "_start_background",
        lambda _service: order.append("start")
        or cli.StartResult("http://127.0.0.1:6664", False),
    )

    result = CliRunner().invoke(cli.app, ["restart"])

    assert result.exit_code == 0
    assert order == ["stop", "start"]
    assert "UI 地址：http://127.0.0.1:6664" in result.stdout


def test_config_path_is_stable_across_current_directories(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from codex_task_monitor.paths import resolve_config_path

    service = _config(tmp_path)
    monkeypatch.setenv("CODEX_TASK_MONITOR_CONFIG", str(service.path))
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)

    assert resolve_config_path() == service.path
