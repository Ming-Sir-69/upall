"""Build visible MCP / Skill jobs for the main TUI (CC Switch–style recognition)."""
from __future__ import annotations

import re

from .discovery import Installation
from .layers.mcp import discover_mcp_entries
from .layers.skills import check_skills

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_token(text: str, limit: int = 40) -> str:
    text = _SAFE.sub("-", str(text)).strip("-._")
    return (text or "x")[:limit]


def layer_role(kind: str, host: str, name: str) -> str:
    return f"{kind}.{safe_token(host)}.{safe_token(name)}"


def is_layer_role(role: str) -> bool:
    return role.startswith("mcp.") or role.startswith("skill.")


def build_mcp_installations(home=None) -> dict[str, Installation]:
    """One Installation per discovered MCP server (visible even when not npx)."""
    tools = {}
    for entry in discover_mcp_entries(home):
        host = str(entry.get("host") or "mcp")
        name = str(entry.get("id") or "server")
        role = layer_role("mcp", host, name)
        path = str(entry.get("path") or "")
        label = f"MCP · {name}（{host}）"
        tools[role] = Installation(
            role,
            path=path,
            source="local",
            update_supported=False,
            reason="",
            label=label,
            group="agent",
            monitor="mcp",
            spec={"kind": "mcp", "entry": entry},
        )
    return tools


def build_skill_installations(home=None) -> dict[str, Installation]:
    """One Installation per discovered skill copy (fingerprint, no invented semver)."""
    tools = {}
    for item in check_skills(home=home):
        role = layer_role("skill", item.host, item.name)
        label = f"Skill · {item.name}（{item.host}）"
        tools[role] = Installation(
            role,
            path=str(item.path),
            source="local",
            update_supported=item.sync_state == "drift" and not item.is_symlink,
            reason=item.skip_reason or item.sync_state,
            label=label,
            group="agent",
            monitor="skill",
            spec={
                "kind": "skill",
                "fingerprint": item.fingerprint,
                "sync_state": item.sync_state,
                "is_symlink": item.is_symlink,
                "host": item.host,
                "name": item.name,
            },
        )
    return tools
