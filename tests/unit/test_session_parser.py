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
