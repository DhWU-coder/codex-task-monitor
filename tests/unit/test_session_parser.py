from codex_task_monitor.models import TaskStatus


def _parser():
    from codex_task_monitor.session_observer.parser import SessionParser

    return SessionParser()


def test_session_metadata_establishes_thread_and_cwd() -> None:
    parser = _parser()

    events = parser.parse(
        {
            "timestamp": "2026-07-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": "thread-test",
                "cwd": "/workspace/sample-project",
                "source": "appServer",
            },
        },
        baseline=True,
    )

    assert events[0].thread_id == "thread-test"
    assert events[0].cwd == "/workspace/sample-project"
    assert events[0].baseline is True


def test_forked_from_id_is_attached_to_all_session_events() -> None:
    parser = _parser()

    metadata_events = parser.parse(
        {
            "type": "session_meta",
            "payload": {
                "id": "thread-child",
                "forked_from_id": "thread-parent",
            },
        }
    )
    running_events = parser.parse(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-child",
            },
        }
    )

    assert metadata_events[0].parent_thread_id == "thread-parent"
    assert running_events[0].parent_thread_id == "thread-parent"


def test_replayed_ancestor_records_do_not_replace_canonical_thread() -> None:
    parser = _parser()
    canonical = parser.parse(
        {
            "type": "session_meta",
            "payload": {
                "id": "thread-child",
                "forked_from_id": "thread-parent",
                "cwd": "/work/child",
            },
        }
    )
    parser.parse(
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "子任务标题"},
        }
    )

    replayed_metadata = parser.parse(
        {
            "type": "session_meta",
            "payload": {"id": "thread-parent", "cwd": "/work/parent"},
        }
    )
    replayed_running = parser.parse(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-parent",
            },
        }
    )
    parser.resume_canonical_section()
    child_running = parser.parse(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-child",
            },
        }
    )

    assert canonical[0].thread_id == "thread-child"
    assert canonical[0].parent_thread_id == "thread-parent"
    assert replayed_metadata == []
    assert replayed_running == []
    assert child_running[0].thread_id == "thread-child"
    assert child_running[0].turn_id == "turn-child"
    assert child_running[0].title == "子任务标题"
    assert child_running[0].cwd == "/work/child"


def test_replayed_ancestor_user_message_does_not_set_canonical_title() -> None:
    parser = _parser()
    parser.parse(
        {
            "type": "session_meta",
            "payload": {"id": "thread-child"},
        }
    )
    parser.parse(
        {
            "type": "session_meta",
            "payload": {"id": "thread-parent"},
        }
    )
    parser.parse(
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "父任务标题"},
        }
    )

    parser.resume_canonical_section()
    parser.parse(
        {
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "子任务标题"},
        }
    )
    events = parser.parse(
        {
            "type": "event_msg",
            "payload": {"type": "task_started", "turn_id": "turn-child"},
        }
    )

    assert events[0].title == "子任务标题"


def test_task_started_immediately_before_canonical_metadata_is_recovered() -> None:
    parser = _parser()
    canonical_meta = {
        "timestamp": "2026-07-30T06:43:56Z",
        "type": "session_meta",
        "payload": {
            "id": "thread-child",
            "forked_from_id": "thread-parent",
            "cwd": "/work/child",
        },
    }
    parser.parse(canonical_meta)
    parser.parse(
        {
            "type": "session_meta",
            "payload": {"id": "thread-parent"},
        }
    )
    parser.parse(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-parent",
            },
        }
    )
    skipped = parser.parse(
        {
            "timestamp": "2026-07-30T06:44:18Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-child",
                "started_at": "2026-07-30T06:44:18Z",
            },
        }
    )

    resumed = parser.parse(canonical_meta)

    assert skipped == []
    assert [event.status for event in resumed] == [
        TaskStatus.UNKNOWN,
        TaskStatus.RUNNING,
    ]
    assert resumed[-1].thread_id == "thread-child"
    assert resumed[-1].turn_id == "turn-child"


def test_boundary_terminal_event_is_not_replayed_for_canonical_task() -> None:
    parser = _parser()
    canonical_meta = {
        "type": "session_meta",
        "payload": {"id": "thread-child"},
    }
    parser.parse(canonical_meta)
    parser.parse(
        {
            "type": "session_meta",
            "payload": {"id": "thread-parent"},
        }
    )
    parser.parse(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-parent",
            },
        }
    )

    resumed = parser.parse(canonical_meta)

    assert [event.status for event in resumed] == [TaskStatus.UNKNOWN]
    assert resumed[0].turn_id is None


def test_task_started_maps_running_event() -> None:
    parser = _parser()
    parser.parse(
        {
            "type": "session_meta",
            "payload": {"id": "thread-test", "cwd": "/workspace/sample-project"},
        }
    )

    events = parser.parse(
        {
            "timestamp": "2026-07-29T10:00:03Z",
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": "turn-test",
                "started_at": "2026-07-29T10:00:03Z",
            },
        }
    )

    assert events[0].turn_id == "turn-test"
    assert events[0].status is TaskStatus.RUNNING


def test_task_complete_maps_authoritative_completion() -> None:
    parser = _parser()
    parser.parse(
        {"type": "session_meta", "payload": {"id": "thread-test"}}
    )

    events = parser.parse(
        {
            "timestamp": "2026-07-29T10:01:03Z",
            "type": "event_msg",
            "payload": {
                "type": "task_complete",
                "turn_id": "turn-test",
                "last_agent_message": "已完成测试功能。",
                "completed_at": "2026-07-29T10:01:03Z",
            },
        }
    )

    assert events[0].status is TaskStatus.COMPLETED
    assert events[0].latest_summary == "已完成测试功能。"
    assert events[0].authoritative is True


def test_failed_and_interrupted_records_map_terminal_states() -> None:
    parser = _parser()
    parser.parse(
        {"type": "session_meta", "payload": {"id": "thread-test"}}
    )

    failed = parser.parse(
        {
            "type": "event_msg",
            "payload": {
                "type": "task_failed",
                "turn_id": "turn-1",
                "error": "构建失败",
            },
        }
    )
    interrupted = parser.parse(
        {
            "type": "event_msg",
            "payload": {"type": "turn_aborted", "turn_id": "turn-2"},
        }
    )

    assert failed[0].status is TaskStatus.FAILED
    assert failed[0].error_summary == "构建失败"
    assert interrupted[0].status is TaskStatus.INTERRUPTED


def test_request_user_input_maps_waiting_event() -> None:
    parser = _parser()
    parser.parse(
        {"type": "session_meta", "payload": {"id": "thread-test"}}
    )
    parser.parse(
        {
            "type": "turn_context",
            "payload": {"turn_id": "turn-test"},
        }
    )

    events = parser.parse(
        {
            "type": "response_item",
            "payload": {
                "type": "function_call",
                "name": "request_user_input",
                "call_id": "request-1",
                "arguments": '{"questions":[{"question":"是否继续？"}]}',
            },
        }
    )

    assert events[0].status is TaskStatus.WAITING_INPUT
    assert events[0].request_id == "request-1"
    assert events[0].waiting_reason == "是否继续？"


def test_unknown_record_is_ignored() -> None:
    parser = _parser()

    assert parser.parse({"type": "future_record", "payload": {}}) == []
