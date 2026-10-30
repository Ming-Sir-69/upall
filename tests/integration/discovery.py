#!/usr/bin/env python3
"""Discovery is bounded, identifies provenance and never installs missing tools."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUNTIME = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RUNTIME))
from upall.discovery import TOOLS, classify, desktop_app, discover

def executable(path, text="#!/bin/sh\nexit 0\n"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)
    return path

def npm_install(prefix, role, package):
    root = prefix / "lib/node_modules" / package
    root.mkdir(parents=True)
    (root / "package.json").write_text(json.dumps({"name": package}))
    target = executable(root / "bin" / role)
    entry = prefix / "bin" / role
    entry.parent.mkdir(exist_ok=True)
    entry.symlink_to(target)
    executable(prefix / "bin/npm")
    return entry

with tempfile.TemporaryDirectory(prefix="upall-discovery-") as tmp:
    root = Path(tmp)
    home = root / "home"
    # /opt/homebrew/bin does not itself prove Homebrew ownership.
    prefix = root / "homebrew"
    codex = npm_install(prefix, "codex", "@openai/codex")
    found = classify("codex", codex, home)
    assert (found.source, found.package, found.prefix) == ("npm", "@openai/codex", str(prefix.resolve())), found.public()
    assert found.update_supported
    # Even an npm prefix living below a Homebrew Node Cellar belongs to npm.
    nested = root / "Cellar/node/24"
    nested_codex = npm_install(nested, "codex", "@openai/codex")
    assert classify("codex", nested_codex, home).source == "npm"

    native = executable(home / ".local/share/claude/versions/2.1.301")
    launcher = home / ".local/bin/claude"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(native)
    settings = home / ".claude/settings.json"
    settings.parent.mkdir()
    settings.write_text('{"autoUpdatesChannel":"stable"}')
    claude = classify("claude", launcher, home)
    assert (claude.source, claude.channel, claude.update_supported) == ("native", "stable", True)

    brew = root / "brew"
    executable(brew / "bin/brew")
    gemini = executable(brew / "Cellar/gemini-cli/1.2.3/bin/gemini")
    found = classify("gemini", gemini, home)
    assert (found.source, found.package, found.update_supported) == ("brew", "gemini-cli", True)

    project = root / "project/node_modules/@earendil-works/pi-coding-agent"
    project.mkdir(parents=True)
    (project / "package.json").write_text('{"name":"@earendil-works/pi-coding-agent"}')
    pi = executable(project / "bin/pi")
    found = classify("pi", pi, home)
    assert found.source == "local" and not found.update_supported
    old_pi = npm_install(root / "legacy", "pi", "@mariozechner/pi-coding-agent")
    assert classify("pi", old_pi, home).package == "@mariozechner/pi-coding-agent"
    unknown = executable(root / "unrelated/pi")
    assert not classify("pi", unknown, home).update_supported
    grok = executable(home / ".grok/downloads/grok-darwin-arm64")
    launcher = home / ".grok/bin/grok"
    launcher.parent.mkdir(parents=True)
    launcher.symlink_to(grok)
    assert classify("grok", launcher, home).source == "native"
    hermes = executable(root / "custom-hermes/.hermes/bin/hermes")
    (root / "custom-hermes/hermes_cli").mkdir()
    (root / "custom-hermes/.git").mkdir()
    wrapper = executable(root / "custom-bin/hermes", f'#!/bin/sh\nexec "{hermes}" "$@"\n')
    assert classify("hermes", wrapper, home).root == str((root / "custom-hermes").resolve())

    inventory = discover(search_path=str(prefix / "bin"), home=home)
    assert inventory["codex"].installed
    assert not inventory["claude"].installed  # Explicit search path does not fall through to another install.
    assert not inventory["claude-desktop"].installed
    assert set(inventory) == set(TOOLS) and len(inventory) == 12
    empty = discover(search_path=str(root / "empty"), home=home)
    assert all(not item.installed for item in empty.values())
    bundle = home / "Applications/ChatGPT.app/Contents"
    bundle.mkdir(parents=True)
    import plistlib
    (bundle / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "1.2026.1"}))
    app = desktop_app("chatgpt", home, system_dir=root / "no-apps")
    assert app.installed and app.version == "1.2026.1" and app.source == "desktop"
    missing = desktop_app("chatgpt", root / "nowhere", system_dir=root / "no-apps")
    assert not missing.installed and missing.reason == "未找到 ChatGPT 桌面应用"
print("PASS: npm/native/brew/local/unknown identities, stable channel, legacy namespace, bounded detection")

with tempfile.TemporaryDirectory(prefix="upall-empty-") as tmp:
    env = dict(os.environ, UPALL_SEARCH_PATH=tmp, UPALL_LOG_ROOT=tmp, UPALL_TEST_MODE="0")
    script = RUNTIME / "tools/upall"
    result = subprocess.run([sys.executable, str(script), "--list", "--json"], env=env,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert len(report["jobs"]) == 12
    assert all(job["status"] == "SKIPPED" for job in report["jobs"])
    assert not (Path(tmp) / "latest/report.json").exists(), "inventory replaced the last update report"
    result = subprocess.run([sys.executable, str(script), "--json"], env=env,
                            stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
    assert result.returncode == 0 and json.loads(result.stdout)["jobs"] == []
print("PASS: all missing tools stay missing; list/empty discovery never launches an installer")

