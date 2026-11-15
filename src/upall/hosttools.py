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

from .discovery import DEFAULT_MONITORS, GROUPS, MONITORS, TOOLS, Installation
from .util import atomic

ID = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")


class ConfigError(Exception):
    pass


def _config_base():
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) if base and Path(base).is_absolute() else Path.home() / ".config"


def config_path():
    explicit = os.environ.get("UPALL_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("UPALL_SEARCH_PATH"):
        return None  # isolated runs never read the real host config
    return _config_base() / "upall/tools.json"


def monitors_path():
    """Optional ~/.config/upall/monitors.json (or UPALL_MONITORS_CONFIG)."""
    explicit = os.environ.get("UPALL_MONITORS_CONFIG")
    if explicit:
        return Path(explicit).expanduser()
    if os.environ.get("UPALL_SEARCH_PATH"):
        return None
    return _config_base() / "upall/monitors.json"


def _argv(value, name):
    if (not isinstance(value, list) or not value or
            not all(isinstance(part, str) and part for part in value)):
        raise ConfigError(f"{name} 必须是非空字符串数组")
    first = str(Path(value[0]).expanduser())
    if not Path(first).is_absolute():
        raise ConfigError(f"{name} 的程序必须是绝对路径")
    return [first, *value[1:]]


def _owner_only(path):
    info = path.stat()
    if info.st_uid != os.getuid() or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError(f"{path} 必须属于当前用户且不可被他人写入")


def _read_object(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as error:
        raise ConfigError(f"{path} 无法读取：{error}") from None
    if not isinstance(data, dict):
        raise ConfigError(f"{path} 顶层必须是对象")
    return data


def _parse_enabled_monitors(value, source):
    """Accept a list of kinds, or {\"enabled\": [...]} / {kind: bool} maps."""
    if isinstance(value, dict):
        if "enabled" in value:
            value = value["enabled"]
        else:
            unknown = set(value) - set(MONITORS)
            if unknown:
                raise ConfigError(f"{source}: 未知监测类型 {', '.join(sorted(unknown))}")
            enabled = {kind for kind, on in value.items() if on}
            bad = enabled - set(MONITORS)
            if bad:
                raise ConfigError(f"{source}: 未知监测类型 {', '.join(sorted(bad))}")
            return frozenset(enabled)
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ConfigError(f"{source}: monitors 必须是非空类型名数组")
    unknown = set(value) - set(MONITORS)
    if unknown:
        raise ConfigError(f"{source}: 未知监测类型 {', '.join(sorted(unknown))}")
    return frozenset(value)


def load_monitors(path=None, tools_config=None):
    """Return enabled monitor kinds; missing config → DEFAULT_MONITORS.

    Precedence: dedicated monitors.json (or path) > tools.json \"monitors\" field > defaults.
    Isolated runs (UPALL_SEARCH_PATH) skip user files unless an explicit path is passed.
    """
    if path is not None:
        if not path.exists():
            return frozenset(DEFAULT_MONITORS)
        _owner_only(path)
        data = _read_object(path)
        payload = data["enabled"] if "enabled" in data else data
        return _parse_enabled_monitors(payload, str(path))

    dedicated = monitors_path()
    if dedicated is not None and dedicated.exists():
        _owner_only(dedicated)
        data = _read_object(dedicated)
        payload = data["enabled"] if "enabled" in data else data
        return _parse_enabled_monitors(payload, str(dedicated))

    tools_path = tools_config if tools_config is not None else config_path()
    if tools_path is not None and tools_path.exists():
        _owner_only(tools_path)
        data = _read_object(tools_path)
        if "monitors" in data:
            return _parse_enabled_monitors(data["monitors"], f"{tools_path} monitors")
    return frozenset(DEFAULT_MONITORS)


def save_monitors(enabled, path=None):
    """Persist enabled monitor kinds to monitors.json (owner-only, 0600).

    Isolated runs (UPALL_SEARCH_PATH without UPALL_MONITORS_CONFIG) cannot write.
    """
    enabled = frozenset(enabled)
    if not enabled:
        raise ConfigError("至少开启一种监测类型")
    unknown = enabled - set(MONITORS)
    if unknown:
        raise ConfigError("未知监测类型：" + ", ".join(sorted(unknown)))
    target = Path(path).expanduser() if path is not None else monitors_path()
    if target is None:
        raise ConfigError("隔离运行无法写入监测配置；请设置 UPALL_MONITORS_CONFIG")
    target = target.absolute()
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if target.exists():
        _owner_only(target)
    payload = {"enabled": [kind for kind in MONITORS if kind in enabled]}
    atomic(target, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    os.chmod(target, 0o600)
    _owner_only(target)
    return frozenset(payload["enabled"])


def load(path=None):
    """Return (tools, preserve, after_update); raise ConfigError.

    tools: {id: Installation}; preserve: {role: [Path]}; after_update: {role: argv}.
    """
    path = config_path() if path is None else path
    if path is None or not path.exists():
        return {}, {}, {}
    _owner_only(path)
    data = _read_object(path)
    tools = {}
    for item in data.get("tools", []):
        if not isinstance(item, dict) or not ID.fullmatch(str(item.get("id", ""))):
            raise ConfigError("tools[].id 只能是小写字母、数字和连字符")
        role = item["id"]
        group = item.get("group", "host")
        if group not in GROUPS:
            raise ConfigError(f"{role}: group 只能是 {', '.join(GROUPS)}")
        monitor = item.get("monitor", "runtime")
        if monitor not in MONITORS:
            raise ConfigError(f"{role}: monitor 只能是 {', '.join(MONITORS)}")
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
            label=str(item.get("label") or TOOLS.get(role, role)), group=group,
            monitor=monitor, spec=spec)
    preserve = {}
    for role, paths in (data.get("preserve") or {}).items():
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
            raise ConfigError(f"preserve.{role} 必须是路径数组")
        preserve[role] = [Path(p).expanduser() for p in paths]
    hooks = {}
    for role, argv in (data.get("after_update") or {}).items():
        hooks[role] = _argv(argv, f"after_update.{role}")
    return tools, preserve, hooks
