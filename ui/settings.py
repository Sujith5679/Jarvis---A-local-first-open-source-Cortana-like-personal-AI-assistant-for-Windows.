"""Basic settings page (spec.md §3.1) — folder management, plus a startup
section added in Phase 6 (spec.md §27).

Voice/hotkey preferences remain `.env`-only for now (see README) — this
dialog's own docstring history noted they'd get their own section "later,"
and startup is the one Phase 6 actually promotes into the UI since it's the
one preference the spec explicitly frames as a user-facing ON/OFF toggle
(§27: "Start JARVIS with Windows: ON/OFF" — "Do not force automatic
startup").
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)
from rag import indexing_state
from rag.embeddings import get_default_embedding_provider
from rag.ingestion import IngestionPipeline, IngestionSummary
from rag.vector_store import get_default_vector_store
from storage.repositories import folders as folders_repo
from tools import file_search

from app import windows_startup

logger = logging.getLogger("jarvis.ui.settings")


class IndexingWorker(QThread):
    """Runs a full folder sync off the UI thread (spec.md §42: indexing must
    never freeze the UI). Builds its own pipeline/embedding/vector-store
    instances rather than sharing the UI's, since this executes on a
    different thread — see invalidate_cache() for how the two are
    reconciled afterwards."""

    succeeded = Signal(object)  # IngestionSummary
    failed = Signal(str)

    def run(self) -> None:
        try:
            embedding_provider = get_default_embedding_provider()
            vector_store = get_default_vector_store(dimension=embedding_provider.dimension)
            pipeline = IngestionPipeline(
                embedding_provider=embedding_provider, vector_store=vector_store
            )
            summary = pipeline.sync_all_enabled_folders()
            self.succeeded.emit(summary)
        except Exception as exc:  # pragma: no cover - defensive
            logger.exception("Indexing failed")
            self.failed.emit(str(exc))


class FoldersDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.resize(480, 420)
        self._worker: IndexingWorker | None = None

        layout = QVBoxLayout(self)

        folders_heading = QLabel("Indexed folders", self)
        folders_heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(folders_heading)

        info = QLabel(
            "JARVIS only searches folders you explicitly add here — never your whole drive.",
            self,
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        self.folder_list = QListWidget(self)
        layout.addWidget(self.folder_list, stretch=1)

        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color:#6b7280; font-style: italic;")
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add Folder...", self)
        self.add_button.clicked.connect(self._on_add_folder)
        button_row.addWidget(self.add_button)

        self.remove_button = QPushButton("Remove Selected", self)
        self.remove_button.clicked.connect(self._on_remove_folder)
        button_row.addWidget(self.remove_button)

        self.reindex_button = QPushButton("Reindex Now", self)
        self.reindex_button.clicked.connect(self._start_indexing)
        button_row.addWidget(self.reindex_button)
        layout.addLayout(button_row)

        startup_heading = QLabel("Startup", self)
        startup_heading.setStyleSheet("font-weight: 600; margin-top: 10px;")
        layout.addWidget(startup_heading)

        self.startup_checkbox = QCheckBox("Start JARVIS with Windows", self)
        try:
            self.startup_checkbox.setChecked(windows_startup.is_startup_enabled())
        except Exception:
            logger.exception("Could not query Windows startup task state")
            self.startup_checkbox.setEnabled(False)
            self.startup_checkbox.setToolTip("Could not check Task Scheduler — see logs.")
        self.startup_checkbox.toggled.connect(self._on_startup_toggled)
        layout.addWidget(self.startup_checkbox)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self._refresh_list()

    def _on_startup_toggled(self, checked: bool) -> None:
        try:
            if checked:
                windows_startup.enable_startup()
            else:
                windows_startup.disable_startup()
        except windows_startup.StartupTaskError as exc:
            QMessageBox.warning(self, "Startup setting", f"Could not update startup task: {exc}")
            # Revert the checkbox to reflect reality, without re-triggering this handler.
            self.startup_checkbox.blockSignals(True)
            self.startup_checkbox.setChecked(not checked)
            self.startup_checkbox.blockSignals(False)

    def _refresh_list(self) -> None:
        self.folder_list.clear()
        for folder in folders_repo.list_folders(enabled_only=True):
            self.folder_list.addItem(folder["path"])

    def _on_add_folder(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Select a folder for JARVIS to index")
        if not directory:
            return
        folders_repo.add_folder(directory)
        self._refresh_list()
        self._start_indexing()

    def _on_remove_folder(self) -> None:
        item = self.folder_list.currentItem()
        if item is None:
            return
        path = item.text()
        for folder in folders_repo.list_folders(enabled_only=True):
            if folder["path"] == path:
                folders_repo.remove_folder(folder["id"])
                break
        self._refresh_list()

    def _start_indexing(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        if indexing_state.is_paused():
            self.status_label.setText(
                "Indexing is paused — resume it from the tray icon to reindex."
            )
            return
        self.status_label.setText("Indexing… this runs in the background.")
        self.add_button.setEnabled(False)
        self.reindex_button.setEnabled(False)

        self._worker = IndexingWorker()
        self._worker.succeeded.connect(self._on_indexing_succeeded)
        self._worker.failed.connect(self._on_indexing_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_indexing_succeeded(self, summary: IngestionSummary) -> None:
        # The worker's VectorStore is a different in-memory instance than the
        # one cached inside tools.file_search — without this, search_files
        # would keep answering from the pre-reindex index.
        file_search.invalidate_cache()
        self.status_label.setText(
            f"Indexed {summary.indexed}, skipped {summary.skipped_unchanged} unchanged, "
            f"{summary.failed} failed, {summary.removed} removed."
        )
        self.add_button.setEnabled(True)
        self.reindex_button.setEnabled(True)

    def _on_indexing_failed(self, message: str) -> None:
        self.status_label.setText(f"Indexing error: {message}")
        self.add_button.setEnabled(True)
        self.reindex_button.setEnabled(True)
