"""Usage & Costs dialog — read-only view over storage.repositories.usage.

Shows token/cost totals for the current session (this app run's
conversation — see storage/repositories/usage.py's module docstring for why
that's "session" here) and all-time, each broken down by provider/model,
plus a table of the most recent individual calls. All reads are cheap local
SQLite aggregate queries, so unlike FoldersDialog's indexing this needs no
background worker — everything happens synchronously on open/refresh.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from storage.repositories import usage as usage_repo

# Ollama Cloud (and anything else llm/pricing.py has no per-token price for)
# reports estimated_cost_usd as NULL/None — must read as "not applicable",
# never as zero, since it's a flat GPU-time subscription, not per-token
# billing.
_COST_NOT_APPLICABLE = "included in plan"


def _format_cost(cost: float | None) -> str:
    if cost is None:
        return _COST_NOT_APPLICABLE
    if cost < 0.01:
        return f"${cost:.4f}"
    return f"${cost:.2f}"


def _format_tokens(n: int) -> str:
    return f"{n:,}"


class _TotalsTable(QTableWidget):
    """Provider/model breakdown for one totals dict from usage_repo."""

    def __init__(self, parent=None) -> None:
        super().__init__(0, 5, parent)
        self.setHorizontalHeaderLabels(["Provider", "Model", "Calls", "Tokens", "Est. Cost"])
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionMode(QTableWidget.SelectionMode.NoSelection)

    def load(self, totals: dict) -> None:
        rows = totals["by_provider"]
        self.setRowCount(len(rows))
        for i, row in enumerate(rows):
            self.setItem(i, 0, QTableWidgetItem(row["provider"]))
            self.setItem(i, 1, QTableWidgetItem(row["model"]))
            self.setItem(i, 2, QTableWidgetItem(str(row["call_count"])))
            self.setItem(i, 3, QTableWidgetItem(_format_tokens(row["total_tokens"])))
            self.setItem(i, 4, QTableWidgetItem(_format_cost(row["estimated_cost_usd"])))
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)


class UsageDialog(QDialog):
    def __init__(self, session_id: str, parent=None) -> None:
        super().__init__(parent)
        self.session_id = session_id
        self.setWindowTitle("Usage & Costs")
        self.resize(560, 560)

        layout = QVBoxLayout(self)

        note = QLabel(
            "Token counts are exact; costs are estimated from each provider's "
            "published per-token pricing (llm/pricing.py) and may not exactly "
            "match your bill. Providers with no per-token price — e.g. Ollama "
            "Cloud's flat subscription — show as “" + _COST_NOT_APPLICABLE + "” "
            "rather than a guessed number.",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#6b7280; font-size: 11px;")
        layout.addWidget(note)

        layout.addWidget(self._section_label("This session"))
        self.session_summary = QLabel("", self)
        layout.addWidget(self.session_summary)
        self.session_table = _TotalsTable(self)
        self.session_table.setMaximumHeight(120)
        layout.addWidget(self.session_table)

        layout.addWidget(self._section_label("All time"))
        self.overall_summary = QLabel("", self)
        layout.addWidget(self.overall_summary)
        self.overall_table = _TotalsTable(self)
        self.overall_table.setMaximumHeight(120)
        layout.addWidget(self.overall_table)

        layout.addWidget(self._section_label("Recent calls"))
        self.recent_table = QTableWidget(0, 6, self)
        self.recent_table.setHorizontalHeaderLabels(
            ["Time", "Provider", "Model", "Prompt", "Completion", "Cost"]
        )
        self.recent_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self.recent_table.verticalHeader().setVisible(False)
        self.recent_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.recent_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        layout.addWidget(self.recent_table, stretch=1)

        button_row = QHBoxLayout()
        refresh_button = QPushButton("Refresh", self)
        refresh_button.clicked.connect(self.refresh)
        button_row.addWidget(refresh_button)
        button_row.addStretch(1)
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        self.refresh()

    @staticmethod
    def _section_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet("font-weight: 600; margin-top: 6px;")
        return label

    def refresh(self) -> None:
        session_totals = usage_repo.get_session_totals(self.session_id)
        overall_totals = usage_repo.get_overall_totals()

        self.session_summary.setText(
            f"{session_totals['call_count']} calls, "
            f"{_format_tokens(session_totals['total_tokens'])} tokens, "
            f"{_format_cost(session_totals['estimated_cost_usd'])}"
        )
        self.session_table.load(session_totals)

        self.overall_summary.setText(
            f"{overall_totals['call_count']} calls, "
            f"{_format_tokens(overall_totals['total_tokens'])} tokens, "
            f"{_format_cost(overall_totals['estimated_cost_usd'])}"
        )
        self.overall_table.load(overall_totals)

        recent = usage_repo.list_recent(limit=50)
        self.recent_table.setRowCount(len(recent))
        for i, row in enumerate(recent):
            self.recent_table.setItem(i, 0, QTableWidgetItem(row["timestamp"][:19]))
            self.recent_table.setItem(i, 1, QTableWidgetItem(row["provider"]))
            self.recent_table.setItem(i, 2, QTableWidgetItem(row["model"]))
            self.recent_table.setItem(i, 3, QTableWidgetItem(_format_tokens(row["prompt_tokens"])))
            self.recent_table.setItem(
                i, 4, QTableWidgetItem(_format_tokens(row["completion_tokens"]))
            )
            self.recent_table.setItem(
                i, 5, QTableWidgetItem(_format_cost(row["estimated_cost_usd"]))
            )
        self.recent_table.resizeColumnsToContents()
        self.recent_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
