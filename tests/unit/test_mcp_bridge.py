from __future__ import annotations

import pytest
from integrations.mcp.bridge import MCPConnection, discover_and_register
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
    """A fresh in-process server + connection per call — mirrors real usage,
    where MCPConnection opens a new connection for every operation rather
    than reusing one (see integrations/mcp/bridge.py's module docstring for
    why: an mcp.Client's background tasks are tied to the event loop that
    opened it, so it can't be reused across separate asyncio.run() calls)."""
    server = _make_test_server()
    return MCPConnection(_config(name), client_factory=lambda: Client(server))


# --- MCPConnection: real protocol exchange against an in-process server ---


@pytest.mark.asyncio
async def test_list_tools():
    conn = _in_process_connection()
    tools = await conn.list_tools()
    names = {t.name for t in tools}
    assert names == {"echo", "fail_tool"}


@pytest.mark.asyncio
async def test_handler_calls_tool_and_returns_result_dict():
    conn = _in_process_connection()
    handler = conn.make_handler("echo")
    result = await handler(message="hello")
    assert result == {"result": "echo: hello"}


@pytest.mark.asyncio
async def test_handler_returns_error_dict_on_tool_failure():
    conn = _in_process_connection()
    handler = conn.make_handler("fail_tool")
    result = await handler()
    assert "error" in result


@pytest.mark.asyncio
async def test_each_call_opens_its_own_connection():
    """The whole point of the per-call design: list_tools() and two
    separate handler calls must each work independently, proving no state
    is (incorrectly) assumed to persist between them."""
    conn = _in_process_connection()
    await conn.list_tools()
    handler = conn.make_handler("echo")
    first = await handler(message="one")
    second = await handler(message="two")
    assert first == {"result": "echo: one"}
    assert second == {"result": "echo: two"}


def test_handler_survives_across_separate_asyncio_run_calls():
    """Regression test for the real bug this design fixes: a connection
    (or its handler) must remain usable even when list_tools() and the
    tool call happen in genuinely separate asyncio.run() invocations - the
    scenario that broke when connections were kept open across calls.

    Deliberately a plain (non-async) test: it needs to call asyncio.run()
    itself, twice, from a synchronous context - calling asyncio.run() from
    inside a coroutine pytest-asyncio is already running would raise
    "cannot be called from a running event loop", defeating the point."""
    import asyncio

    conn = _in_process_connection()

    tools = asyncio.run(conn.list_tools())
    assert {t.name for t in tools} == {"echo", "fail_tool"}

    handler = conn.make_handler("echo")
    result = asyncio.run(handler(message="hi"))
    assert result == {"result": "echo: hi"}


# --- discover_and_register(): orchestration across multiple servers -------


@pytest.mark.asyncio
async def test_discover_and_register_wraps_tools_with_safe_defaults():
    registry = ToolRegistry()

    def factory(config):
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    reached = await discover_and_register(
        registry, configs=[_config("myserver")], connection_factory=factory
    )
    assert reached == 1

    names = {t.name for t in registry.all()}
    assert names == {"mcp__myserver__echo", "mcp__myserver__fail_tool"}

    echo_tool = registry.get("mcp__myserver__echo")
    assert echo_tool.metadata.requires_confirmation is True
    assert echo_tool.metadata.risk_level == "high"
    assert "myserver" in echo_tool.metadata.description


@pytest.mark.asyncio
async def test_discover_and_register_tool_actually_callable_end_to_end():
    registry = ToolRegistry()

    def factory(config):
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    await discover_and_register(
        registry, configs=[_config("myserver")], connection_factory=factory
    )

    echo_tool = registry.get("mcp__myserver__echo")
    result = await echo_tool.execute(message="ping")
    assert result == {"result": "echo: ping"}


def test_discover_and_register_tool_callable_from_a_separate_asyncio_run():
    """The scenario that actually matters in the real app: discovery runs
    inside one asyncio.run() (ui/chat_window.py's MCPDiscoveryWorker), and
    the tool gets invoked later from a completely different asyncio.run()
    call (a real agent turn). Must still work. Plain (non-async) test for
    the same reason as test_handler_survives_across_separate_asyncio_run_
    calls above - it drives its own asyncio.run() calls directly."""
    import asyncio

    registry = ToolRegistry()

    def factory(config):
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    async def run_discovery():
        return await discover_and_register(
            registry, configs=[_config("myserver")], connection_factory=factory
        )

    asyncio.run(run_discovery())

    echo_tool = registry.get("mcp__myserver__echo")

    async def call_tool():
        return await echo_tool.execute(message="ping")

    result = asyncio.run(call_tool())
    assert result == {"result": "echo: ping"}


@pytest.mark.asyncio
async def test_discover_and_register_skips_server_that_fails_to_connect():
    registry = ToolRegistry()

    class _FailingConnection:
        def __init__(self, config):
            self.config = config

        async def list_tools(self):
            raise ConnectionError("could not spawn process")

    reached = await discover_and_register(
        registry, configs=[_config("broken")], connection_factory=_FailingConnection
    )

    assert registry.all() == []
    assert reached == 0


@pytest.mark.asyncio
async def test_discover_and_register_continues_after_one_server_fails():
    registry = ToolRegistry()

    class _FailingConnection:
        def __init__(self, config):
            self.config = config

        async def list_tools(self):
            raise ConnectionError("nope")

    def factory(config):
        if config.name == "broken":
            return _FailingConnection(config)
        server = _make_test_server()
        return MCPConnection(config, client_factory=lambda: Client(server))

    reached = await discover_and_register(
        registry,
        configs=[_config("broken"), _config("working")],
        connection_factory=factory,
    )

    names = {t.name for t in registry.all()}
    assert names == {"mcp__working__echo", "mcp__working__fail_tool"}
    assert reached == 1


@pytest.mark.asyncio
async def test_discover_and_register_no_configured_servers_is_a_noop(monkeypatch):
    monkeypatch.setattr("integrations.mcp.bridge.load_mcp_servers", lambda: [])
    registry = ToolRegistry()
    reached = await discover_and_register(registry)
    assert reached == 0
    assert registry.all() == []
