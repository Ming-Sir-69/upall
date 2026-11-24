"""Known tools and bounded installation discovery; never install during detection."""
from dataclasses import dataclass, asdict, field
import json
import os
from pathlib import Path
import plistlib
import shlex
import shutil
import subprocess
import sys

TOOLS = {
    "claude": "Claude Code", "codex": "Codex", "kimi": "Kimi Code", "hermes": "Hermes",
    "gemini": "Gemini CLI", "grok": "Grok Build", "opencode": "OpenCode",
    "openclaw": "OpenClaw", "pi": "Pi", "mcode": "MiniMax Code", "cursor-agent": "Cursor Agent",
    "antigravity-cli": "Antigravity CLI", "dsh": "DeepSeek Harness",
    "omp": "Oh My Pi", "copilot": "GitHub Copilot CLI",
    "claude-desktop": "Claude Desktop", "workbuddy": "WorkBuddy",
    "kimi-cu": "KimiCU", "kimi-webbridge": "Kimi WebBridge", "iphone-use": "iPhone Use",
    "agent-desktop": "Agent Desktop", "mole": "Mole", "cc-switch": "CC Switch",
}
# Display groups, in screen order. Host-defined tools pick one of these keys.
GROUPS = {"cli": "AI 编程工具", "agent": "Agent 插件与技能", "app": "效率与维护", "host": "本机项目"}
ROLE_GROUPS = {"claude-desktop": "app", "workbuddy": "app", "kimi-cu": "agent", "kimi-webbridge": "agent", "iphone-use": "agent",
               "agent-desktop": "agent", "mole": "app", "cc-switch": "app"}
# Monitor kinds are orthogonal to GROUPS: filter what to check, not how it is listed.
# Defaults keep today's CLI/agent/app checks (runtime) plus future skill/mcp; plugin stays off.
MONITORS = {"runtime": "编程工具本体", "plugin": "宿主插件", "skill": "Skill", "mcp": "MCP"}
DEFAULT_MONITORS = frozenset({"runtime", "skill", "mcp"})
# Built-ins default to runtime; layer roles (skill/mcp) and host tools set monitor explicitly.
ROLE_MONITORS = {}
# macOS app bundles that UPALL replaces from the vendor's own package after
# signature checks: (bundle name, bundle id, launchd service to restart).
APP_BUNDLES = {"kimi-cu": ("KimiCU", "ai.kimi.cu", "ai.kimi.cu.service"),
               "cc-switch": ("CC Switch", "com.ccswitch.desktop", "")}
DESKTOP_APPS = {"claude-desktop": ("Claude", "com.anthropic.claudefordesktop"),
                "workbuddy": ("WorkBuddy", "com.tencent.workbuddy.mac")}
