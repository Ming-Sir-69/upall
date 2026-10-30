#!/usr/bin/env python3
"""Exercise real worker paths with isolated CLI fixtures; never install software."""
import os
import json
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
import time

SCRIPT = Path(__file__).resolve().parents[2] / "tools/upall"
PYTHON = Path(sys.executable)
STUB = r'''
import json, os, sys, time
from pathlib import Path
root = Path(os.environ["UPALL_FIXTURE_ROOT"])
case = os.environ["UPALL_FIXTURE_CASE"]
tool = Path(sys.argv[0]).name
args = sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(tool + " " + " ".join(args) + "\n")
def current(role):
    saved = root / (role + ".version")
    if saved.exists():
        return saved.read_text().strip()
    old = case == "update" or (case == "ineffective" and role == "codex")
    return ("12345678" if old else "abcdefab") if role == "hermes" else ("1.0.0" if old else "1.0.1")
def updated(role):
    (root / (role + ".version")).write_text("abcdefab" if role == "hermes" else "1.0.1")
if tool == "claude" and args == ["--version"]:
    print(current("claude") + " (Claude Code)")
elif tool == "claude" and args == ["update"]:
    updated("claude")
elif tool == "codex" and args == ["--version"]:
    print("codex-cli " + current("codex"))
elif tool == "codex" and args == ["update"]:
    if case != "ineffective":
        updated("codex")
elif tool == "kimi" and args == ["--version"]:
    print(current("kimi"))
elif tool in ("gemini", "grok", "opencode", "openclaw", "pi", "mcode") and args == ["--version"]:
    print(current(tool))
elif tool == "openclaw" and args == ["update", "--dry-run", "--json"]:
    print(json.dumps({"currentVersion":current(tool),"targetVersion":"1.0.1"}))
elif tool == "openclaw" and args == ["update", "--yes"]:
    updated(tool)
elif tool == "npm" and args[0] == "view" and args[-2:] == ["version", "--silent"]:
    if case == "query_failure":
        sys.exit(7)
    if case == "malicious_version":
        print("1.0.1\x1b]52;c;not-a-version\x07")
        sys.exit(0)
    if case == "hang":
        (root / "child.pid").write_text(str(os.getpid()))
        time.sleep(30)
    print("1.0.1")
elif tool == "npm" and args[:3] == ["install", "--global", "--prefix"]:
    assert Path(args[3]).resolve() == (root / "prefix").resolve()
    if case != "ineffective":
        packages={"@openai/codex":"codex", "@google/gemini-cli":"gemini", "@xai-official/grok":"grok",
                  "opencode-ai":"opencode", "@earendil-works/pi-coding-agent":"pi", "@minimax-ai/code":"mcode"}
        updated(next(role for package,role in packages.items() if args[4].startswith(package+"@")))
elif tool == "curl" and args[-1] == "https://code.kimi.com/kimi-code/latest":
    print("1.0.1")
elif tool == "curl" and "https://code.kimi.com/kimi-code/install.sh" in args:
    Path(args[args.index("-o") + 1]).write_text('printf "1.0.1\\n" > "$UPALL_FIXTURE_ROOT/kimi.version"')
elif tool == "git" and args[-3:] == ["rev-parse", "--short=8", "HEAD"]:
    print(current("hermes"))
elif tool == "hermes" and args[:2] == ["--run-module", "hermes_cli.source_check"]:
    assert "--force" in args and "--cache-path" in args
    print(json.dumps({"supported": True, "channel": "stable", "currentSha": current("hermes") * 5,
                      "targetSha": "abcdefab" * 5, "updateAvailable": current("hermes") != "abcdefab"}))
elif tool == "hermes" and args == ["update", "--yes"]:
    updated("hermes")
else:
    sys.exit("unexpected fixture command: " + tool + " " + " ".join(args))
'''


