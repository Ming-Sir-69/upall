"""Build visible MCP / Skill jobs for the main TUI.

Only installed entries; structural discovery; fingerprint/name dedup
(one row per identity, hosts listed together).
"""
from __future__ import annotations

import hashlib
import re

from .discovery import Installation
from .layers.mcp import discover_mcp_entries
from .layers.skills import annotate_sync_state, discover_skills

_SAFE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_token(text: str, limit: int = 40) -> str:
    text = _SAFE.sub("-", str(text)).strip("-._")
    return (text or "x")[:limit]


def layer_role(kind: str, *parts: str) -> str:
    tokens = [safe_token(part) for part in parts if part]
    return f"{kind}." + ".".join(tokens or ["x"])


def is_layer_role(role: str) -> bool:
    return role.startswith("mcp.") or role.startswith("skill.")


def _short_fp(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def build_mcp_installations(home=None) -> dict[str, Installation]:
    """One Installation per unique MCP fingerprint (already installed only)."""
    tools: dict[str, Installation] = {}
    for entry in discover_mcp_entries(home):
        name = str(entry.get("id") or "server")
        hosts = [str(h) for h in (entry.get("hosts") or [entry.get("host") or "mcp"])]
        host_text = ",".join(hosts)
        fp = str(entry.get("fingerprint") or name)
        if len(hosts) == 1:
            role = layer_role("mcp", hosts[0], name)
        else:
            role = layer_role("mcp", name)
        if role in tools:
            role = layer_role("mcp", name, _short_fp(fp))
        paths = entry.get("paths") or [entry.get("path") or ""]
        label = f"MCP · {name}" + (f"（{host_text}）" if host_text else "")
        tools[role] = Installation(
            role,
            path=str(paths[0] if paths else ""),
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
    """One Installation per skill name (hosts collapsed); only real installs."""
    tools: dict[str, Installation] = {}
    by_name: dict[str, list] = {}
    for item in annotate_sync_state(discover_skills(home=home, names=None)):
        if item.skip_reason == "host system skill":
            continue
        if not item.fingerprint and item.fingerprint_kind in {"empty", "unreadable"}:
            continue
        by_name.setdefault(item.name.lower(), []).append(item)

    for _key, group in by_name.items():
        managed = [item for item in group if not item.is_symlink and not item.skip_reason]
        peers = managed or group
        hosts: list[str] = []
        for item in peers:
            if item.host not in hosts:
                hosts.append(item.host)
        primary = next((item for item in peers if not item.is_symlink), peers[0])
        states = {item.sync_state for item in peers}
        sync_state = "drift" if "drift" in states else (
            "in_sync" if "in_sync" in states else (primary.sync_state or "alone")
        )
        if len(hosts) == 1:
            role = layer_role("skill", hosts[0], primary.name)
        else:
            role = layer_role("skill", primary.name)
        host_text = ",".join(hosts)
        label = f"Skill · {primary.name}" + (f"（{host_text}）" if host_text else "")
        tools[role] = Installation(
            role,
            path=str(primary.path),
            source="local",
            update_supported=sync_state == "drift" and not primary.is_symlink,
            reason=primary.skip_reason or sync_state,
            label=label,
            group="agent",
            monitor="skill",
            spec={
                "kind": "skill",
                "fingerprint": primary.fingerprint,
                "sync_state": sync_state,
                "is_symlink": primary.is_symlink,
                "host": primary.host,
                "hosts": hosts,
                "name": primary.name,
            },
        )
    return tools
