"""Known AI tools and bounded installation discovery; never install during detection."""
from dataclasses import dataclass, asdict
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil

TOOLS = {
    "claude": "Claude Code", "codex": "Codex", "kimi": "Kimi Code", "hermes": "Hermes",
    "gemini": "Gemini CLI", "grok": "Grok Build", "opencode": "OpenCode",
    "openclaw": "OpenClaw", "pi": "Pi", "mcode": "MiniMax Code",
    "claude-desktop": "Claude Desktop", "chatgpt": "ChatGPT",
}
DESKTOP_APPS = {"claude-desktop": ("Claude Desktop", "Claude"), "chatgpt": ("ChatGPT", "ChatGPT")}
DEMO_ROLES = ("claude", "codex", "kimi", "hermes")
PACKAGES = {
    "claude": ("@anthropic-ai/claude-code",), "codex": ("@openai/codex",),
    "gemini": ("@google/gemini-cli",), "grok": ("@xai-official/grok",),
    "opencode": ("opencode-ai", "@opencode/cli"), "openclaw": ("openclaw",),
    "pi": ("@earendil-works/pi-coding-agent", "@mariozechner/pi-coding-agent"),
    "mcode": ("@minimax-ai/code",),
}
SOURCE_LABELS = {
    "npm": "npm", "brew": "Homebrew", "native": "官方原生", "script": "官方脚本",
    "source": "源码安装", "desktop": "桌面应用", "local": "项目依赖",
    "unknown": "来源待确认", "missing": "未安装", "demo": "演示",
}
BREW_PACKAGES = {
    "claude": {"claude-code", "claude-code@latest"}, "codex": {"codex"},
    "gemini": {"gemini-cli"}, "grok": {"grok"}, "opencode": {"opencode"},
    "openclaw": {"openclaw"}, "pi": {"pi", "pi-coding-agent"}, "mcode": {"minimax-code"},
}


@dataclass
class Installation:
    role: str
    path: str = ""
    source: str = "missing"
    package: str = ""
    prefix: str = ""
    manager: str = ""
    cask: bool = False
    channel: str = "latest"
    root: str = ""
    version: str = ""
    update_supported: bool = False
    reason: str = ""

    @property
    def installed(self):
        return bool(self.path)

    def public(self):
        return dict(asdict(self), installed=self.installed, source_label=SOURCE_LABELS[self.source])