def run_case(case, expected, exit_code, args=(), include_claude=False, include_npm_tools=False):
    with tempfile.TemporaryDirectory(prefix="upall-workers-") as tmp:
        root = Path(tmp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "fixture"
        # macOS exec needs a binary interpreter here, not a second shebang script.
        stub.write_text(f"#!{sys.executable}\n" + STUB)
        stub.chmod(0o755)
        for tool in ("codex", "kimi", "npm", "curl", "git", "hermes"):
            (bin_dir / tool).symlink_to(stub)
        package = root / "prefix/lib/node_modules/@openai/codex"
        package.mkdir(parents=True)
        (package / "package.json").write_text(json.dumps({"name":"@openai/codex"}))
        (package / "codex").write_text(f"#!{sys.executable}\n" + STUB)
        (package / "codex").chmod(0o755)
        (bin_dir / "codex").unlink()
        (bin_dir / "codex").symlink_to(package / "codex")
        (root / "prefix/bin").mkdir()
        (root / "prefix/bin/npm").symlink_to(stub)
        kimi = root / ".kimi-code/bin/kimi"
        kimi.parent.mkdir(parents=True)
        kimi.write_text(f"#!{sys.executable}\n" + STUB)
        kimi.chmod(0o755)
        (bin_dir / "kimi").unlink()
        (bin_dir / "kimi").symlink_to(kimi)
        hermes = root / "hermes-agent/.hermes/bin/hermes"
        hermes.parent.mkdir(parents=True)
        (root / "hermes-agent/.git").mkdir()
        (root / "hermes-agent/hermes_cli").mkdir()
        hermes.write_text(f"#!{sys.executable}\n"+STUB)
        hermes.chmod(0o755)
        (bin_dir / "hermes").unlink()
        (bin_dir / "hermes").write_text(f'#!/bin/sh\nexec "{hermes}" "$@"\n')
        (bin_dir / "hermes").chmod(0o755)
        if include_claude:
            claude = root / ".local/share/claude/versions/1.0.1"
            claude.parent.mkdir(parents=True)
            claude.write_text(f"#!{sys.executable}\n" + STUB)
            claude.chmod(0o755)
            (bin_dir / "claude").symlink_to(claude)
        if include_npm_tools:
            for role,name in {"gemini":"@google/gemini-cli", "grok":"@xai-official/grok", "opencode":"opencode-ai",
                              "openclaw":"openclaw", "pi":"@earendil-works/pi-coding-agent", "mcode":"@minimax-ai/code"}.items():
                package=root/"prefix/lib/node_modules"/name
                package.mkdir(parents=True)
                (package/"package.json").write_text(json.dumps({"name":name}))
                executable=package/"bin"/role
                executable.parent.mkdir()
                executable.write_text(f"#!{sys.executable}\n"+STUB)
                executable.chmod(0o755)
                (bin_dir/role).symlink_to(executable)
        env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", UPALL_TEST_MODE="0", UPALL_SEARCH_PATH=str(bin_dir),
                   UPALL_NO_ALT_SCREEN="1", UPALL_LOG_ROOT=tmp,
                   UPALL_FIXTURE_ROOT=tmp, UPALL_FIXTURE_CASE=case)
        command = [sys.executable, str(SCRIPT), *args]
        if case == "hang":
            process = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            deadline = time.monotonic() + 4
            while not (root / "child.pid").exists() and time.monotonic() < deadline:
                time.sleep(.02)
            assert (root / "child.pid").exists()
            child_pid = int((root / "child.pid").read_text())
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=4)
            result = subprocess.CompletedProcess(command, process.returncode, stdout, stderr)
            try:
                os.kill(child_pid, 0)
            except ProcessLookupError:
                pass
            else:
                raise AssertionError("cancelled updater child still exists")
        else:
            result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL,
                                    capture_output=True, text=True, timeout=10)
        states = {role: (root / "latest/state" / f"{role}.status").read_text().strip()
                  for role in expected}
        logs = "\n".join(p.read_text() for p in (root / "latest").glob("*.log"))
        assert result.returncode == exit_code, (case, result.stderr, logs)
        assert states == expected, (case, states, logs)
        assert not result.stderr, (case, result.stderr)
        assert (root / "calls").exists(), (result.stdout, logs)
        calls = (root / "calls").read_text()
        if "hermes" in expected:
            assert "hermes --run-module hermes_cli.source_check" in calls
        if case != "update" or "--update" not in args:
            assert "hermes update --yes" not in calls
        if "--update" not in args:
            assert "npm install" not in calls and "codex update" not in calls and "install.sh" not in calls
        if "--json" in args:
            report = json.loads(result.stdout)
            assert len(report["jobs"]) == len(expected)
            assert report["mode"] == ("update" if "--update" in args else "check")
        if case == "ineffective":
            assert "expected=1.0.1" in (root / "latest/codex.log").read_text()
        if case == "query_failure":
            untouched = (root / "latest/hermes.log").read_text()
            retry = subprocess.run([*command, "--retry", "--json"], env=dict(env, UPALL_FIXTURE_CASE="current"),
                                   stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=5)
            assert retry.returncode == 0, retry.stderr
            assert [(j["role"],j["status"]) for j in json.loads(retry.stdout)["jobs"]] == [("codex","CURRENT")]
            assert (root / "latest/hermes.log").read_text() == untouched
        print(f"PASS: {case} {' '.join(args)}")


