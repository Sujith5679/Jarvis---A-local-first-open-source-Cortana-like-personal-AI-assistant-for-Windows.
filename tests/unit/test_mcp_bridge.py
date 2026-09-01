from __future__ import annotations

from contextlib import asynccontextmanager

import anyio
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


# --- Remote (HTTP) servers — real streamable-HTTP protocol exchange over -
# httpx's ASGITransport (no real socket/subprocess, but the real MCP-over-
# HTTP wire protocol and real header handling, unlike the in-process-
# MCPServer tests above which skip HTTP entirely). Mirrors what was
# live-verified manually against a real local server + real network socket
# (see module docstring): a request with the right Authorization header
# succeeds, one without it is rejected.


@asynccontextmanager
async def _run_asgi_lifespan(app):
    """Manually drives the ASGI lifespan protocol (startup/shutdown) for
    `app`. A real server (uvicorn — what was used for the manual live
    verification in this module's docstring) does this automatically;
    httpx's ASGITransport deliberately does not, so a bare ASGITransport
    call fails with "Task group is not initialized" — MCPServer's
    streamable_http_app() initializes its session manager's task group in
    its lifespan startup handler, same as any Starlette app with startup
    work to do. This is the same thing the `asgi-lifespan` package's
    LifespanManager does; written by hand here to avoid a new test-only
    dependency."""
    to_app_send, to_app_receive = anyio.create_memory_object_stream(1)
    from_app_send, from_app_receive = anyio.create_memory_object_stream(4)

    async def receive():
        return await to_app_receive.receive()

    async def send(message):
        await from_app_send.send(message)

    async with anyio.create_task_group() as tg:
        tg.start_soon(app, {"type": "lifespan"}, receive, send)
        await to_app_send.send({"type": "lifespan.startup"})
        startup_result = await from_app_receive.receive()
        assert startup_result["type"] == "lifespan.startup.complete", startup_result
        try:
            yield
        finally:
            await to_app_send.send({"type": "lifespan.shutdown"})
            tg.cancel_scope.cancel()


def _make_asgi_app_with_auth(required_header: str):
    """A real MCP server exposed over a real (in-process, ASGI) HTTP app,
    with a hand-rolled auth check in front of it — the same shape as a
    real hosted MCP server that gates access by a bearer token/API key.

    transport_security=disabled is deliberate: MCPServer's high-level API
    enables Host/Origin DNS-rebinding protection by default (a real,
    separate security feature, unrelated to what this test is checking),
    and it rejects this test's fake ASGITransport host - what's under test
    here is JARVIS's own header-injection wiring, not the SDK's rebinding
    protection, so it's turned off rather than fought."""
    from mcp.server.transport_security import TransportSecuritySettings

    server = MCPServer("remote-test-server")

    @server.tool()
    def whoami(name: str) -> str:
        return f"hello, {name}"

    inner_app = server.streamable_http_app(
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False)
    )

    async def app(scope, receive, send):
        if scope["type"] == "http":
            headers = dict(scope.get("headers", []))
            token = headers.get(b"authorization", b"").decode()
            if token != required_header:
                await send(
                    {"type": "http.response.start", "status": 401, "headers": []}
                )
                await send({"type": "http.response.body", "body": b"unauthorized"})
                return
        await inner_app(scope, receive, send)

    return app


_ASGI_TEST_URL = "http://localhost/mcp"  # not an arbitrary host - see
# test_remote_server_with_correct_auth_header_succeeds's discovery below:
# MCPServer's TransportSecurityMiddleware rejects an unrecognized `Host`
# header (real DNS-rebinding protection), so the fake base URL has to be
# one it actually allows by default.


def _asgi_connection(config: MCPServerConfig, app) -> MCPConnection:
    import httpx2
    from mcp.client.streamable_http import streamable_http_client

    def client_factory():
        http_client = httpx2.AsyncClient(
            transport=httpx2.ASGITransport(app=app),
            base_url=_ASGI_TEST_URL,
            headers=config.headers or None,
        )
        transport = streamable_http_client(_ASGI_TEST_URL, http_client=http_client)
        return Client(transport)

    return MCPConnection(config, client_factory=client_factory)


