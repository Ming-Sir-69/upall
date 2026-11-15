"""Optional AI vertical layers (MCP / Skill); wired by the engine later."""

from upall.layers.mcp import check_npx_package, iter_mcp_checks
from upall.layers.skills import (
    SyncAction,
    SyncPlan,
    SkillInstall,
    SkillRoot,
    WEBBRIDGE_NAMES,
    apply_sync_plan,
    check_skills,
    check_webbridge_skills,
    default_skill_roots,
    discover_skills,
    fingerprint_skill,
    plan_webbridge_sync,
)

__all__ = [
    "SkillInstall",
    "SkillRoot",
    "SyncAction",
    "SyncPlan",
    "WEBBRIDGE_NAMES",
    "apply_sync_plan",
    "check_npx_package",
    "check_skills",
    "check_webbridge_skills",
    "default_skill_roots",
    "discover_skills",
    "fingerprint_skill",
    "iter_mcp_checks",
    "plan_webbridge_sync",
]
