"""Windows notifications (spec.md §22, §25).

Uses a QSystemTrayIcon purely as a notification-delivery mechanism for now.
Phase 6 builds the full tray menu (Open JARVIS / Start-Stop voice / Pause
indexing / Settings / Reindex files / View logs / Quit) — it should reuse
this same icon instance rather than creating a second one.
"""

from __future__ import annotations

import logging

from PySide6.QtWidgets import QApplication, QStyle, QSystemTrayIcon
from security.audit import log_event

logger = logging.getLogger("jarvis.ui.notifications")

NOTIFICATION_DURATION_MS = 10_000


class NotificationService:
    def __init__(self) -> None:
        app = QApplication.instance()
        icon = (
            app.style().standardIcon(QStyle.StandardPixmap.SP_MessageBoxInformation)
            if app is not None
            else None
        )
        self._tray_icon = QSystemTrayIcon(icon) if icon is not None else QSystemTrayIcon()
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._tray_icon.show()

    def notify(self, title: str, message: str, *, reminder_id: int | None = None) -> bool:
        """Shows a Windows notification and logs delivery status (spec.md §22:
        "Log notification delivery status."). Returns whether it was delivered."""
        delivered = False
        try:
            if QSystemTrayIcon.isSystemTrayAvailable():
                self._tray_icon.showMessage(
                    title,
                    message,
                    QSystemTrayIcon.MessageIcon.Information,
                    NOTIFICATION_DURATION_MS,
                )
                delivered = True
            else:
                logger.warning("System tray unavailable; cannot show notification: %s", title)
        except Exception:
            logger.exception("Failed to show notification: %s", title)

        log_event(
            "notification_delivery",
            status="success" if delivered else "error",
            input_summary=title,
            result_summary=f"reminder_id={reminder_id}" if reminder_id is not None else None,
        )
        return delivered
