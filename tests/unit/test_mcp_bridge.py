from __future__ import annotations

import pytest
from integrations.mcp.bridge import (
    MCPConnection,
    close_all,
    discover_and_register,
)
from integrations.mcp.config import MCPServerConfig
from mcp.server.mcpserver import MCPServer
from tools.registry import ToolRegistry

from mcp import Client


def _make_test_server() -> MCPServer:
    """A real in-process MCP server (not mocked) — exercises the actual
    MCP protocol exchange without spawning a subprocess."""
    server = MCPServer("test-server")

    @server.tool()
    def echo(message: str) -> str:
        """Echoes a message back."""
        return f"echo: {message}"

    @server.tool()
    def fail_tool() -> str:
        """Always fails."""
        raise RuntimeError("simulated tool failure")

    return server


def _config(name: str = "test") -> MCPServerConfig:
    return MCPServerConfig(name=name, command="unused-in-tests", args=[], env={})


def _in_process_connection(name: str = "test") -> MCPConnection:
    server = _make_test_server()
    return MCPConnection(_config(name), client_factory=lambda: Client(server))


# --- MCPConnection: real protocol exchange against an in-process server ---


@pytest.mark.asyncio
async def test_connect_and_list_tools():
    conn = _in_process_connection()
    await conn.connect()
    try:
        tools = await conn.list_tools()
        names = {t.name for t in tools}
        assert names == {"echo", "fail_tool"}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_handler_calls_tool_and_returns_result_dict():
    conn = _in_process_connection()
    await conn.connect()
    try:
        handler = conn.make_handler("echo")
        result = await handler(message="hello")
        assert result == {"result": "echo: hello"}
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_handler_returns_error_dict_on_tool_failure():
    conn = _in_process_connection()
    await conn.connect()
    try:
        handler = conn.make_handler("fail_tool")
        result = await handler()
        assert "error" in result
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_close_is_idempotent():
    conn = _in_process_connection()
    await conn.connect()
    await conn.close()
    await conn.close()  # must not raise


# --- discover_and_register(): orchestration across multiple servers -------


@pytest.mark.asyncio
async def test_discover_and_register_wraps_tools_with_safe_defaults():
    registry = ToolRegistry()

    def factory(config):
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    connections = await discover_and_register(
        registry, configs=[_config("myserver")], connection_factory=factory
    )

    names = {t.name for t in registry.all()}
    assert names == {"mcp__myserver__echo", "mcp__myserver__fail_tool"}

    echo_tool = registry.get("mcp__myserver__echo")
    assert echo_tool.metadata.requires_confirmation is True
    assert echo_tool.metadata.risk_level == "high"
    assert "myserver" in echo_tool.metadata.description

    await close_all(connections)


@pytest.mark.asyncio
async def test_discover_and_register_tool_actually_callable_end_to_end():
    registry = ToolRegistry()

    def factory(config):
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    connections = await discover_and_register(
        registry, configs=[_config("myserver")], connection_factory=factory
    )

    echo_tool = registry.get("mcp__myserver__echo")
    result = await echo_tool.execute(message="ping")
    assert result == {"result": "echo: ping"}

    await close_all(connections)


@pytest.mark.asyncio
async def test_discover_and_register_skips_server_that_fails_to_connect():
    registry = ToolRegistry()

    class _FailingConnection:
        def __init__(self, config):
            self.config = config

        async def connect(self):
            raise ConnectionError("could not spawn process")

        async def close(self):
            pass

    connections = await discover_and_register(
        registry, configs=[_config("broken")], connection_factory=_FailingConnection
    )

    assert registry.all() == []
    assert connections == []


@pytest.mark.asyncio
async def test_discover_and_register_continues_after_one_server_fails():
    registry = ToolRegistry()

    class _FailingConnection:
        def __init__(self, config):
            self.config = config

        async def connect(self):
            raise ConnectionError("nope")

        async def close(self):
            pass

    def factory(config):
        if config.name == "broken":
            return _FailingConnection(config)
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    connections = await discover_and_register(
        registry,
        configs=[_config("broken"), _config("working")],
        connection_factory=factory,
    )

    names = {t.name for t in registry.all()}
    assert names == {"mcp__working__echo", "mcp__working__fail_tool"}
    assert len(connections) == 1

    await close_all(connections)


@pytest.mark.asyncio
async def test_discover_and_register_no_configured_servers_is_a_noop(monkeypatch):
    monkeypatch.setattr("integrations.mcp.bridge.load_mcp_servers", lambda: [])
    registry = ToolRegistry()
    connections = await discover_and_register(registry)
    assert connections == []
    assert registry.all() == []


@pytest.mark.asyncio
async def test_close_all_closes_every_connection():
    closed = []

    class _FakeConn:
        async def close(self):
            closed.append(True)

    await close_all([_FakeConn(), _FakeConn()])
    assert closed == [True, True]