def read_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def classify(role, executable, home=None):
    home = Path.home() if home is None else Path(home)
    entry = Path(executable).absolute()
    target = entry.resolve()
    result = Installation(role, str(entry), source="unknown", reason="已找到命令，安装来源未确认")
    if role == "claude":
        config = Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude")
        settings = {}
        for file in (config / "settings.json", config / "settings.local.json",
                     Path("/Library/Application Support/ClaudeCode/managed-settings.json")):
            settings.update(read_json(file))
        if settings.get("autoUpdatesChannel") in ("stable", "latest"):
            result.channel = settings["autoUpdatesChannel"]
    parts = target.parts

    # Installer-owned directories are not ordinary global npm prefixes.
    if role == "mcode" and (
        ".minimax-code" in target.parts or
        (os.environ.get("MCODE_INSTALL_DIR") and target.is_relative_to(Path(os.environ["MCODE_INSTALL_DIR"]).expanduser().resolve()))
    ):
        root = Path(os.environ["MCODE_INSTALL_DIR"]).expanduser() if os.environ.get("MCODE_INSTALL_DIR") else Path(*parts[:parts.index(".minimax-code") + 1])
        result.source, result.root = "script", str(root)
        result.update_supported, result.reason = True, ""
        return result

    for parent in list(target.parents)[:8]:
        metadata = read_json(parent / "package.json")
        name = metadata.get("name")
        if name not in PACKAGES.get(role, ()):
            continue
        result.package = name
        node_modules = next((p for p in parent.parents if p.name == "node_modules"), None)
        if node_modules and node_modules.parent.name == "lib":
            prefix = node_modules.parent.parent
            manager = prefix / "bin/npm"
            result.source, result.prefix, result.manager = "npm", str(prefix), str(manager)
            result.update_supported = manager.is_file() and os.access(manager, os.X_OK)
            result.reason = "" if result.update_supported else "未找到同一 npm 前缀的包管理器"
        else:
            result.source = "local"
            result.reason = "使用该项目或包管理器的更新流程"
        return result

    if "Cellar" in parts or "Caskroom" in parts:
        marker = "Caskroom" if "Caskroom" in parts else "Cellar"
        index = parts.index(marker)
        if len(parts) > index + 1:
            prefix = Path(*parts[:index])
            manager = prefix / "bin/brew"
            result.source, result.prefix = "brew", str(prefix)
            result.package, result.manager = parts[index + 1], str(manager)
            result.cask = marker == "Caskroom"
            result.update_supported = result.package in BREW_PACKAGES.get(role, set()) and manager.is_file() and os.access(manager, os.X_OK)
            result.reason = "" if result.update_supported else "未找到该安装对应的 brew"
            return result

    if role == "claude" and ".local/share/claude/versions/" in target.as_posix():
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "codex" and "/.codex/" in target.as_posix():
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "kimi" and "/.kimi-code/" in target.as_posix():
        result.source, result.update_supported, result.reason = "script", True, ""
    elif role == "hermes":
        # The official update command itself checks supported install types and channels.
        candidates = [target]
        try:
            with target.open("rb") as file:
                lines = file.read(8192).decode("utf-8", "replace").splitlines()
            for line in lines:
                if line.startswith("exec "):
                    words = shlex.split(line)
                    if len(words) > 1 and Path(words[1]).is_absolute():
                        candidates.append(Path(words[1]).resolve())
        except (OSError, ValueError):
            pass
        for candidate in candidates:
            for root in list(candidate.parents)[:8]:
                if (root / ".git").exists() and (root / "hermes_cli").is_dir():
                    result.source, result.root = "source", str(root)
                    result.update_supported, result.reason = True, ""
                    return result
    elif role == "opencode" and "/.opencode/bin/" in target.as_posix():
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "grok" and any("/.grok/bin/" in str(path) or "/.grok/downloads/grok-" in str(path)
                                for path in (entry, target)):
        result.source, result.update_supported, result.reason = "native", True, ""
    return result


def desktop_app(role, home, system_dir=Path("/Applications")):
    """Read a desktop bundle's version; the app updates itself, so detection is read-only."""
    label, bundle = DESKTOP_APPS[role]
    for candidate in (system_dir / f"{bundle}.app", home / f"Applications/{bundle}.app"):
        try:
            with (candidate / "Contents/Info.plist").open("rb") as file:
                info = plistlib.load(file)
            return Installation(role, str(candidate), "desktop",
                                version=str(info.get("CFBundleShortVersionString", "")),
                                reason="由桌面应用自身更新")
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    return Installation(role, reason=f"未找到 {label} 桌面应用")


def discover(search_path=None, home=None):
    home = Path.home() if home is None else Path(home)
    explicit = search_path is not None
    if search_path is None:
        search_path = os.environ.get("PATH", "")
        search_path += os.pathsep + os.pathsep.join(str(home / p) for p in (
            ".local/bin", ".kimi-code/bin", ".opencode/bin", ".grok/bin", ".minimax-code/bin",
            ".bun/bin", ".npm-global/bin", ".local/share/pnpm",
        ))
        for key in ("GROK_BIN_DIR", "MCODE_INSTALL_DIR"):
            if os.environ.get(key):
                extra = Path(os.environ[key]).expanduser()
                search_path += os.pathsep + str(extra / "bin" if key == "MCODE_INSTALL_DIR" else extra)
    found = {}
    for role in TOOLS:
        if role in DESKTOP_APPS:
            found[role] = (Installation(role, reason=f"未找到 {DESKTOP_APPS[role][0]} 桌面应用")
                           if explicit else desktop_app(role, home))
            continue
        path = shutil.which(role, path=search_path)
        found[role] = classify(role, path, home) if path else Installation(role)
    return found

