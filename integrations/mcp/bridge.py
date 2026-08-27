"""Bridges MCP servers into JARVIS's own tool registry (tools/registry.py).

Every MCP-sourced tool ALWAYS requires confirmation and is ALWAYS treated
as high risk, regardless of what the server claims about itself — JARVIS
has no way to statically verify what an external, user-configured MCP
server's tool actually does, unlike every built-in tool (whose risk level
was assigned by actually reading its code). spec.md §2.3's "the LLM should
not receive unrestricted access" principle applies here even though these
are "explicit tools" in form — an unreviewed external tool is not the same
trust level as a reviewed one, no exceptions.

Tool names are namespaced `mcp__<server>__<tool>` (the same convention
Claude Code itself uses for MCP tools) so they can never collide with a
built-in tool name and so the confirmation dialog always shows which
server a proposed action actually comes from.

One connection per configured+enabled server, opened once at registry-
build time — schema discovery needs a live round trip, and the LLM must
see tool schemas up front to ever propose calling one — then kept open for
the process's lifetime (closed via `close_all()` at shutdown) so repeat
calls reuse it rather than paying a fresh subprocess-spawn cost every
time. Same "start once, stay up for the session" choice already made for
SearXNG (see web/searxng_process.py's module docstring). A server that
fails to start/connect is skipped with a warning — never fatal to startup,
same graceful-degradation rule as every other optional subsystem.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from tools.registry import Tool, ToolMetadata, ToolRegistry

from integrations.mcp.config import MCPServerConfig, load_mcp_servers
from mcp import Client, StdioServerParameters

logger = logging.getLogger("jarvis.integrations.mcp.bridge")

MCP_TOOL_TIMEOUT_SECONDS = 30.0
# Live-verified this needs real headroom: an npx-based server's *first*
# launch downloads the package before it can even start (a real run against
# @modelcontextprotocol/server-filesystem timed out at 20s cold, then
# connected in ~2s once npm had it cached). Discovery already happens off
# the UI thread (ui/chat_window.py's MCPDiscoveryWorker), so a generous
# timeout here costs nothing but a slightly later "connected" status.
MCP_CONNECT_TIMEOUT_SECONDS = 60.0


def _tool_name(server_name: str, tool_name: str) -> str:
    return f"mcp__{server_name}__{tool_name}"


def _text_from_content(content: list[Any]) -> str:
    return "\n".join(
        block.text for block in content if getattr(block, "type", None) == "text"
    ).strip()


def _result_to_dict(result: Any) -> dict[str, Any]:
    """Converts an MCP CallToolResult into the {result...}/{error...} dict
    shape every JARVIS tool handler returns (tools/registry.py)."""
    if result.is_error:
        text = _text_from_content(result.content)
        return {"error": text or "The MCP tool reported an error with no further detail."}
    if result.structured_content is not None:
        return dict(result.structured_content)
    return {"result": _text_from_content(result.content)}


class MCPConnection:
    """One live connection to one MCP server, kept open for reuse across
    calls. `connect()`/`close()` are the only lifecycle methods callers
    outside this module need — `discover_and_register()` drives both.

    `client_factory` defaults to building a real subprocess-backed `Client`
    from `config`; tests override it to connect an in-process `MCPServer`
    instead (see `mcp.Client`'s constructor — it accepts either), so the
    real MCP protocol exchange gets exercised without spawning a process.
    """

    def __init__(self, config: MCPServerConfig, *, client_factory=None) -> None:
        self.config = config
        self._client_factory = client_factory or self._default_client_factory
        self._client: Client | None = None
        self._client_cm: Any = None

    def _default_client_factory(self) -> Client:
        params = StdioServerParameters(
            command=self.config.command,
            args=self.config.args,
            env=self.config.env or None,
        )
        return Client(params)

    async def connect(self) -> None:
        self._client_cm = self._client_factory()
        self._client = await asyncio.wait_for(
            self._client_cm.__aenter__(), timeout=MCP_CONNECT_TIMEOUT_SECONDS
        )

    async def close(self) -> None:
        if self._client_cm is not None:
            try:
                await self._client_cm.__aexit__(None, None, None)
            except Exception:
                logger.warning("Error closing MCP server %r", self.config.name, exc_info=True)
            finally:
                self._client_cm = None
                self._client = None

    async def list_tools(self) -> list[Any]:
        assert self._client is not None, "connect() must succeed before list_tools()"
        result = await self._client.list_tools()
        return result.tools

    def make_handler(self, mcp_tool_name: str):
        async def _handler(**kwargs: Any) -> dict[str, Any]:
            assert self._client is not None, "MCP connection is not open"
            try:
                result = await self._client.call_tool(mcp_tool_name, kwargs)
            except Exception as exc:
                return {"error": f"MCP tool call failed: {exc}"}
            return _result_to_dict(result)

        return _handler


async def discover_and_register(
    registry: ToolRegistry,
    configs: list[MCPServerConfig] | None = None,
    *,
    connection_factory=None,
) -> list[MCPConnection]:
    """Connects to every enabled configured MCP server, discovers its
    tools, and registers each as a `Tool`. Returns the live connections —
    the caller owns closing them (see `close_all()`). Never raises: a
    server that can't be reached is logged and skipped, the rest still
    load normally.

    `connection_factory` defaults to `MCPConnection`; tests override it to
    inject an in-process server via `MCPConnection`'s own `client_factory`
    (see its docstring) without spawning a real subprocess.
    """
    configs = configs if configs is not None else load_mcp_servers()
    connection_factory = connection_factory or MCPConnection
    connections: list[MCPConnection] = []

    for config in configs:
        conn = connection_factory(config)
        try:
            await conn.connect()
            mcp_tools = await conn.list_tools()
        except Exception as exc:
            logger.warning("Could not connect to MCP server %r: %s", config.name, exc)
            await conn.close()
            continue

        registered = 0
        for mcp_tool in mcp_tools:
            name = _tool_name(config.name, mcp_tool.name)
            description = f"[MCP server: {config.name}] {mcp_tool.description or mcp_tool.name}"
            tool = Tool(
                metadata=ToolMetadata(
                    name=name,
                    description=description,
                    requires_confirmation=True,
                    risk_level="high",
                    timeout_seconds=MCP_TOOL_TIMEOUT_SECONDS,
                ),
                input_schema=mcp_tool.input_schema,
                handler=conn.make_handler(mcp_tool.name),
            )
            try:
                registry.register(tool)
                registered += 1
            except ValueError:
                logger.warning("Tool name collision, skipping: %s", name)

        connections.append(conn)
        logger.info("MCP server %r: registered %d tool(s)", config.name, registered)

    return connections


async def close_all(connections: list[MCPConnection]) -> None:
    for conn in connections:
        await conn.close()
