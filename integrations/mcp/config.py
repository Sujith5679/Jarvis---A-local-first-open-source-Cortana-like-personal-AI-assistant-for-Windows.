"""MCP server configuration (`mcp_servers.json`, repo root).

Deliberately mirrors Claude Desktop/Claude Code's own config shape
(`mcpServers: {name: {command, args, env}}`) so a config you already have
for those can mostly be reused here — plus an `enabled` flag (defaults
true) so a server can be kept defined but temporarily switched off without
deleting it, same idea as `indexed_folders.enabled`.

Gitignored, same as `.env` (see `.gitignore`) — a server's `env` block
routinely carries real API tokens (a GitHub PAT, a Slack bot token, ...).
`security/secrets.py`'s `known_secrets_from_settings()` includes these so
they get redacted from audit logs/errors the same as any other secret.
`mcp_servers.example.json` is the git-tracked template, with blank/example
values only — same split as `.env`/`.env.example`.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("jarvis.integrations.mcp.config")

# Deliberately cwd-relative, exactly like pydantic-settings' own
# `env_file=".env"` lookup (config/settings.py) - NOT BASE_DIR-absolute.
# start_jarvis.bat resolves its own directory before running, so this
# still finds the real file in real usage; the difference is what it does
# in tests. real_db/isolated_settings (tests/conftest.py) already chdir
# into an isolated tmp_path specifically so the real .env can't leak into
# a test - an absolute BASE_DIR path would defeat that same protection
# here (a real mcp_servers.json would otherwise get read during ordinary
# test runs via security/secrets.py's known_secrets_from_settings(),
# called on every audit log write).
CONFIG_PATH = Path("mcp_servers.json")


@dataclass
class MCPServerConfig:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    enabled: bool = True


def load_all_mcp_servers(path: Path | None = None) -> list[MCPServerConfig]:
    """Returns every configured server (enabled or not). Never raises — a
    missing file, malformed JSON, or invalid entry just logs a warning and
    is skipped/empty, same graceful-degradation rule as every other
    optional subsystem (spec.md §32): MCP is entirely opt-in."""
    path = path or CONFIG_PATH
    if not path.exists():
        return []

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not read MCP server config at %s: %s", path, exc)
        return []

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        logger.warning(
            "mcp_servers.json's 'mcpServers' must be an object, got %s", type(servers).__name__
        )
        return []

    configs: list[MCPServerConfig] = []
    for name, entry in servers.items():
        if not isinstance(entry, dict) or not entry.get("command"):
            logger.warning("Skipping invalid MCP server entry %r (missing 'command')", name)
            continue
        configs.append(
            MCPServerConfig(
                name=name,
                command=entry["command"],
                args=[str(a) for a in entry.get("args", [])],
                env={str(k): str(v) for k, v in entry.get("env", {}).items()},
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return configs


def load_mcp_servers(path: Path | None = None) -> list[MCPServerConfig]:
    """Returns only the enabled servers — what integrations/mcp/bridge.py
    actually connects to."""
    return [c for c in load_all_mcp_servers(path) if c.enabled]
