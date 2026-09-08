from __future__ import annotations

from tools.registry import Tool, ToolMetadata, ToolRegistry


async def _handler(**kwargs):
    return {"ok": True}


def _tool(name: str) -> Tool:
    return Tool(
        metadata=ToolMetadata(
            name=name, description="d", requires_confirmation=False, risk_level="low",
            timeout_seconds=5.0,
        ),
        input_schema={"type": "object", "properties": {}},
        handler=_handler,
    )


def test_register_and_get():
    registry = ToolRegistry()
    registry.register(_tool("a"))
    assert registry.get("a") is not None
    assert registry.get("a").name == "a"


def test_get_missing_returns_none():
    assert ToolRegistry().get("nope") is None


def test_register_duplicate_name_raises():
    registry = ToolRegistry()
    registry.register(_tool("a"))
    try:
        registry.register(_tool("a"))
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_all_returns_every_registered_tool():
    registry = ToolRegistry()
    registry.register(_tool("a"))
    registry.register(_tool("b"))
    names = {t.name for t in registry.all()}
    assert names == {"a", "b"}


def test_llm_schemas_shape():
    registry = ToolRegistry()
    registry.register(_tool("a"))
    schemas = registry.llm_schemas()
    assert schemas == [
        {
            "type": "function",
            "function": {
                "name": "a",
                "description": "d",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ]


def test_unregister_removes_tool():
    registry = ToolRegistry()
    registry.register(_tool("a"))
    registry.unregister("a")
    assert registry.get("a") is None
    assert registry.all() == []


def test_unregister_missing_tool_is_a_noop():
    registry = ToolRegistry()
    registry.unregister("does_not_exist")  # must not raise


def test_unregister_then_reregister_same_name_succeeds():
    """Confirms that unregistering a tool allows registering a new tool
    with the same name, without hitting the duplicate-name ValueError."""
    registry = ToolRegistry()
    registry.register(_tool("custom_tool"))
    registry.unregister("custom_tool")
    registry.register(_tool("custom_tool"))  # must not raise
    assert registry.get("custom_tool") is not None
