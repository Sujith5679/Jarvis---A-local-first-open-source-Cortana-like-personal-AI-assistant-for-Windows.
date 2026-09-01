"""MCP server configuration (`mcp_servers.json`, repo root).

Deliberately mirrors Claude Desktop/Claude Code's own config shape
(`mcpServers: {name: {command, args, env}}`) so a config you already have
for those can mostly be reused here — plus an `enabled` flag (defaults
true) so a server can be kept defined but temporarily switched off without
deleting it, same idea as `indexed_folders.enabled`.

Two connection styles per server, exactly one required:
- Local (stdio): `command` (+ optional `args`, `env`) — JARVIS spawns it
  as a subprocess, e.g. an `npx`-run filesystem/git/sqlite server.
- Remote (HTTP): `url` (+ optional `headers`) — JARVIS connects to an
  already-running server over the network, e.g. another app's own MCP
  endpoint, or a hosted GitHub/Slack/etc. MCP server. `headers` is where a
  static bearer token/API key goes (`{"Authorization": "Bearer ..."}`) —
  live-verified against a real local HTTP MCP server with a header-gated
  auth check (integrations/mcp/bridge.py's module docstring has the
  details). Full OAuth flows aren't supported — only static headers.

Gitignored, same as `.env` (see `.gitignore`) — a server's `env`/`headers`
block routinely carries a real credential (a GitHub PAT, a Slack bot
token, a bearer token for a remote server, ...).
`security/secrets.py`'s `known_secrets_from_settings()` includes both so
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
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    enabled: bool = True

    @property
    def is_remote(self) -> bool:
        return bool(self.url)


def _parse_entry(name: str, entry: object) -> MCPServerConfig | None:
    if not isinstance(entry, dict):
        logger.warning("Skipping invalid MCP server entry %r (not an object)", name)
        return None

    has_command = bool(entry.get("command"))
    has_url = bool(entry.get("url"))
    if has_command and has_url:
        logger.warning(
            "Skipping MCP server entry %r: has both 'command' and 'url' - pick one "
            "(local via 'command', or remote via 'url')",
            name,
        )
        return None
    if not has_command and not has_url:
        logger.warning("Skipping invalid MCP server entry %r (needs 'command' or 'url')", name)
        return None

    return MCPServerConfig(
        name=name,
        command=entry.get("command") or None,
        args=[str(a) for a in entry.get("args", [])],
        env={str(k): str(v) for k, v in entry.get("env", {}).items()},
        url=entry.get("url") or None,
        headers={str(k): str(v) for k, v in entry.get("headers", {}).items()},
        enabled=bool(entry.get("enabled", True)),
    )


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
        config = _parse_entry(name, entry)
        if config is not None:
            configs.append(config)
    return configs


def load_mcp_servers(path: Path | None = None) -> list[MCPServerConfig]:
    """Returns only the enabled servers — what integrations/mcp/bridge.py
    actually connects to."""
    return [c for c in load_all_mcp_servers(path) if c.enabled]


def save_mcp_servers(configs: list[MCPServerConfig], path: Path | None = None) -> None:
    """Writes the full server list back to mcp_servers.json, overwriting
    it — used by ui/mcp_settings.py's add/edit/remove form. Always writes
    the complete set (never a partial patch), so this is also what a
    remove is: save the list without that entry."""
    path = path or CONFIG_PATH
    data = {
        "mcpServers": {
            c.name: {
                "command": c.command or "",
                "args": c.args,
                "env": c.env,
                "url": c.url or "",
                "headers": c.headers,
                "enabled": c.enabled,
            }
            for c in configs
        }
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