current = dict.fromkeys(("codex", "kimi", "hermes"), "CURRENT")
run_case("current", current, 0)
run_case("update", dict.fromkeys(current, "AVAILABLE"), 0)
run_case("update", dict.fromkeys(current, "UPDATED"), 0, ("--update",))
run_case("ineffective", {**current, "codex": "UPDATE-FAILED"}, 1, ("--update",))
run_case("query_failure", {**current, "codex": "CONNECTION-FAILED"}, 1)
run_case("malicious_version", {**current, "codex": "CONNECTION-FAILED"}, 1)
run_case("update", dict.fromkeys(current, "AVAILABLE"), 0, ("--check",))
run_case("update", {"codex": "AVAILABLE"}, 0, ("codex", "--json"))
run_case("update", {"codex": "UPDATED"}, 0, ("codex", "--json", "--update"))
run_case("hang", {"codex": "CANCELLED"}, 130, ("codex",))
run_case("current", {"claude":"CURRENT", **current}, 0, include_claude=True)
run_case("update", {"claude":"UPDATED", **dict.fromkeys(current,"UPDATED")}, 0, ("--update",), include_claude=True)
run_case("update", {"claude":"UPDATED", **dict.fromkeys(current,"UPDATED"),
         **dict.fromkeys(("gemini","grok","opencode","openclaw","pi","mcode"),"UPDATED")}, 0, ("--update",),
         include_claude=True, include_npm_tools=True)

# Desktop applications check their own update feeds but are never auto-installed.
from types import SimpleNamespace
from upall.discovery import Installation
from upall.engine import Engine


def desktop_engine(tmp, version="26.1", inventory=False):
    installations = {"chatgpt": Installation("chatgpt", "/Applications/ChatGPT.app", "desktop",
                                             version=version, reason="由桌面应用自身更新")}
    args = SimpleNamespace(check=True, demo=False, inventory=inventory)
    return Engine(args, ["chatgpt"], Path(tmp), installations)


with tempfile.TemporaryDirectory(prefix="upall-desktop-") as tmp:
    engine = desktop_engine(tmp)
    try:
        engine.desktop_latest = lambda role, found: found.version
        engine.start()
        while not engine.done():
            time.sleep(0.02)
        job = engine.snapshot()[0]
        assert job.status == "CURRENT" and job.current == "26.1" and job.latest == "26.1"
        assert job.detail == "由桌面应用自身更新"
    finally:
        engine.pool.shutdown()
print("PASS: desktop application up to date shows CURRENT with the feed version")

with tempfile.TemporaryDirectory(prefix="upall-desktop-newer-") as tmp:
    engine = desktop_engine(tmp)
    try:
        engine.desktop_latest = lambda role, found: "26.2"
        engine.start()
        while not engine.done():
            time.sleep(0.02)
        job = engine.snapshot()[0]
        assert job.status == "MANUAL" and job.latest == "26.2" and job.detail == "请在应用内更新"
    finally:
        engine.pool.shutdown()
print("PASS: a newer desktop release needs manual in-app updating, never an upall install")

with tempfile.TemporaryDirectory(prefix="upall-desktop-inventory-") as tmp:
    engine = desktop_engine(tmp, inventory=True)
    try:
        def no_feed(role, found):
            raise AssertionError("inventory must not contact update feeds")
        engine.desktop_latest = no_feed
        engine.start()
        while not engine.done():
            time.sleep(0.02)
        job = engine.snapshot()[0]
        assert job.status == "INSTALLED" and job.current == "26.1" and job.latest == "-"
    finally:
        engine.pool.shutdown()
print("PASS: inventory mode lists desktop applications without update checks")

