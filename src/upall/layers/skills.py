"""Read-only Skill discovery and vendor multi-host sync planning.

Focus: vendor-bundled skills copied into several host skill dirs (Kimi WebBridge).
Check phase only scans and fingerprints; updates are returned as a plan for the
engine/Lead to apply after the user confirms. Symlinked / self-maintained skills
are listed but never proposed for overwrite. Skill specs have no version field —
comparison uses content fingerprints only (no invented semver).
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
import hashlib
import os
from pathlib import Path
import re
import shutil
from typing import Iterable

# Directory names we treat as the WebBridge vendor skill (and close aliases).
WEBBRIDGE_NAMES = frozenset({"kimi-webbridge", "webbridge", "kimi-browser-extension"})

_SKILL_DIR_NAMES = {"skills", "skills-cursor"}

# Prefer these hosts when choosing a sync source among equal candidates.
_SOURCE_HOST_RANK = {
    "kimi-code": 0,
    "claude": 1,
    "codex": 2,
    "hermes": 3,
    "agents": 4,
    "cursor": 5,
    "cursor-builtin": 6,
}

_FRONTMATTER_NAME = re.compile(r"(?m)^name:\s*[\"']?([A-Za-z0-9._-]+)[\"']?\s*$")
_MAX_FINGERPRINT_BYTES = 32 * 1024 * 1024  # per file; skip oversized blobs
_MAX_TREE_FILES = 2000


@dataclass(frozen=True)
class SkillRoot:
    host: str
    path: Path


@dataclass(frozen=True)
class SkillInstall:
    name: str
    path: Path
    host: str
    fingerprint: str
    fingerprint_kind: str  # "skill_md" | "tree" | "empty" | "unreadable"
    is_symlink: bool = False
    link_target: str = ""
    project_link: bool = False
    sync_state: str = ""  # in_sync | drift | alone | skip
    skip_reason: str = ""
    skill_md_fingerprint: str = ""

    def as_dict(self):
        data = asdict(self)
        data["path"] = str(self.path)
        return data


@dataclass(frozen=True)
class SyncAction:
    kind: str  # "replace_tree" | "skip"
    destination: Path
    source: Path | None = None
    reason: str = ""
    host: str = ""

    def as_dict(self):
        return {
            "kind": self.kind,
            "destination": str(self.destination),
            "source": str(self.source) if self.source is not None else None,
            "reason": self.reason,
            "host": self.host,
        }


@dataclass(frozen=True)
class SyncPlan:
    skill_name: str
    source: Path | None
    source_fingerprint: str
    actions: list[SyncAction] = field(default_factory=list)
    installs: list[SkillInstall] = field(default_factory=list)

    def as_dict(self):
        return {
            "skill_name": self.skill_name,
            "source": str(self.source) if self.source is not None else None,
            "source_fingerprint": self.source_fingerprint,
            "actions": [action.as_dict() for action in self.actions],
            "installs": [item.as_dict() for item in self.installs],
        }

    @property
    def needs_sync(self):
        return any(action.kind == "replace_tree" for action in self.actions)


def _host_from_skill_root(path: Path, home: Path) -> str:
    if path.name == "skills-cursor":
        return "cursor-builtin"
    try:
        rel = path.resolve().relative_to(home.resolve())
        parts = list(rel.parts)
    except ValueError:
        parts = list(path.parts)
    for part in parts:
        if part.startswith(".") and part not in {".config", ".local", ".cache"}:
            return part.lstrip(".") or "skill"
    if path.name.startswith("skills"):
        parent = path.parent.name.lstrip(".")
        return parent or path.name
    return path.name


def find_skill_roots(home: Path | None = None, project_root: Path | None = None) -> list[SkillRoot]:
    """Find directories that structurally hold skills (child dirs with SKILL.md)."""
    home = Path(home or Path.home()).expanduser()
    found: list[SkillRoot] = []
    seen: set[Path] = set()

    def consider(path: Path, host: str | None = None):
        if not path.is_dir():
            return
        try:
            key = path.resolve()
        except OSError:
            key = path
        if key in seen:
            return
        # Must contain at least one installed skill (SKILL.md child).
        try:
            for child in path.iterdir():
                if child.name.startswith("."):
                    continue
                if (child / "SKILL.md").exists():
                    break
            else:
                return
        except OSError:
            return
        seen.add(key)
        found.append(SkillRoot(host or _host_from_skill_root(path, home), path))

    try:
        for child in home.iterdir():
            if not child.is_dir() or not child.name.startswith("."):
                continue
            # .claude/skills, .codex/skills, .kimi-code/skills, .cursor/skills-cursor …
            for name in _SKILL_DIR_NAMES:
                consider(child / name)
            # one nested level: .foo/bar/skills
            try:
                for sub in child.iterdir():
                    if sub.is_dir() and not sub.name.startswith("."):
                        for name in _SKILL_DIR_NAMES:
                            consider(sub / name)
            except OSError:
                pass
    except OSError:
        pass

    if project_root is not None:
        project = Path(project_root).expanduser()
        consider(project / ".claude" / "skills", host="project-claude")
        consider(project / ".agents" / "skills", host="project-agents")
        consider(project / ".cursor" / "skills", host="project-cursor")
        consider(project / ".cursor" / "skills-cursor", host="project-cursor")

    return found


def default_skill_roots(home: Path | None = None, project_root: Path | None = None) -> list[SkillRoot]:
    """Skill roots discovered by structure (dirs that actually contain SKILL.md)."""
    return find_skill_roots(home=home, project_root=project_root)


def is_webbridge_name(name: str) -> bool:
    lowered = (name or "").strip().lower()
    if lowered in WEBBRIDGE_NAMES:
        return True
    return "webbridge" in lowered


def skill_name_from_dir(path: Path) -> str:
    """Prefer directory name; fall back to SKILL.md frontmatter `name:` if present."""
    name = path.name
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        return name
    try:
        text = skill_md.read_text(encoding="utf-8", errors="replace")[:4000]
    except OSError:
        return name
    match = _FRONTMATTER_NAME.search(text)
    return match.group(1) if match else name


def fingerprint_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            remaining = _MAX_FINGERPRINT_BYTES
            while remaining > 0:
                chunk = handle.read(min(65536, remaining))
                if not chunk:
                    break
                digest.update(chunk)
                remaining -= len(chunk)
    except OSError:
        return ""
    return digest.hexdigest()


def fingerprint_tree(path: Path) -> str:
    """Stable sha256 over relative paths + file digests (symlinked files skipped)."""
    digest = hashlib.sha256()
    root = path.resolve() if path.exists() and not path.is_symlink() else path
    entries: list[tuple[str, str]] = []
    count = 0
    try:
        for current, dirnames, filenames in os.walk(root, followlinks=False):
            dirnames[:] = sorted(name for name in dirnames if name not in {".git", "__pycache__", ".DS_Store"})
            current_path = Path(current)
            for filename in sorted(filenames):
                if filename == ".DS_Store":
                    continue
                count += 1
                if count > _MAX_TREE_FILES:
                    digest.update(b"truncated")
                    break
                file_path = current_path / filename
                if file_path.is_symlink():
                    continue
                relative = file_path.relative_to(root).as_posix()
                entries.append((relative, fingerprint_file(file_path) or "unreadable"))
            if count > _MAX_TREE_FILES:
                break
    except OSError:
        return ""
    for relative, file_hash in entries:
        digest.update(relative.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest() if entries else ""


def fingerprint_skill(path: Path) -> tuple[str, str, str]:
    """Return (fingerprint, kind, skill_md_fingerprint). Prefer tree; fall back to SKILL.md."""
    skill_md = path / "SKILL.md"
    skill_md_hash = fingerprint_file(skill_md) if skill_md.is_file() and not skill_md.is_symlink() else ""
    if path.is_dir() and not path.is_symlink():
        tree = fingerprint_tree(path)
        if tree:
            return tree, "tree", skill_md_hash
    if skill_md_hash:
        return skill_md_hash, "skill_md", skill_md_hash
    if skill_md.is_file():
        # Symlinked SKILL.md or unreadable tree: still report skill_md when possible.
        linked = fingerprint_file(skill_md)
        if linked:
            return linked, "skill_md", linked
    return "", "empty" if path.exists() else "unreadable", skill_md_hash


def _looks_project_link(link: Path, target: Path) -> bool:
    """Heuristic: symlink leaving the host skills root into a project-like tree."""
    try:
        resolved = target if target.is_absolute() else (link.parent / target)
        resolved = resolved.resolve()
    except OSError:
        return True
    parts = {part.lower() for part in resolved.parts}
    if "skills" in parts and any(marker in parts for marker in ("项目库", "projects", "src", "repo", "repos")):
        return True
    # Outside home host-config trees → treat as project/self-maintained.
    home = Path.home()
    try:
        relative = resolved.relative_to(home)
    except ValueError:
        return True
    top = relative.parts[0] if relative.parts else ""
    if top.startswith(".") and top not in {".config", ".local", ".cache", ".Trash"}:
        # Still under a host config tree (e.g. ~/.agents/skills via relative link).
        return ".git" in parts or "项目库" in resolved.as_posix()
    return True


def _skip_reason(path: Path, is_symlink: bool, project_link: bool) -> str:
    if is_symlink and project_link:
        return "symlink to project / self-maintained"
    if is_symlink:
        return "symlink skill (list only)"
    # Codex ships system skills under .system/
    if ".system" in path.parts:
        return "host system skill"
    return ""


def discover_skills(
    roots: Iterable[SkillRoot] | None = None,
    *,
    names: Iterable[str] | None = None,
    home: Path | None = None,
    project_root: Path | None = None,
) -> list[SkillInstall]:
    """READ-ONLY scan of skill roots. Missing roots are skipped silently."""
    roots = list(roots) if roots is not None else default_skill_roots(home=home, project_root=project_root)
    wanted = None
    if names is not None:
        wanted = {name.strip().lower() for name in names if name and name.strip()}
    found: list[SkillInstall] = []
    seen: set[Path] = set()
    for root in roots:
        if not root.path.is_dir():
            continue
        try:
            children = sorted(root.path.iterdir(), key=lambda item: item.name.lower())
        except OSError:
            continue
        for child in children:
            if child.name.startswith("."):
                continue
            # A skill is a directory (or symlink-to-dir) that directly contains SKILL.md.
            try:
                if not (child / "SKILL.md").exists():
                    continue
            except OSError:
                continue
            try:
                key = child.resolve() if not child.is_symlink() else child
            except OSError:
                key = child
            if key in seen:
                continue
            seen.add(key)
            name = skill_name_from_dir(child)
            if wanted is not None and not _name_wanted(name, child.name, wanted):
                continue
            is_link = child.is_symlink()
            link_target = ""
            project_link = False
            if is_link:
                try:
                    link_target = os.readlink(child)
                    project_link = _looks_project_link(child, Path(link_target))
                except OSError:
                    link_target = ""
                    project_link = True
            fingerprint, kind, skill_md_hash = fingerprint_skill(child)
            # For symlinks, fingerprint the target tree when readable (report only).
            if is_link:
                try:
                    target_path = Path(os.path.realpath(child))
                    if target_path.is_dir():
                        fingerprint, kind, skill_md_hash = fingerprint_skill(target_path)
                except OSError:
                    pass
            reason = _skip_reason(child, is_link, project_link)
            found.append(SkillInstall(
                name=name,
                path=child,
                host=root.host,
                fingerprint=fingerprint,
                fingerprint_kind=kind,
                is_symlink=is_link,
                link_target=link_target,
                project_link=project_link,
                sync_state="skip" if reason else "",
                skip_reason=reason,
                skill_md_fingerprint=skill_md_hash,
            ))
    return found


def _name_wanted(name: str, dirname: str, wanted: set[str]) -> bool:
    candidates = {name.lower(), dirname.lower()}
    if candidates & wanted:
        return True
    if any(is_webbridge_name(item) for item in wanted):
        return any(is_webbridge_name(item) for item in candidates)
    return False


def annotate_sync_state(installs: list[SkillInstall]) -> list[SkillInstall]:
    """Set sync_state: skip / alone / in_sync / drift among non-skipped peers of the same name."""
    by_name: dict[str, list[SkillInstall]] = {}
    for item in installs:
        by_name.setdefault(item.name.lower(), []).append(item)
    annotated: list[SkillInstall] = []
    for group in by_name.values():
        managed = [item for item in group if not item.skip_reason and not item.is_symlink]
        fingerprints = {item.fingerprint for item in managed if item.fingerprint}
        for item in group:
            if item.skip_reason or item.is_symlink:
                annotated.append(replace(item, sync_state="skip",
                                         skip_reason=item.skip_reason or "symlink skill (list only)"))
                continue
            if len(managed) <= 1:
                annotated.append(replace(item, sync_state="alone"))
            elif len(fingerprints) <= 1:
                annotated.append(replace(item, sync_state="in_sync"))
            else:
                annotated.append(replace(item, sync_state="drift"))
    return annotated


def check_skills(
    *,
    names: Iterable[str] | None = None,
    roots: Iterable[SkillRoot] | None = None,
    home: Path | None = None,
    project_root: Path | None = None,
) -> list[SkillInstall]:
    """Discover + annotate sync_state. Default names: WebBridge aliases only."""
    if names is None:
        names = WEBBRIDGE_NAMES
    return annotate_sync_state(discover_skills(roots, names=names, home=home, project_root=project_root))


def check_webbridge_skills(
    *,
    roots: Iterable[SkillRoot] | None = None,
    home: Path | None = None,
    project_root: Path | None = None,
) -> list[SkillInstall]:
    """Convenience: only Kimi WebBridge / webbridge installs."""
    return check_skills(names=WEBBRIDGE_NAMES, roots=roots, home=home, project_root=project_root)


def _pick_source(managed: list[SkillInstall], preferred: Path | None) -> SkillInstall | None:
    if preferred is not None:
        preferred = Path(preferred)
        for item in managed:
            if item.path == preferred or item.path.resolve() == preferred.resolve():
                return item
        # Preferred path may be outside the scanned set (fresh unpack); synthesize.
        if preferred.is_dir() and (preferred / "SKILL.md").exists():
            fingerprint, kind, skill_md_hash = fingerprint_skill(preferred)
            return SkillInstall(
                name=skill_name_from_dir(preferred),
                path=preferred,
                host="source",
                fingerprint=fingerprint,
                fingerprint_kind=kind,
                skill_md_fingerprint=skill_md_hash,
                sync_state="alone",
            )
    if not managed:
        return None
    # Prefer the fingerprint shared by the most copies; break ties by host rank then path.
    counts: dict[str, int] = {}
    for item in managed:
        if item.fingerprint:
            counts[item.fingerprint] = counts.get(item.fingerprint, 0) + 1
    best_fp = max(counts, key=lambda key: (counts[key], key), default="")
    candidates = [item for item in managed if item.fingerprint == best_fp] or list(managed)
    candidates.sort(key=lambda item: (_SOURCE_HOST_RANK.get(item.host, 99), str(item.path)))
    return candidates[0]


def plan_webbridge_sync(
    installs: list[SkillInstall] | None = None,
    *,
    source: Path | None = None,
    skill_name: str = "kimi-webbridge",
    home: Path | None = None,
    project_root: Path | None = None,
    roots: Iterable[SkillRoot] | None = None,
) -> SyncPlan:
    """Return copy/skip actions for Lead/engine — does not mutate the filesystem.

    Typical wiring after a confirmed `kimi-webbridge` upgrade:
      installs = check_webbridge_skills()
      plan = plan_webbridge_sync(installs, source=preferred_fresh_copy)
      # apply only after user confirms (Space/1); see apply_sync_plan(..., confirm=True)
    """
    if installs is None:
        installs = check_webbridge_skills(roots=roots, home=home, project_root=project_root)
    else:
        installs = annotate_sync_state(list(installs))

    relevant = [
        item for item in installs
        if is_webbridge_name(item.name) or is_webbridge_name(item.path.name)
        or item.name.lower() == skill_name.lower() or item.path.name.lower() == skill_name.lower()
    ]
    if not relevant:
        relevant = installs

    managed = [item for item in relevant if not item.is_symlink and not item.skip_reason]
    skipped = [item for item in relevant if item.is_symlink or item.skip_reason]
    chosen = _pick_source(managed, source)
    actions: list[SyncAction] = []

    for item in skipped:
        actions.append(SyncAction(
            kind="skip",
            destination=item.path,
            source=None,
            reason=item.skip_reason or "symlink / self-maintained",
            host=item.host,
        ))

    if chosen is None:
        return SyncPlan(skill_name=skill_name, source=None, source_fingerprint="",
                        actions=actions, installs=relevant)

    for item in managed:
        if item.path == chosen.path:
            continue
        if item.fingerprint and item.fingerprint == chosen.fingerprint:
            actions.append(SyncAction(
                kind="skip",
                destination=item.path,
                source=chosen.path,
                reason="already in sync",
                host=item.host,
            ))
            continue
        actions.append(SyncAction(
            kind="replace_tree",
            destination=item.path,
            source=chosen.path,
            reason="fingerprint drift" if item.fingerprint else "empty or unreadable copy",
            host=item.host,
        ))

    return SyncPlan(
        skill_name=skill_name,
        source=chosen.path,
        source_fingerprint=chosen.fingerprint,
        actions=actions,
        installs=relevant,
    )


def apply_sync_plan(plan: SyncPlan, *, confirm: bool = False) -> list[Path]:
    """Opt-in apply. Refuses unless confirm=True. Never touches symlink destinations."""
    if not confirm:
        raise RuntimeError("refusing to apply skill sync plan without confirm=True")
    updated: list[Path] = []
    for action in plan.actions:
        if action.kind != "replace_tree":
            continue
        if action.source is None:
            continue
        destination = Path(action.destination)
        source = Path(action.source)
        if destination.is_symlink() or source.is_symlink():
            continue
        if not source.is_dir() or not (source / "SKILL.md").is_file():
            raise RuntimeError(f"sync source missing SKILL.md: {source}")
        parent = destination.parent
        parent.mkdir(parents=True, exist_ok=True)
        staging = parent / f".upall-skill-sync-{destination.name}"
        if staging.exists():
            shutil.rmtree(staging)
        try:
            shutil.copytree(source, staging, symlinks=False, dirs_exist_ok=False)
            if destination.exists():
                if destination.is_symlink():
                    raise RuntimeError(f"refusing to overwrite symlink skill: {destination}")
                shutil.rmtree(destination)
            staging.rename(destination)
            updated.append(destination)
        finally:
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)
    return updated
