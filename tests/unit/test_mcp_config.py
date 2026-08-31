from __future__ import annotations

import json

from integrations.mcp.config import (
    CONFIG_PATH,
    MCPServerConfig,
    load_all_mcp_servers,
    load_mcp_servers,
    save_mcp_servers,
)


def _write(tmp_path, data: dict):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_missing_file_returns_empty_list(tmp_path):
    path = tmp_path / "does_not_exist.json"
    assert load_mcp_servers(path) == []
    assert load_all_mcp_servers(path) == []


def test_malformed_json_returns_empty_list(tmp_path):
    path = tmp_path / "mcp_servers.json"
    path.write_text("{not valid json", encoding="utf-8")
    assert load_mcp_servers(path) == []


def test_loads_valid_server(tmp_path):
    path = _write(
        tmp_path,
        {
            "mcpServers": {
                "filesystem": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
                    "env": {"TOKEN": "abc123"},
                }
            }
        },
    )
    servers = load_mcp_servers(path)
    assert len(servers) == 1
    s = servers[0]
    assert s.name == "filesystem"
    assert s.command == "npx"
    assert s.args == ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    assert s.env == {"TOKEN": "abc123"}
    assert s.enabled is True


def test_enabled_defaults_to_true_when_omitted(tmp_path):
    path = _write(tmp_path, {"mcpServers": {"x": {"command": "python"}}})
    assert load_mcp_servers(path)[0].enabled is True


def test_disabled_server_excluded_from_load_mcp_servers(tmp_path):
    path = _write(
        tmp_path,
        {"mcpServers": {"x": {"command": "python", "enabled": False}}},
    )
    assert load_mcp_servers(path) == []
    all_servers = load_all_mcp_servers(path)
    assert len(all_servers) == 1
    assert all_servers[0].enabled is False


def test_entry_missing_command_is_skipped(tmp_path):
    path = _write(tmp_path, {"mcpServers": {"broken": {"args": ["x"]}}})
    assert load_mcp_servers(path) == []


def test_non_dict_entry_is_skipped(tmp_path):
    path = _write(tmp_path, {"mcpServers": {"broken": "not an object"}})
    assert load_mcp_servers(path) == []


def test_mcpservers_not_an_object_returns_empty(tmp_path):
    path = _write(tmp_path, {"mcpServers": ["oops"]})
    assert load_mcp_servers(path) == []


def test_missing_mcpservers_key_returns_empty(tmp_path):
    path = _write(tmp_path, {})
    assert load_mcp_servers(path) == []


def test_defaults_for_optional_fields(tmp_path):
    path = _write(tmp_path, {"mcpServers": {"minimal": {"command": "python"}}})
    s = load_mcp_servers(path)[0]
    assert s.args == []
    assert s.env == {}


def test_config_path_is_cwd_relative_not_repo_root_absolute():
    """Regression test: CONFIG_PATH must resolve relative to cwd, exactly
    like pydantic-settings' own env_file=".env" lookup - not an absolute
    BASE_DIR path. Otherwise a real mcp_servers.json at the repo root would
    leak into every test run via security/secrets.py's
    known_secrets_from_settings() (called on every audit log write),
    defeating the same chdir-based isolation real_db/isolated_settings
    already rely on for `.env`."""
    assert not CONFIG_PATH.is_absolute()


def test_no_path_argument_respects_isolated_cwd(real_db):
    """With no explicit path, load_mcp_servers() must resolve against the
    real_db fixture's isolated tmp_path (which it chdir's into) - never
    the real repo's mcp_servers.json, even if one exists on this machine."""
    assert load_mcp_servers() == []


# --- save_mcp_servers(): ui/mcp_settings.py's add/edit/remove form -------


def test_save_then_load_round_trips(tmp_path):
    path = tmp_path / "mcp_servers.json"
    configs = [
        MCPServerConfig(
            name="filesystem",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
            env={"TOKEN": "abc"},
            enabled=True,
        ),
        MCPServerConfig(name="disabled-one", command="python", enabled=False),
    ]
    save_mcp_servers(configs, path)

    loaded = load_all_mcp_servers(path)
    assert loaded == configs


def test_save_overwrites_existing_file(tmp_path):
    path = tmp_path / "mcp_servers.json"
    save_mcp_servers([MCPServerConfig(name="a", command="x")], path)
    save_mcp_servers([MCPServerConfig(name="b", command="y")], path)

    loaded = load_all_mcp_servers(path)
    assert [c.name for c in loaded] == ["b"]


def test_save_empty_list_produces_empty_config(tmp_path):
    path = tmp_path / "mcp_servers.json"
    save_mcp_servers([], path)
    assert load_all_mcp_servers(path) == []


def test_save_writes_valid_json_matching_documented_shape(tmp_path):
    path = tmp_path / "mcp_servers.json"
    save_mcp_servers(
        [MCPServerConfig(name="x", command="npx", args=["-y"], env={"K": "V"}, enabled=False)],
        path,
    )
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data == {
        "mcpServers": {
            "x": {"command": "npx", "args": ["-y"], "env": {"K": "V"}, "enabled": False}
        }
    }