@pytest.mark.asyncio
async def test_remote_server_with_correct_auth_header_succeeds():
    app = _make_asgi_app_with_auth("Bearer secret-token")
    config = MCPServerConfig(
        name="remote", url="http://test/mcp", headers={"Authorization": "Bearer secret-token"}
    )
    conn = _asgi_connection(config, app)

    async with _run_asgi_lifespan(app):
        tools = await conn.list_tools()
        assert {t.name for t in tools} == {"whoami"}

        handler = conn.make_handler("whoami")
        result = await handler(name="jarvis")
        assert result == {"result": "hello, jarvis"}


@pytest.mark.asyncio
async def test_remote_server_without_auth_header_is_rejected():
    app = _make_asgi_app_with_auth("Bearer secret-token")
    config = MCPServerConfig(name="remote", url="http://test/mcp", headers={})
    conn = _asgi_connection(config, app)

    with pytest.raises(Exception):  # noqa: B017 - transport-level failure, exact type varies
        await conn.list_tools()


@pytest.mark.asyncio
async def test_remote_server_with_wrong_auth_header_is_rejected():
    app = _make_asgi_app_with_auth("Bearer secret-token")
    config = MCPServerConfig(
        name="remote", url="http://test/mcp", headers={"Authorization": "Bearer wrong"}
    )
    conn = _asgi_connection(config, app)

    with pytest.raises(Exception):  # noqa: B017 - transport-level failure, exact type varies
        await conn.list_tools()


@pytest.mark.asyncio
async def test_discover_and_register_works_for_a_remote_server():
    app = _make_asgi_app_with_auth("Bearer secret-token")
    config = MCPServerConfig(
        name="remote", url="http://test/mcp", headers={"Authorization": "Bearer secret-token"}
    )
    registry = ToolRegistry()

    async with _run_asgi_lifespan(app):
        reached = await discover_and_register(
            registry, configs=[config], connection_factory=lambda cfg: _asgi_connection(cfg, app)
        )

        assert reached == 1
        tool = registry.get("mcp__remote__whoami")
        assert tool is not None
        assert tool.metadata.requires_confirmation is True
        result = await tool.execute(name="world")
        assert result == {"result": "hello, world"}


# --- _default_client_factory(): the actual production wiring for a config
# with no client_factory override (what real usage goes through) --------


def test_default_client_factory_builds_stdio_client_for_local_config():
    config = MCPServerConfig(
        name="local", command="python", args=["-u", "server.py"], env={"A": "1"}
    )
    conn = MCPConnection(config)

    client = conn._default_client_factory()
    from mcp import StdioServerParameters

    assert isinstance(client.server, StdioServerParameters)
    assert client.server.command == "python"
    assert client.server.args == ["-u", "server.py"]
    assert client.server.env == {"A": "1"}


def test_default_client_factory_builds_http_transport_for_remote_config(monkeypatch):
    calls = {}
    # A plain object, deliberately NOT a str/StdioServerParameters/server -
    # Client.__post_init__ special-cases those types (a bare str is treated
    # as a URL to build its own default transport for), so returning one
    # here would test the wrong code path in mcp.Client itself instead of
    # confirming JARVIS passed the right opaque transport through.
    sentinel_transport = object()

    def fake_create_mcp_http_client(headers=None):
        calls["headers"] = headers
        return "fake-http-client"

    def fake_streamable_http_client(url, *, http_client=None):
        calls["url"] = url
        calls["http_client"] = http_client
        return sentinel_transport

    monkeypatch.setattr(
        "mcp.client.streamable_http.create_mcp_http_client", fake_create_mcp_http_client
    )
    monkeypatch.setattr(
        "mcp.client.streamable_http.streamable_http_client", fake_streamable_http_client
    )

    config = MCPServerConfig(
        name="remote", url="https://example.com/mcp", headers={"Authorization": "Bearer x"}
    )
    conn = MCPConnection(config)
    client = conn._default_client_factory()

    assert calls["headers"] == {"Authorization": "Bearer x"}
    assert calls["url"] == "https://example.com/mcp"
    assert calls["http_client"] == "fake-http-client"
    assert client.server is sentinel_transport
