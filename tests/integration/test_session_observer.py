from pathlib import Path

import pytest

from codex_task_monitor.models import TaskStatus

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sessions"


def _copy_running_session(target: Path) -> None:
    target.parent.mkdir(parents=True)
    target.write_bytes((FIXTURES / "running.jsonl").read_bytes())


@pytest.mark.asyncio
async def test_bootstrap_finds_running_task_as_baseline(tmp_path: Path) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "2026" / "07" / "rollout.jsonl"
    _copy_running_session(session_file)
    observer = SessionObserver(tmp_path / "sessions")

    events = await observer.scan_once()

    running = [event for event in events if event.status is TaskStatus.RUNNING]
    assert len(running) == 1
    assert running[0].thread_id == "thread-test"
    assert running[0].baseline is True


@pytest.mark.asyncio
async def test_incremental_completion_is_not_baseline(tmp_path: Path) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    _copy_running_session(session_file)
    observer = SessionObserver(tmp_path / "sessions")
    await observer.scan_once()

    with session_file.open("ab") as stream:
        stream.write((FIXTURES / "completed-line.jsonl").read_bytes())
    events = await observer.scan_once()
    repeated = await observer.scan_once()

    completed = [event for event in events if event.status is TaskStatus.COMPLETED]
    assert len(completed) == 1
    assert completed[0].baseline is False
    assert repeated == []


@pytest.mark.asyncio
async def test_partial_line_waits_for_remaining_bytes(tmp_path: Path) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    _copy_running_session(session_file)
    observer = SessionObserver(tmp_path / "sessions")
    await observer.scan_once()
    completed = (FIXTURES / "completed-line.jsonl").read_bytes()
    midpoint = len(completed) // 2

    with session_file.open("ab") as stream:
        stream.write(completed[:midpoint])
    first = await observer.scan_once()
    with session_file.open("ab") as stream:
        stream.write(completed[midpoint:])
    second = await observer.scan_once()

    assert first == []
    assert [event.status for event in second] == [TaskStatus.COMPLETED]


@pytest.mark.asyncio
async def test_replaced_file_creates_new_baseline(tmp_path: Path) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    _copy_running_session(session_file)
    observer = SessionObserver(tmp_path / "sessions")
    await observer.scan_once()

    replacement = (FIXTURES / "running.jsonl").read_bytes()
    session_file.unlink()
    session_file.write_bytes(replacement)
    events = await observer.scan_once()

    assert events
    assert all(event.baseline for event in events)
