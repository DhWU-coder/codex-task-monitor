from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
INSTALLER = PROJECT_ROOT / "install.sh"
REPOSITORY_URL = "https://github.com/DhWU-coder/codex-task-monitor.git"


def run_installer(
    tmp_path: Path,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["CODEX_TASK_MONITOR_INSTALL_DIR"] = str(tmp_path / "install")
    environment["CODEX_TASK_MONITOR_BIN_DIR"] = str(tmp_path / "bin")
    return subprocess.run(
        ["bash", str(INSTALLER), *arguments],
        cwd=PROJECT_ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dry_run_detects_local_repository(tmp_path: Path) -> None:
    result = run_installer(tmp_path, "--dry-run")

    assert result.returncode == 0
    assert "安装模式：本地仓库" in result.stdout
    assert f"源码目录：{PROJECT_ROOT}" in result.stdout
    assert f"全局命令：{tmp_path / 'bin' / 'codex-task-monitor'}" in result.stdout


def test_remote_dry_run_uses_configured_install_directory(tmp_path: Path) -> None:
    result = run_installer(tmp_path, "--remote", "--dry-run")

    assert result.returncode == 0
    assert "安装模式：远程安装" in result.stdout
    assert f"仓库地址：{REPOSITORY_URL}" in result.stdout
    assert f"源码目录：{tmp_path / 'install'}" in result.stdout


def test_installer_refuses_to_overwrite_regular_cli_file(tmp_path: Path) -> None:
    binary_directory = tmp_path / "bin"
    binary_directory.mkdir()
    (binary_directory / "codex-task-monitor").write_text(
        "用户已有命令",
        encoding="utf-8",
    )

    result = run_installer(tmp_path, "--dry-run")

    assert result.returncode != 0
    assert "拒绝覆盖已有的普通文件或目录" in result.stderr


def test_frontend_commands_run_inside_frontend_directory(tmp_path: Path) -> None:
    repository = tmp_path / "repository"
    frontend_directory = repository / "frontend"
    virtual_environment_bin = repository / ".venv" / "bin"
    fake_command_directory = tmp_path / "commands"
    outside_directory = tmp_path / "outside"
    for directory in (
        frontend_directory,
        virtual_environment_bin,
        fake_command_directory,
        outside_directory,
    ):
        directory.mkdir(parents=True)

    shutil.copy2(INSTALLER, repository / "install.sh")
    (repository / "pyproject.toml").write_text("", encoding="utf-8")
    (frontend_directory / "package.json").write_text("{}", encoding="utf-8")
    (frontend_directory / "package-lock.json").write_text("{}", encoding="utf-8")

    successful_command = "#!/usr/bin/env bash\nexit 0\n"
    for command_path in (
        virtual_environment_bin / "python",
        virtual_environment_bin / "codex-task-monitor",
        fake_command_directory / "python3",
    ):
        command_path.write_text(successful_command, encoding="utf-8")
        command_path.chmod(0o755)

    node_command = fake_command_directory / "node"
    node_command.write_text(
        "#!/usr/bin/env bash\nprintf 'v20.0.0\\n'\n",
        encoding="utf-8",
    )
    node_command.chmod(0o755)

    npm_log = tmp_path / "npm-working-directories.log"
    npm_command = fake_command_directory / "npm"
    npm_command.write_text(
        "#!/usr/bin/env bash\nprintf '%s\\n' \"$PWD\" >> \"$CODEX_TASK_MONITOR_NPM_PWD_LOG\"\n",
        encoding="utf-8",
    )
    npm_command.chmod(0o755)

    environment = os.environ.copy()
    environment["PATH"] = f"{fake_command_directory}:{environment['PATH']}"
    environment["CODEX_TASK_MONITOR_BIN_DIR"] = str(tmp_path / "bin")
    environment["CODEX_TASK_MONITOR_PYTHON"] = "python3"
    environment["CODEX_TASK_MONITOR_NPM_PWD_LOG"] = str(npm_log)
    result = subprocess.run(
        ["bash", str(repository / "install.sh")],
        cwd=outside_directory,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert npm_log.read_text(encoding="utf-8").splitlines() == [
        str(frontend_directory),
        str(frontend_directory),
    ]