with tempfile.TemporaryDirectory(prefix="upall-desktop-feed-") as tmp:
    engine = desktop_engine(tmp)
    try:
        appcast = ('<rss xmlns:sparkle="http://www.andymatuschak.org/xml-namespaces/sparkle">'
                   "<channel><item><sparkle:shortVersionString>26.1027.30824"
                   "</sparkle:shortVersionString></item></channel></rss>")
        engine.command = lambda role, command, **kwargs: appcast
        assert engine.desktop_latest("chatgpt", engine.installations["chatgpt"]) == "26.1027.30824"
        engine.command = lambda role, command, **kwargs: "<rss/>"
        try:
            engine.desktop_latest("chatgpt", engine.installations["chatgpt"])
        except Exception as error:
            assert "未读到有效的最新版本" in str(error)
        else:
            raise AssertionError("malformed appcast must fail the check")
    finally:
        engine.pool.shutdown()
print("PASS: Sparkle appcast parsing and rejection of malformed feed metadata")

import io
import plistlib
import zipfile


def fake_desktop(root, version="26.1"):
    bundle = root / "ChatGPT.app"
    (bundle / "Contents").mkdir(parents=True)
    (bundle / "Contents/Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": version}))
    installations = {"chatgpt": Installation("chatgpt", str(bundle), "desktop",
                                             version=version, reason="由桌面应用自身更新")}
    engine = Engine(SimpleNamespace(check=True, demo=False, inventory=False), ["chatgpt"], root / "logs", installations)
    engine.trash_dir = root / "Trash"
    engine.trash_dir.mkdir()
    engine.desktop_running = lambda name: False
    feed = {"version": "26.2", "url": "https://persistent.oaistatic.com/codex-app-prod/fake.zip",
            "sha256": "", "size": 0}
    def latest(role, found):
        engine.desktop_feeds[role] = feed
        return feed["version"]
    engine.desktop_latest = latest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("ChatGPT.app/Contents/Info.plist", plistlib.dumps({"CFBundleShortVersionString": "26.2"}))
    feed["size"] = len(buffer.getvalue())
    return engine, bundle, feed, buffer.getvalue()


def finish(engine, install=False):
    engine.start(install=install)
    while not engine.done():
        time.sleep(0.02)
    return engine.snapshot()[0]


with tempfile.TemporaryDirectory(prefix="upall-desktop-available-") as tmp:
    engine, _, _, _ = fake_desktop(Path(tmp))
    try:
        job = finish(engine)
        assert job.status == "AVAILABLE" and job.latest == "26.2", (job.status, job.detail)
    finally:
        engine.pool.shutdown()
print("PASS: a desktop release with a trustworthy package URL becomes AVAILABLE")

with tempfile.TemporaryDirectory(prefix="upall-desktop-install-") as tmp:
    engine, bundle, feed, payload = fake_desktop(Path(tmp))
    try:
        real_command = engine.command
        def fake_command(role, command, **kwargs):
            if command[0] == "curl":
                Path(command[-1]).write_bytes(payload)
                return ""
            return real_command(role, command, **kwargs)
        engine.command = fake_command
        job = finish(engine, install=True)
        assert job.status == "UPDATED" and job.current == "26.2", (job.status, job.detail)
        assert plistlib.loads((bundle / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"] == "26.2"
        assert list(engine.trash_dir.glob("ChatGPT.app.upall-*")), "old bundle must be kept in the Trash"
    finally:
        engine.pool.shutdown()
print("PASS: desktop update swaps the bundle from the official zip and keeps the old one in the Trash")

with tempfile.TemporaryDirectory(prefix="upall-desktop-hash-") as tmp:
    import hashlib
    engine, bundle, feed, payload = fake_desktop(Path(tmp))
    try:
        feed["sha256"] = hashlib.sha256(b"different").hexdigest()
        engine.command = lambda role, command, **kwargs: (Path(command[-1]).write_bytes(payload) or "")
        job = finish(engine, install=True)
        assert job.status == "UPDATE-FAILED" and "sha256" in job.detail, (job.status, job.detail)
        assert plistlib.loads((bundle / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"] == "26.1"
        assert not list(engine.trash_dir.glob("ChatGPT.app.upall-*")), "failed verification must not touch the app"
    finally:
        engine.pool.shutdown()
print("PASS: a sha256 mismatch aborts the desktop update without touching the installed app")
