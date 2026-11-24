"""Shared npm --global --prefix install backend.

All npm-backed tools (Codex, Gemini, Agent Desktop, …) share this path.
Per-tool customization is limited to allow-scripts / optional extras in
NPM_INSTALL_OPTIONS; layout recovery stays identical.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .base import bounded_rmtree, bounded_unlink, resolve_under

# Role → npm install flag customization. Empty means plain `npm i -g --prefix`.
NPM_INSTALL_OPTIONS = {
    "claude": {
        "ignore_scripts": False,
        "include_optional": True,
        "allow_scripts": "@anthropic-ai/claude-code",
    },
    "mcode": {
        "ignore_scripts": False,
        "include_optional": True,
        "allow_scripts": "@minimax-ai/code,better-sqlite3",
    },
    "agent-desktop": {
        "ignore_scripts": False,
        "include_optional": True,
        "allow_scripts": "agent-desktop",
    },
}

_LAYOUT_ERROR = re.compile(
    r"\b(?:ENOTEMPTY|EEXIST)\b|directory not empty|File exists:",
    re.I,
)


def package_slug(package: str) -> str:
    """npm staging rename uses .<slug>-<random> next to the live package."""
    if package.startswith("@"):
        scope, name = package[1:].split("/", 1)
        return f"{scope}-{name}"
    return package


def node_modules(prefix: Path | str) -> Path:
    return Path(prefix) / "lib" / "node_modules"


def package_dir(prefix: Path | str, package: str) -> Path:
    return node_modules(prefix).joinpath(*package.split("/"))


def staging_dirs(prefix: Path | str, package: str) -> list[Path]:
    root = node_modules(prefix)
    if not root.is_dir():
        return []
    marker = f".{package_slug(package)}-"
    return sorted(
        path for path in root.iterdir()
        if path.name.startswith(marker) and (path.is_dir() or path.is_symlink())
    )


def _bin_field(metadata: dict) -> set[str]:
    binary = metadata.get("bin")
    if isinstance(binary, str):
        name = metadata.get("name")
        if isinstance(name, str) and name:
            return {name.rsplit("/", 1)[-1]}
        return set()
    if isinstance(binary, dict):
        return {str(key) for key in binary if key}
    return set()


def _read_package_json(path: Path) -> dict:
    try:
        data = json.loads((path / "package.json").read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def bin_names(prefix: Path | str, package: str) -> set[str]:
    names = {package.rsplit("/", 1)[-1]}
    for candidate in (package_dir(prefix, package), *staging_dirs(prefix, package)):
        names |= _bin_field(_read_package_json(candidate))
    return names


def is_layout_error(message: str) -> bool:
    return bool(_LAYOUT_ERROR.search(str(message)))


def prepare(prefix: Path | str, package: str) -> list[str]:
    """Clear leftover npm rename dirs and broken prefix/bin links for this package.

    npm upgrades rename lib/node_modules/<pkg> → .<slug>-<id>. A previous failed
    upgrade leaves that directory behind and triggers ENOTEMPTY on the next run;
    hand-made bin symlinks into the staging tree then fail with EEXIST.
    """
    prefix = Path(prefix)
    modules = node_modules(prefix)
    bin_dir = prefix / "bin"
    notes: list[str] = []
    if not modules.is_dir():
        return notes

    names = bin_names(prefix, package)
    staging = staging_dirs(prefix, package)
    staging_resolved = []
    for path in staging:
        resolved = resolve_under(path, modules)
        if resolved is None:
            continue
        staging_resolved.append(resolved)
        if bounded_rmtree(path, modules):
            notes.append(f"已清理 npm 残留目录：{path.name}")

    if not bin_dir.is_dir():
        return notes

    staging_names = {path.name for path in staging_resolved}
    for name in sorted(names):
        link = bin_dir / name
        if not link.is_symlink() and not link.exists():
            continue
        remove = False
        if link.is_symlink():
            raw = link.readlink()
            target = raw if raw.is_absolute() else link.parent / raw
            # Broken link, or still pointing into a staging rename we just removed
            # / that still matches this package's staging prefix.
            if not target.exists():
                remove = True
            else:
                resolved = resolve_under(target, modules)
                if resolved is not None and (
                    resolved.name in staging_names
                    or any(part.startswith(f".{package_slug(package)}-") for part in resolved.parts)
                ):
                    remove = True
        if remove and bounded_unlink(link, prefix):
            notes.append(f"已移除失效命令链接：bin/{name}")
    return notes


def build_install_command(
    manager: str,
    prefix: Path | str,
    package: str,
    version: str,
    *,
    role: str = "",
    options: dict | None = None,
) -> list[str]:
    command = [manager, "install", "--global", "--prefix", str(prefix), f"{package}@{version}"]
    opts = options if options is not None else NPM_INSTALL_OPTIONS.get(role, {})
    if role == "dsh":
        command.append("--engine-strict")
    if opts.get("ignore_scripts") is False:
        command.append("--ignore-scripts=false")
    if opts.get("include_optional"):
        command.append("--include=optional")
    allow = opts.get("allow_scripts")
    if allow:
        command.append(f"--allow-scripts={allow}")
    return command
