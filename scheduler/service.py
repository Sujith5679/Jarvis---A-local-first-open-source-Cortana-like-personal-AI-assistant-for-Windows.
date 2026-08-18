"""Background job scheduler (spec.md §22, §43).

APScheduler's BackgroundScheduler runs reminder polling (and other
housekeeping jobs) on its own thread, so the UI thread is never blocked.
Because Qt widgets are not thread-safe, a reminder that just fired crosses
back to the GUI thread via a Qt signal (`ReminderBridge`) rather than being
handled directly on the scheduler thread — `QObject.emit()` is safe to call
cross-thread; touching a QWidget from a background thread is not.
"""

from __future__ import annotations

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from config.defaults import DEFAULT_REMINDER_POLL_INTERVAL_SECONDS
from PySide6.QtCore import QObject, Signal

from scheduler.jobs import run_database_maintenance
from scheduler.reminders import check_and_fire_due_reminders

logger = logging.getLogger("jarvis.scheduler")

DATABASE_MAINTENANCE_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


class ReminderBridge(QObject):
    """Marshals reminder-fired events from the scheduler thread to the GUI thread."""

    reminder_fired = Signal(dict)


class SchedulerService:
    def __init__(self) -> None:
        self.bridge = ReminderBridge()
        self._scheduler = BackgroundScheduler()

    def start(self) -> None:
        # Run once immediately so reminders missed while the app was closed
        # fire promptly on startup (spec.md §22: "Recover missed reminders").
        self._poll_reminders()

        self._scheduler.add_job(
            self._poll_reminders,
            IntervalTrigger(seconds=DEFAULT_REMINDER_POLL_INTERVAL_SECONDS),
            id="reminder_poll",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.add_job(
            run_database_maintenance,
            IntervalTrigger(seconds=DATABASE_MAINTENANCE_INTERVAL_SECONDS),
            id="db_maintenance",
            replace_existing=True,
            max_instances=1,
        )
        self._scheduler.start()
        logger.info(
            "Scheduler started (reminder poll every %ss)", DEFAULT_REMINDER_POLL_INTERVAL_SECONDS
        )

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped.")

    def _poll_reminders(self) -> None:
        fired = check_and_fire_due_reminders()
        for reminder in fired:
            self.bridge.reminder_fired.emit(reminder)
