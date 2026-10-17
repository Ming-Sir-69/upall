"""Bounded, control-safe terminal and file helpers."""
import os
from pathlib import Path
import re
import stat
import tempfile
import unicodedata

ANSI = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]")


def clean(text):
    return "".join(c for c in ANSI.sub("", str(text))
                   if c >= " " and not unicodedata.category(c).startswith("C"))


def width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in "WF" else 1
               for c in clean(text))


def fit(text, size):
    text = clean(text)
    if size <= 0:
        return ""
    if width(text) > size:
        result, used = "", 0
        for char in text:
            count = width(char)
            if used + count > size - 1:
                break
            result += char
            used += count
        text = result + "…"
    return text + " " * max(0, size - width(text))


def atomic(path, value):
    temp = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name + ".", delete=False) as file:
            temp = Path(file.name)
            file.write(value)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def private_directory(path):
    """Keep reports, locks and downloaded installers in an owner-only directory."""
    path = Path(path).expanduser().absolute()
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise PermissionError("UPALL state directory must belong to the current user")
        os.fchmod(descriptor, 0o700)
    finally:
        os.close(descriptor)
    return path


def state_root():
    """Apply the host override, then XDG rules; relative XDG paths are invalid."""
    override = os.environ.get("UPALL_LOG_ROOT")
    if override:
        return Path(override).expanduser().absolute()
    base = Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state")
    if not base.is_absolute():
        base = Path.home() / ".local/state"
    return base / "upall"


def tail(path, count=5, offset=0):
    try:
        with path.open("rb") as source:
            source.seek(0, 2)
            source.seek(max(0, source.tell() - 65536))
            lines = [clean(line).strip() for line in source.read().decode("utf-8", "replace").replace("\r", "\n").splitlines()]
        lines = [line for line in lines if line]
        end = max(0, len(lines) - offset)
        return lines[max(0, end - count):end]
    except OSError:
        return []
