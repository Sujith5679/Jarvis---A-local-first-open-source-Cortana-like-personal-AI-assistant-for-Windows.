from __future__ import annotations

import json

from security.secrets import known_secrets_from_settings, mask, scrub_secrets


def test_mask_none_and_empty():
    assert mask(None) == "<unset>"
    assert mask("") == "<empty>"


def test_mask_short_value_fully_hidden():
    assert mask("abc") == "***"


def test_mask_long_value_shows_partial():
    masked = mask("gsk_abcdef123456")
    assert masked.startswith("gsk_")
    assert masked.endswith("56")
    assert "abcdef" not in masked


def test_scrub_secrets_replaces_occurrences():
    text = "Request failed: Authorization Bearer gsk_supersecretkey123 was rejected"
    scrubbed = scrub_secrets(text, ["gsk_supersecretkey123"])
    assert "gsk_supersecretkey123" not in scrubbed
    assert "rejected" in scrubbed


def test_scrub_secrets_ignores_none_entries():
    text = "no secrets here"
    assert scrub_secrets(text, [None, ""]) == text


def test_known_secrets_includes_mcp_server_env_values(real_db, monkeypatch):
    """A configured MCP server's env block (e.g. a GitHub PAT, a Slack bot
    token) must be scrubbed the same as any other secret — an MCP tool's
    own result/error text could echo one back."""
    config_path = real_db.data_dir / "mcp_servers.json"
    config_path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "github": {
                        "command": "npx",
                        "env": {"GITHUB_TOKEN": "ghp_supersecrettoken123"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("integrations.mcp.config.CONFIG_PATH", config_path)

    secrets = known_secrets_from_settings()
    assert "ghp_supersecrettoken123" in secrets

    scrubbed = scrub_secrets("token was ghp_supersecrettoken123, rejected", secrets)
    assert "ghp_supersecrettoken123" not in scrubbed
