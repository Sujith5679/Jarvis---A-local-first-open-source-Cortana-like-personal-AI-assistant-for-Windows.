from __future__ import annotations

from datetime import UTC, datetime, timedelta

from scheduler.reminders import check_and_fire_due_reminders
from storage.repositories import reminders as reminders_repo


def test_check_and_fire_due_reminders_fires_and_logs(real_db):
    from storage.database import get_connection

    trigger = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    reminder_id = reminders_repo.create_reminder(title="Take a break", trigger_at=trigger)

    fired = check_and_fire_due_reminders()

    assert len(fired) == 1
    assert fired[0]["id"] == reminder_id

    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM audit_log WHERE action = 'reminder_fired'"
        ).fetchone()
    assert row is not None
    assert row["input_summary"] == "Take a break"


def test_check_and_fire_due_reminders_no_due_reminders_returns_empty(real_db):
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    reminders_repo.create_reminder(title="Later", trigger_at=future)

    assert check_and_fire_due_reminders() == []
