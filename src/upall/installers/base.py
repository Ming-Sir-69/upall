"""Shared helpers for install backends: stay inside a known root, delete safely."""
from __future__ import annotations

from pathlib import Path
import shutil
from typing import Iterable


def resolve_under(path: Path, root: Path) -> Path | None:
    """Return the resolved path when it stays under root; otherwise None."""
    try:
        resolved = path.resolve()
        root_resolved = root.resolve()
    except OSError:
        return None
    if resolved == root_resolved or root_resolved in resolved.parents:
        return resolved
    return None


def bounded_rmtree(path: Path, root: Path) -> bool:
    """Remove a directory only when it resolves under root. Returns True if removed."""
    target = resolve_under(path, root)
    if target is None or not target.exists() or target.is_symlink() or not target.is_dir():
        return False
    shutil.rmtree(target)
    return True


def bounded_unlink(path: Path, root: Path) -> bool:
    """Remove a file or symlink only when its parent stays under root."""
    try:
        parent = resolve_under(path.parent, root)
    except OSError:
        return False
    if parent is None:
        return False
    if not path.is_symlink() and not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def existing(paths: Iterable[Path]) -> list[Path]:
    return [path for path in paths if path.exists() or path.is_symlink()]
