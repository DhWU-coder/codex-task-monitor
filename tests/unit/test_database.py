import os
import stat
from pathlib import Path

import pytest


def _repository(database_path: Path):
    from codex_task_monitor.storage.database import Database
    from codex_task_monitor.storage.repository import Repository

    database = Database(database_path)
    database.initialize()
    return Repository(database)


def test_notification_key_is_unique(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "data" / "monitor.db")

    assert repository.reserve_notification("thread:turn:completed") is True
    assert repository.reserve_notification("thread:turn:completed") is False


def test_recovery_deactivates_non_running_watch(tmp_path: Path) -> None:
    from codex_task_monitor.models import TaskStatus, WatchMode

    repository = _repository(tmp_path / "data" / "monitor.db")
    repository.save_watch(thread_id="t1", mode=WatchMode.PERSISTENT, active=True)

    repository.restore_watches({"t1": TaskStatus.COMPLETED})

    watch = repository.get_watch("t1")
    assert watch is not None
    assert watch.active is False


def test_recovery_keeps_waiting_watch_active(tmp_path: Path) -> None:
    from codex_task_monitor.models import TaskStatus, WatchMode

    repository = _repository(tmp_path / "data" / "monitor.db")
    repository.save_watch(thread_id="t1", mode=WatchMode.CURRENT_TURN, active=True)

    repository.restore_watches({"t1": TaskStatus.WAITING_INPUT})

    watch = repository.get_watch("t1")
    assert watch is not None
    assert watch.active is True


def test_saved_watch_round_trips_turn_and_baseline(tmp_path: Path) -> None:
    from codex_task_monitor.models import TaskStatus, WatchMode

    repository = _repository(tmp_path / "data" / "monitor.db")

    repository.save_watch(
        thread_id="t1",
        mode=WatchMode.CURRENT_TURN,
        turn_id="turn-1",
        baseline_status=TaskStatus.RUNNING,
        active=True,
    )

    watch = repository.get_watch("t1")
    assert watch is not None
    assert watch.turn_id == "turn-1"
    assert watch.baseline_status is TaskStatus.RUNNING
    assert watch.mode is WatchMode.CURRENT_TURN


@pytest.mark.skipif(os.name == "nt", reason="Windows 不支持 POSIX 权限位")
def test_database_permissions_are_private(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "monitor.db"
    _repository(database_path)

    assert stat.S_IMODE(database_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(database_path.stat().st_mode) == 0o600


def test_failed_notification_can_be_prepared_for_retry(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "data" / "monitor.db")
    repository.reserve_notification(
        "thread:turn:completed",
        message="Codex 任务已完成",
    )
    repository.mark_notification_failed(
        "thread:turn:completed",
        "临时网络错误",
    )
    notification = repository.get_notification_by_key(
        "thread:turn:completed"
    )
    assert notification is not None

    retry = repository.prepare_notification_retry(notification["id"])

    assert retry is not None
    assert retry["message"] == "Codex 任务已完成"
    assert repository.get_notification(notification["id"])["state"] == "pending"


def test_sent_notification_cannot_be_retried(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "data" / "monitor.db")
    repository.reserve_notification(
        "thread:turn:completed",
        message="Codex 任务已完成",
    )
    repository.mark_notification_sent("thread:turn:completed", "om_1")
    notification = repository.get_notification_by_key(
        "thread:turn:completed"
    )
    assert notification is not None

    assert repository.prepare_notification_retry(notification["id"]) is None
