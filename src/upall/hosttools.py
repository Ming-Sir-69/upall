"""Host-defined tools and local-modification records (owner-only JSON config).

The config describes what the host itself maintains, so UPALL can tell
"ours" from "theirs" without diffing whole releases:

{
  "tools": [
    {"id": "mole", "label": "Mole", "group": "app",
     "check": ["/abs/adapter", "check"], "update": ["/abs/adapter", "update"], "timeout": 1800},
    {"id": "some-fork", "label": "Some Fork", "group": "host", "kind": "git",
     "repo": "/abs/checkout", "remote": "origin", "branch": "main"}
  ],
  "preserve": {"some-tool": ["~/.config/some-tool/custom.json"]},
  "after_update": {"kimi-webbridge": ["/abs/rebuild-our-skill-entry", "--quiet"]}
}

A command tool's check prints one JSON object:
  {"current": "1.0.0", "latest": "1.1.0",
   "overlay": {"local": 2, "absorbed": 1, "conflict": false, "note": "..."},
   "manual": "reason when it must not be updated automatically"}

"preserve" lists customised copies (skills, configs) that an upstream update
would overwrite; UPALL snapshots them before the update and puts them back.
"after_update" runs a host command once a tool's update succeeded, to re-apply
a modification on top of the new release (only our change stays ours, the
rest follows upstream).
"""
import json
import os
from pathlib import Path
import re
import stat

from .discovery import GROUPS, TOOLS, Installation

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


class ConfigError(Exception):
    pass


def config_path():
    explicit = os.environ.get("UPALL_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("UPALL_SEARCH_PATH"):
        return None  # isolated runs never read the real host config
    base = os.environ.get("XDG_CONFIG_HOME")
    base = Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"
    return base / "upall/tools.json"


def _argv(value, name):
    if (not isinstance(value, list) or not value or
            not all(isinstance(part, str) and part for part in value)):
        raise ConfigError(f"{name} 必须是非空字符串数组")
    first = str(Path(value[0]).expanduser())
    if not Path(first).is_absolute():
        raise ConfigError(f"{name} 的程序必须是绝对路径")
    return [first, *value[1:]]


def load(path=None):
    """Return (tools, preserve, after_update); raise ConfigError.

    tools: {id: Installation}; preserve: {role: [Path]}; after_update: {role: argv}.
    """
    path = config_path() if path is None else path
    if path is None or not path.exists():
        return {}, {}, {}
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError(f"{path} 必须属于当前用户且不可被他人写入")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise ConfigError(f"{path} 无法读取：{error}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} 顶层必须是对象")
    tools = {}
    for item in data.get("tools", []):
        if not isinstance(item, dict) or not ID.fullmatch(str(item.get("id", ""))):
            raise ConfigError("tools[].id 只能是小写字母、数字和连字符")
        role = item["id"]
        group = item.get("group", "host")
        if group not in GROUPS:
            raise ConfigError(f"{role}: group 只能是 {', '.join(GROUPS)}")
        kind = item.get("kind", "command")
        timeout = item.get("timeout", 1800)
        if not isinstance(timeout, int) or not 10 <= timeout <= 7200:
            raise ConfigError(f"{role}: timeout 需在 10–7200 秒")
        spec = {"kind": kind, "timeout": timeout}
        if kind == "command":
            spec["check"] = _argv(item.get("check"), f"{role}.check")
            spec["update"] = _argv(item.get("update"), f"{role}.update")
            # Show the adapter script rather than its interpreter.
            path_hint = next((part for part in reversed(spec["check"])
                              if part.startswith("/") and Path(part).exists()), spec["check"][0])
        elif kind == "git":
            repo = Path(str(item.get("repo", ""))).expanduser()
            if not repo.is_absolute():
                raise ConfigError(f"{role}: repo 必须是绝对路径")
            spec.update(repo=str(repo), remote=str(item.get("remote", "origin")),
                        branch=str(item.get("branch", "main")))
            if "after_update" in item:
                spec["after_update"] = _argv(item["after_update"], f"{role}.after_update")
            path_hint = str(repo)
        else:
            raise ConfigError(f"{role}: kind 只能是 command 或 git")
        present = Path(path_hint).exists()
        tools[role] = Installation(
            role, path_hint if present else "", "host" if kind == "command" else "git",
            update_supported=present, reason="" if present else "配置的路径不存在",
            label=str(item.get("label") or TOOLS.get(role, role)), group=group, spec=spec)
    preserve = {}
    for role, paths in (data.get("preserve") or {}).items():
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ConfigError(f"preserve.{role} 必须是路径数组")
        preserve[role] = [Path(p).expanduser() for p in paths]
    hooks = {}
    for role, argv in (data.get("after_update") or {}).items():
        hooks[role] = _argv(argv, f"after_update.{role}")
    return tools, preserve, hooks
