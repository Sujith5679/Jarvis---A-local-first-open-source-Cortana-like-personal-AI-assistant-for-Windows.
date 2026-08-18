from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from storage.repositories import reminders as reminders_repo


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def test_create_and_list_reminder(real_db):
    trigger = _iso(datetime.now(UTC) + timedelta(hours=1))
    reminder_id = reminders_repo.create_reminder(title="Submit report", trigger_at=trigger)

    reminders = reminders_repo.list_reminders(status="pending")
    assert len(reminders) == 1
    assert reminders[0]["id"] == reminder_id
    assert reminders[0]["title"] == "Submit report"


def test_invalid_recurrence_rejected(real_db):
    trigger = _iso(datetime.now(UTC))
    with pytest.raises(ValueError):
        reminders_repo.create_reminder(title="x", trigger_at=trigger, recurrence="monthly")


def test_get_due_reminders_only_returns_past_pending(real_db):
    now = datetime.now(UTC)
    past_id = reminders_repo.create_reminder(
        title="Past", trigger_at=_iso(now - timedelta(minutes=5))
    )
    reminders_repo.create_reminder(title="Future", trigger_at=_iso(now + timedelta(hours=1)))

    due = reminders_repo.get_due_reminders(_iso(now))
    assert [r["id"] for r in due] == [past_id]


def test_fire_due_reminders_marks_oneoff_as_fired(real_db):
    now = datetime.now(UTC)
    reminder_id = reminders_repo.create_reminder(
        title="One-off", trigger_at=_iso(now - timedelta(minutes=1))
    )

    fired = reminders_repo.fire_due_reminders(now)
    assert [r["id"] for r in fired] == [reminder_id]

    reminder = reminders_repo.get_reminder(reminder_id)
    assert reminder["status"] == "fired"

    # A second poll at the same "now" must not refire it.
    assert reminders_repo.fire_due_reminders(now) == []


def test_fire_due_reminders_advances_recurring_and_stays_pending(real_db):
    now = datetime.now(UTC)
    reminder_id = reminders_repo.create_reminder(
        title="Daily standup",
        trigger_at=_iso(now - timedelta(minutes=1)),
        recurrence="daily",
    )

    fired = reminders_repo.fire_due_reminders(now)
    assert [r["id"] for r in fired] == [reminder_id]

    reminder = reminders_repo.get_reminder(reminder_id)
    assert reminder["status"] == "pending"  # stays pending, not 'fired'
    next_trigger = datetime.fromisoformat(reminder["trigger_at"])
    assert next_trigger > now

    # Not due again immediately.
    assert reminders_repo.fire_due_reminders(now) == []


def test_fire_due_reminders_recurring_after_long_gap_only_fires_once(real_db):
    """If the app was closed for 5 days, a daily reminder must fire once on
    restart and reschedule into the future, not fire 5 times back-to-back."""
    now = datetime.now(UTC)
    reminder_id = reminders_repo.create_reminder(
        title="Daily standup",
        trigger_at=_iso(now - timedelta(days=5)),
        recurrence="daily",
    )

    fired = reminders_repo.fire_due_reminders(now)
    assert [r["id"] for r in fired] == [reminder_id]

    reminder = reminders_repo.get_reminder(reminder_id)
    next_trigger = datetime.fromisoformat(reminder["trigger_at"])
    assert next_trigger > now


def test_complete_reminder(real_db):
    trigger = _iso(datetime.now(UTC))
    reminder_id = reminders_repo.create_reminder(title="x", trigger_at=trigger)
    assert reminders_repo.complete_reminder(reminder_id) is True
    reminder = reminders_repo.get_reminder(reminder_id)
    assert reminder["status"] == "completed"
    assert reminder["completed_at"] is not None


def test_dismiss_reminder(real_db):
    trigger = _iso(datetime.now(UTC))
    reminder_id = reminders_repo.create_reminder(title="x", trigger_at=trigger)
    assert reminders_repo.dismiss_reminder(reminder_id) is True
    reminder = reminders_repo.get_reminder(reminder_id)
    assert reminder["status"] == "dismissed"
