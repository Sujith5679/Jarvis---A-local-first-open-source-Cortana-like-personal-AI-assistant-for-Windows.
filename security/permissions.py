"""Tool permission enforcement (spec.md §28, §54).

This is the application-code gate the spec requires: "Tool permission checks
must happen in application code, not only inside the LLM prompt." The LLM
may *propose* any registered tool call; this module is what actually decides
whether it's allowed to run immediately or must pause for user confirmation.

No HIGH/MEDIUM-risk tool is registered yet in Phase 2 (search_files/read_file
are both LOW), so the `requires_confirmation` branch isn't exercised in
practice until Phase 3 (notes/tasks/reminders deletion). The mechanism exists
now so later phases only need to register a tool with
`requires_confirmation=True` — no change to this module or the agent loop.
"""

from __future__ import annotations

from dataclasses import dataclass

from tools.registry import Tool


@dataclass
class PermissionDecision:
    allowed: bool
    requires_confirmation: bool
    reason: str | None = None


def check_permission(tool: Tool) -> PermissionDecision:
    if tool.metadata.requires_confirmation:
        return PermissionDecision(
            allowed=False,
            requires_confirmation=True,
            reason=f"'{tool.name}' is a {tool.metadata.risk_level}-risk action and requires "
            f"explicit user confirmation before it can run.",
        )
    return PermissionDecision(allowed=True, requires_confirmation=False)