DEMO_ROLES = ("claude", "codex", "kimi", "hermes")
PACKAGES = {
    "dsh": ("@deepseek-ai/dsh",), "omp": ("@oh-my-pi/pi-coding-agent",),
    "copilot": ("@github/copilot",),
    "claude": ("@anthropic-ai/claude-code",), "codex": ("@openai/codex",),
    "gemini": ("@google/gemini-cli",), "grok": ("@xai-official/grok",),
    "opencode": ("opencode-ai", "@opencode/cli"), "openclaw": ("openclaw",),
    "pi": ("@earendil-works/pi-coding-agent", "@mariozechner/pi-coding-agent"),
    "mcode": ("@minimax-ai/code",), "agent-desktop": ("agent-desktop",),
}
SOURCE_LABELS = {
    "npm": "npm", "brew": "Homebrew", "native": "官方原生", "script": "官方脚本",
    "bun": "Bun", "source": "源码安装", "local": "项目依赖",
    "app": "官方应用包", "host": "本机配置", "git": "Git 检出",
    "unknown": "来源待确认", "missing": "未安装", "demo": "演示",
}
BREW_PACKAGES = {
    "copilot": {"copilot-cli"}, "omp": {"oh-my-pi"},
    "antigravity-cli": {"antigravity-cli"},
    "claude": {"claude-code", "claude-code@latest"}, "codex": {"codex"},
    "gemini": {"gemini-cli"}, "grok": {"grok"}, "opencode": {"opencode"},
    "openclaw": {"openclaw"}, "pi": {"pi", "pi-coding-agent"}, "mcode": {"minimax-code"}, "mole": {"mole"},
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
    label: str = ""
    group: str = "cli"
    monitor: str = "runtime"
    spec: dict = field(default_factory=dict)
    preserve: list = field(default_factory=list)

    def __post_init__(self):
        self.label = self.label or TOOLS.get(self.role, self.role)
        if not self.spec:
            self.group = ROLE_GROUPS.get(self.role, self.group)
            self.monitor = ROLE_MONITORS.get(self.role, self.monitor)
        if self.monitor not in MONITORS:
            self.monitor = "runtime"

    @property
    def installed(self):
        return bool(self.path)

    def public(self):
        data = dict(asdict(self), installed=self.installed, source_label=SOURCE_LABELS[self.source])
        data.pop("spec")
        return data


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
        if role == "omp" and node_modules == (home / ".bun/install/global/node_modules").resolve():
            result.source, result.update_supported, result.reason = "bun", True, ""
        elif node_modules and node_modules.parent.name == "lib":
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

    if role == "antigravity-cli" and sys.platform == "darwin":
        # A custom install directory is valid. Check the signed executable,
        # not the location or a version string printed by an unknown wrapper.
        requirement = 'identifier "cli" and anchor apple generic and certificate leaf[subject.OU] = "EQHXZ8M8AV"'
        try:
            verified = subprocess.run(
                ["/usr/bin/codesign", "--verify", "--strict", "-R=" + requirement, str(target)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            ).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            verified = False
        if verified:
            result.path = str(target)
            result.source, result.update_supported, result.reason = "native", True, ""
        return result

    if role == "claude" and ".local/share/claude/versions/" in target.as_posix():
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "codex" and "/.codex/" in target.as_posix():
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "cursor-agent" and ".local/share/cursor-agent/versions/" in target.as_posix():
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
    elif role in ("kimi-webbridge", "iphone-use") and (
            "/.kimi-webbridge/bin/" in target.as_posix() or ".app/Contents/MacOS/" in target.as_posix()):
        # Both ship their own verified upgrade command.
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "mole" and ((target.parent / "lib/core/common.sh").exists() or "SCRIPT_DIR=" in _head(target)):
        result.source, result.update_supported, result.reason = "script", True, ""
    elif role == "opencode" and "/.opencode/bin/" in target.as_posix():
        result.source, result.update_supported, result.reason = "native", True, ""
    elif role == "grok" and any("/.grok/bin/" in str(path) or "/.grok/downloads/grok-" in str(path)
                                for path in (entry, target)):
        result.source, result.update_supported, result.reason = "native", True, ""
    return result


def _head(path):
    try:
        with open(path, "rb") as file:
            return file.read(16384).decode("utf-8", "replace")
    except OSError:
        return ""


def app_info(bundle):
    try:
        with (Path(bundle) / "Contents/Info.plist").open("rb") as file:
            info = plistlib.load(file)
        return {"id": str(info.get("CFBundleIdentifier", "")),
                "executable": str(info.get("CFBundleExecutable", "")),
                "version": str(info.get("CFBundleShortVersionString", ""))}
    except (OSError, ValueError, plistlib.InvalidFileException):
        return {}


def registered_desktop_paths():
    """Ask Launch Services about moved or renamed apps without launching them."""
    ids = [identifier for _, identifier in DESKTOP_APPS.values()]
    script = ('ObjC.import("AppKit"); JSON.stringify(' + json.dumps(ids) +
              '.map(id => ObjC.unwrap($.NSWorkspace.sharedWorkspace.'
              'URLForApplicationWithBundleIdentifier(id).path) || ""))')
    try:
        result = subprocess.run(["/usr/bin/osascript", "-l", "JavaScript", "-e", script],
                                capture_output=True, check=True, text=True, timeout=4)
        paths = json.loads(result.stdout)
        return {role: Path(path) for role, path in zip(DESKTOP_APPS, paths)
                if isinstance(path, str) and Path(path).is_absolute()}
    except (OSError, subprocess.SubprocessError, ValueError, TypeError):
        return {}


def find_app(role, directories, registered=None):
    desktop = role in DESKTOP_APPS
    name, bundle_id = DESKTOP_APPS[role] if desktop else APP_BUNDLES[role][:2]
    candidates = [Path(directory) / f"{name}.app" for directory in directories]
    if registered:
        candidates.append(registered)
    for candidate in candidates:
        info = app_info(candidate)
        if info.get("id") == bundle_id:
            if desktop:
                executable = info.get("executable", "")
                if not executable or Path(executable).name != executable:
                    continue
                binary = candidate / "Contents/MacOS" / executable
                if not binary.is_file() or not os.access(binary, os.X_OK):
                    continue
                return Installation(role, str(candidate), "app", version=info["version"],
                                    reason="由应用内更新器管理")
            return Installation(role, str(candidate), "app", update_supported=True)
    return Installation(role)


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
    if not explicit:
        search_path += os.pathsep + os.pathsep.join(str(p) for p in (
            home / ".kimi-webbridge/bin", home / "Applications/iPhoneUse.app/Contents/MacOS",
            Path("/Applications/iPhoneUse.app/Contents/MacOS")))
    app_dirs = os.environ.get("UPALL_APP_DIRS")
    registered = registered_desktop_paths() if sys.platform == "darwin" and not explicit and app_dirs is None else {}
    app_dirs = ([p for p in app_dirs.split(os.pathsep) if p] if app_dirs is not None else
                [] if explicit else ["/Applications", str(home / "Applications")])
    found = {}
    for role in TOOLS:
        if role in APP_BUNDLES or role in DESKTOP_APPS:
            found[role] = find_app(role, app_dirs, registered.get(role))
            continue
        path = shutil.which("agy" if role == "antigravity-cli" else role, path=search_path)
        if not path and role == "mole":
            path = shutil.which("mo", path=search_path)
        if not path and role == "cursor-agent":
            # Official installers also expose a short `agent` name; only accept it
            # when it resolves into the Cursor Agent versions tree.
            alt = shutil.which("agent", path=search_path)
            if alt and ".local/share/cursor-agent/versions/" in Path(alt).resolve().as_posix():
                path = alt
        found[role] = classify(role, path, home) if path else Installation(role)
    return found

