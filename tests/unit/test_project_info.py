from pathlib import Path

import pytest


@pytest.mark.asyncio
async def test_uses_thread_git_info_before_running_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_task_monitor.monitoring import project_info

    async def fail_if_called(*args: object) -> str | None:
        raise AssertionError("已有分支信息时不应调用 Git")

    monkeypatch.setattr(project_info, "_git_output", fail_if_called)

    info = await project_info.resolve_project_info(
        "/work/repo",
        {"branch": "feature/x"},
    )

    assert info.branch == "feature/x"
    assert info.project_name == "repo"


@pytest.mark.asyncio
async def test_non_git_directory_uses_directory_name(tmp_path: Path) -> None:
    from codex_task_monitor.monitoring.project_info import resolve_project_info

    info = await resolve_project_info(str(tmp_path), None)

    assert info.project_name == tmp_path.name
    assert info.cwd == str(tmp_path)
    assert info.branch is None


@pytest.mark.asyncio
async def test_git_root_name_and_branch_are_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from codex_task_monitor.monitoring import project_info

    outputs = iter(["/work/actual-repo", "main"])

    async def fake_git_output(*args: object) -> str | None:
        return next(outputs)

    monkeypatch.setattr(project_info, "_git_output", fake_git_output)

    info = await project_info.resolve_project_info("/work/repo/subdir", None)

    assert info.project_name == "actual-repo"
    assert info.branch == "main"


@pytest.mark.asyncio
async def test_missing_working_directory_returns_empty_info() -> None:
    from codex_task_monitor.monitoring.project_info import resolve_project_info

    info = await resolve_project_info(None, None)

    assert info.project_name is None
    assert info.cwd is None
    assert info.branch is None
