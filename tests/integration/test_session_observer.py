import json
from pathlib import Path

import pytest

from codex_task_monitor.models import TaskStatus

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sessions"


def _json_line(record: dict[str, object]) -> bytes:
    """把测试记录编码为一行 JSONL。"""

    return json.dumps(record).encode() + b"\n"


def _copy_running_session(target: Path) -> None:
    target.parent.mkdir(parents=True)
    target.write_bytes((FIXTURES / "running.jsonl").read_bytes())


def _session_metadata_line(
    thread_id: str,
    parent_thread_id: str | None,
) -> bytes:
    """构造足以跨过旧版六十四 KB 启动头的会话元数据。"""

    payload: dict[str, object] = {
        "id": thread_id,
        "cwd": "/workspace/lineage-project",
        "padding": "x" * 40_000,
    }
    if parent_thread_id:
        payload["forked_from_id"] = parent_thread_id
    return (
        json.dumps(
            {
                "timestamp": "2026-07-29T10:00:00Z",
                "type": "session_meta",
                "payload": payload,
            }
        ).encode()
        + b"\n"
    )


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
async def test_bootstrap_ignores_replayed_lineage_metadata_beyond_64k_head(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_bytes(
        b"".join(
            [
                _session_metadata_line("thread-c", "thread-b"),
                _session_metadata_line("thread-b", "thread-a"),
                _session_metadata_line("thread-a", None),
            ]
        )
    )
    observer = SessionObserver(
        tmp_path / "sessions",
        bootstrap_tail_bytes=64,
    )

    events = await observer.scan_once()

    lineage = {
        (event.thread_id, event.parent_thread_id)
        for event in events
        if event.parent_thread_id
    }
    assert lineage == {("thread-c", "thread-b")}
    assert all(event.thread_id == "thread-c" for event in events)


@pytest.mark.asyncio
async def test_bootstrap_parses_head_and_tail_in_canonical_section(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_bytes(
        b"".join(
            [
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-child",
                            "forked_from_id": "thread-parent",
                            "cwd": "/work/child",
                        },
                    }
                ),
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-parent"},
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_started",
                            "turn_id": "turn-parent",
                        },
                    }
                ),
                b'{"type":"future_record","payload":{"padding":"'
                + b"x" * 4096
                + b'"}}\n',
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_started",
                            "turn_id": "turn-child",
                        },
                    }
                ),
            ]
        )
    )
    observer = SessionObserver(
        tmp_path / "sessions",
        bootstrap_head_bytes=1024,
        bootstrap_tail_bytes=256,
    )

    events = await observer.scan_once()

    running = [event for event in events if event.status is TaskStatus.RUNNING]
    assert [
        (event.thread_id, event.turn_id) for event in running
    ] == [("thread-child", "turn-child")]
    assert all(event.thread_id == "thread-child" for event in events)


@pytest.mark.asyncio
async def test_bootstrap_backward_scan_restores_running_state(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_bytes(
        b"".join(
            [
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-child"},
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_started",
                            "turn_id": "turn-child",
                        },
                    }
                ),
                b'{"type":"future_record","payload":{"padding":"'
                + b"x" * 4096
                + b'"}}\n',
            ]
        )
    )
    observer = SessionObserver(
        tmp_path / "sessions",
        bootstrap_head_bytes=128,
        bootstrap_tail_bytes=64,
        bootstrap_lifecycle_scan_bytes=64 * 1024,
        bootstrap_scan_chunk_bytes=256,
    )

    events = await observer.scan_once()

    running = [event for event in events if event.status is TaskStatus.RUNNING]
    assert [
        (event.thread_id, event.turn_id) for event in running
    ] == [("thread-child", "turn-child")]
    assert running[0].baseline is True


@pytest.mark.asyncio
async def test_bootstrap_backward_scan_skips_replayed_ancestor_lifecycle(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_bytes(
        b"".join(
            [
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {
                            "id": "thread-child",
                            "forked_from_id": "thread-parent",
                        },
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_started",
                            "turn_id": "turn-child",
                        },
                    }
                ),
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-parent"},
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "turn_id": "turn-parent",
                        },
                    }
                ),
                b'{"type":"future_record","payload":{"padding":"'
                + b"x" * 4096
                + b'"}}\n',
            ]
        )
    )
    observer = SessionObserver(
        tmp_path / "sessions",
        bootstrap_head_bytes=128,
        bootstrap_tail_bytes=64,
        bootstrap_lifecycle_scan_bytes=64 * 1024,
        bootstrap_scan_chunk_bytes=256,
    )

    events = await observer.scan_once()

    running = [event for event in events if event.status is TaskStatus.RUNNING]
    completed = [
        event for event in events if event.status is TaskStatus.COMPLETED
    ]
    assert [
        (event.thread_id, event.turn_id) for event in running
    ] == [("thread-child", "turn-child")]
    assert completed == []


@pytest.mark.asyncio
async def test_bootstrap_finds_lifecycle_before_canonical_metadata(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_bytes(
        b"".join(
            [
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-child"},
                    }
                ),
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-parent"},
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "turn_id": "turn-parent",
                        },
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_started",
                            "turn_id": "turn-child",
                        },
                    }
                ),
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-child"},
                    }
                ),
                b'{"type":"future_record","payload":{"padding":"'
                + b"x" * 4096
                + b'"}}\n',
            ]
        )
    )
    observer = SessionObserver(
        tmp_path / "sessions",
        bootstrap_head_bytes=128,
        bootstrap_tail_bytes=64,
        bootstrap_lifecycle_scan_bytes=64 * 1024,
        bootstrap_scan_chunk_bytes=256,
    )

    events = await observer.scan_once()

    running = [event for event in events if event.status is TaskStatus.RUNNING]
    assert [
        (event.thread_id, event.turn_id) for event in running
    ] == [("thread-child", "turn-child")]
    assert running[0].baseline is True


@pytest.mark.asyncio
async def test_bootstrap_does_not_assign_terminal_before_canonical_metadata(
    tmp_path: Path,
) -> None:
    from codex_task_monitor.session_observer.observer import SessionObserver

    session_file = tmp_path / "sessions" / "rollout.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_bytes(
        b"".join(
            [
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-child"},
                    }
                ),
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-parent"},
                    }
                ),
                _json_line(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_complete",
                            "turn_id": "turn-parent",
                        },
                    }
                ),
                _json_line(
                    {
                        "type": "session_meta",
                        "payload": {"id": "thread-child"},
                    }
                ),
                b'{"type":"future_record","payload":{"padding":"'
                + b"x" * 4096
                + b'"}}\n',
            ]
        )
    )
    observer = SessionObserver(
        tmp_path / "sessions",
        bootstrap_head_bytes=128,
        bootstrap_tail_bytes=64,
        bootstrap_lifecycle_scan_bytes=64 * 1024,
        bootstrap_scan_chunk_bytes=256,
    )

    events = await observer.scan_once()

    assert not any(
        event.status is TaskStatus.COMPLETED for event in events
    )


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
