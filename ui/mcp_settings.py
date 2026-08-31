"""MCP Servers settings dialog — add/edit/remove `mcp_servers.json` entries
and reconnect live (integrations/mcp/).

Two dialogs: `MCPServerEditDialog` (one server's fields — name, command,
args, env, enabled) and `MCPServersDialog` (the list + Add/Edit/Remove/
Reconnect Now, opened from ChatWindow's Settings menu).

Editing the config file alone doesn't affect a running JARVIS — the agent's
tool registry only reflects what integrations/mcp/bridge.py discovered at
startup (or the last "Reconnect Now"). "Reconnect Now" is what actually
unregisters the old MCP tools and rediscovers from the edited config,
without needing to restart the app.
"""

from __future__ import annotations

import logging

from integrations.mcp.config import (
    MCPServerConfig,
    load_all_mcp_servers,
    save_mcp_servers,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

logger = logging.getLogger("jarvis.ui.mcp_settings")


def _parse_env_lines(text: str) -> tuple[dict[str, str], list[str]]:
    """Parses "KEY=VALUE" per line. Returns (env dict, warnings) — a
    malformed line is skipped and reported, never a hard error, so one typo
    doesn't block saving the rest of the form."""
    env: dict[str, str] = {}
    warnings: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if "=" not in line:
            warnings.append(f"Ignored (no '='): {line!r}")
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            warnings.append(f"Ignored (empty key): {line!r}")
            continue
        env[key] = value.strip()
    return env, warnings


class MCPServerEditDialog(QDialog):
    """Add (existing=None) or edit (existing=<config>) one server."""

    def __init__(
        self, existing: MCPServerConfig | None, other_names: set[str], parent=None
    ) -> None:
        super().__init__(parent)
        self._other_names = other_names  # names already used by *other* servers
        self.setWindowTitle("Add MCP Server" if existing is None else "Edit MCP Server")
        self.resize(440, 420)

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Name", self))
        self.name_field = QLineEdit(self)
        self.name_field.setPlaceholderText("e.g. filesystem")
        layout.addWidget(self.name_field)

        layout.addWidget(QLabel("Command", self))
        self.command_field = QLineEdit(self)
        self.command_field.setPlaceholderText("e.g. npx")
        layout.addWidget(self.command_field)

        layout.addWidget(QLabel("Arguments (one per line)", self))
        self.args_field = QPlainTextEdit(self)
        self.args_field.setPlaceholderText("-y\n@modelcontextprotocol/server-filesystem\nC:\\Users\\you\\Documents")
        layout.addWidget(self.args_field)

        layout.addWidget(QLabel("Environment variables (KEY=VALUE, one per line)", self))
        self.env_field = QPlainTextEdit(self)
        self.env_field.setPlaceholderText("GITHUB_TOKEN=ghp_...")
        layout.addWidget(self.env_field)

        self.enabled_checkbox = QCheckBox("Enabled", self)
        self.enabled_checkbox.setChecked(True)
        layout.addWidget(self.enabled_checkbox)

        self.error_label = QLabel("", self)
        self.error_label.setStyleSheet("color:#b91c1c;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        button_row = QHBoxLayout()
        save_button = QPushButton("Save", self)
        save_button.clicked.connect(self._on_save)
        button_row.addWidget(save_button)
        cancel_button = QPushButton("Cancel", self)
        cancel_button.clicked.connect(self.reject)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self.result_config: MCPServerConfig | None = None

        if existing is not None:
            self.name_field.setText(existing.name)
            self.command_field.setText(existing.command)
            self.args_field.setPlainText("\n".join(existing.args))
            self.env_field.setPlainText(
                "\n".join(f"{k}={v}" for k, v in existing.env.items())
            )
            self.enabled_checkbox.setChecked(existing.enabled)

    def _on_save(self) -> None:
        name = self.name_field.text().strip()
        command = self.command_field.text().strip()

        if not name:
            self.error_label.setText("Name is required.")
            return
        if name in self._other_names:
            self.error_label.setText(f"A server named {name!r} already exists.")
            return
        if not command:
            self.error_label.setText("Command is required.")
            return

        args = [line.strip() for line in self.args_field.toPlainText().splitlines() if line.strip()]
        env, warnings = _parse_env_lines(self.env_field.toPlainText())
        if warnings:
            self.error_label.setText("; ".join(warnings))
            return

        self.result_config = MCPServerConfig(
            name=name,
            command=command,
            args=args,
            env=env,
            enabled=self.enabled_checkbox.isChecked(),
        )
        self.accept()


class MCPServersDialog(QDialog):
    def __init__(self, window, parent=None) -> None:
        super().__init__(parent)
        self.window = window  # ui.chat_window.ChatWindow — for "Reconnect Now"
        self.setWindowTitle("MCP Servers")
        self.resize(480, 380)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Tools from these servers always require your confirmation before running, "
            "no matter what they claim to do.",
            self,
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#6b7280; font-size: 11px;")
        layout.addWidget(info)

        self.server_list = QListWidget(self)
        layout.addWidget(self.server_list, stretch=1)

        self.status_label = QLabel("", self)
        self.status_label.setStyleSheet("color:#6b7280; font-style: italic;")
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("Add...", self)
        self.add_button.clicked.connect(self._on_add)
        button_row.addWidget(self.add_button)

        self.edit_button = QPushButton("Edit...", self)
        self.edit_button.clicked.connect(self._on_edit)
        button_row.addWidget(self.edit_button)

        self.remove_button = QPushButton("Remove", self)
        self.remove_button.clicked.connect(self._on_remove)
        button_row.addWidget(self.remove_button)

        self.reconnect_button = QPushButton("Reconnect Now", self)
        self.reconnect_button.clicked.connect(self._on_reconnect)
        button_row.addWidget(self.reconnect_button)
        layout.addLayout(button_row)

        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.accept)
        layout.addWidget(close_button)

        self._configs: list[MCPServerConfig] = []
        self._refresh_list()

    def _refresh_list(self) -> None:
        self._configs = load_all_mcp_servers()
        self.server_list.clear()
        for config in self._configs:
            status = "enabled" if config.enabled else "disabled"
            self.server_list.addItem(f"{config.name}  ({status}) — {config.command}")

    def _selected_config(self) -> MCPServerConfig | None:
        row = self.server_list.currentRow()
        if row < 0 or row >= len(self._configs):
            return None
        return self._configs[row]

    def _on_add(self) -> None:
        other_names = {c.name for c in self._configs}
        dialog = MCPServerEditDialog(None, other_names, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_config is not None:
            self._configs.append(dialog.result_config)
            save_mcp_servers(self._configs)
            self._refresh_list()
            self.status_label.setText("Saved. Click Reconnect Now to apply.")

    def _on_edit(self) -> None:
        current = self._selected_config()
        if current is None:
            return
        other_names = {c.name for c in self._configs if c.name != current.name}
        dialog = MCPServerEditDialog(current, other_names, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.result_config is not None:
            index = self._configs.index(current)
            self._configs[index] = dialog.result_config
            save_mcp_servers(self._configs)
            self._refresh_list()
            self.status_label.setText("Saved. Click Reconnect Now to apply.")

    def _on_remove(self) -> None:
        current = self._selected_config()
        if current is None:
            return
        answer = QMessageBox.question(
            self,
            "Remove MCP server",
            f"Remove {current.name!r} from mcp_servers.json?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._configs = [c for c in self._configs if c.name != current.name]
        save_mcp_servers(self._configs)
        self._refresh_list()
        self.status_label.setText("Removed. Click Reconnect Now to apply.")

    def _on_reconnect(self) -> None:
        self.add_button.setEnabled(False)
        self.edit_button.setEnabled(False)
        self.remove_button.setEnabled(False)
        self.reconnect_button.setEnabled(False)
        started = self.window.reconnect_mcp_servers(on_done=self._on_reconnect_done)
        if started:
            self.status_label.setText("Reconnecting…")
        else:
            # A discovery/reconnect was already in flight (e.g. JARVIS just
            # started and its own initial connect hasn't finished yet) —
            # on_done was NOT scheduled, so re-enable the buttons here too.
            self.status_label.setText("Still connecting from before — try again in a moment.")
            self.add_button.setEnabled(True)
            self.edit_button.setEnabled(True)
            self.remove_button.setEnabled(True)
            self.reconnect_button.setEnabled(True)

    def _on_reconnect_done(self, count: int) -> None:
        self.status_label.setText(f"Reconnected — {count} MCP server(s) live.")
        self.add_button.setEnabled(True)
        self.edit_button.setEnabled(True)
        self.remove_button.setEnabled(True)
        self.reconnect_button.setEnabled(True)
