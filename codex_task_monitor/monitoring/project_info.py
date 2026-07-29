"""项目名和 Git 分支的只读提取。"""

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from codex_task_monitor.models import ProjectInfo


async def _git_output(cwd: str, *arguments: str) -> str | None:
    """运行受限的只读 Git 命令并返回标准输出。"""

    try:
        process = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            cwd,
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        stdout, _ = await asyncio.wait_for(process.communicate(), timeout=1)
    except TimeoutError:
        process.kill()
        await process.wait()
        return None
    if process.returncode != 0:
        return None
    value = stdout.decode("utf-8", errors="replace").strip()
    return value or None


async def resolve_project_info(
    cwd: str | None,
    git_info: Mapping[str, Any] | None,
) -> ProjectInfo:
    """从线程元数据和只读 Git 查询解析项目名称与分支。"""

    if not cwd:
        return ProjectInfo()

    normalized_cwd = str(Path(cwd).expanduser())
    configured_branch = None
    if git_info:
        raw_branch = git_info.get("branch")
        if isinstance(raw_branch, str) and raw_branch.strip():
            configured_branch = raw_branch.strip()

    if configured_branch:
        return ProjectInfo(
            project_name=Path(normalized_cwd).name or normalized_cwd,
            cwd=normalized_cwd,
            branch=configured_branch,
        )

    git_root = await _git_output(normalized_cwd, "rev-parse", "--show-toplevel")
    branch = await _git_output(normalized_cwd, "branch", "--show-current") if git_root else None
    root_for_name = git_root or normalized_cwd
    return ProjectInfo(
        project_name=Path(root_for_name).name or root_for_name,
        cwd=normalized_cwd,
        branch=branch,
    )
