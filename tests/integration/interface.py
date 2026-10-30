#!/usr/bin/env python3
"""End-to-end PTY checks for keyboard actions, resize, locking and terminal recovery."""
import fcntl
from concurrent.futures import Future
import importlib.util
import json
import os
from pathlib import Path
import pty
import select
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
from types import SimpleNamespace

SCRIPT = Path(__file__).resolve().parents[2] / "tools/upall"
from upall import terminal as upall
from upall.engine import Engine
from upall.discovery import TOOLS
from upall.util import clean, width, fit
upall.Engine, upall.TOOLS = Engine, TOOLS
upall.clean, upall.width, upall.fit = clean, width, fit


decoder = upall.KeyDecoder()
assert decoder.feed(b"\x1b", now=0) == []
assert decoder.feed(now=.11) == ["\x1b"]
decoder = upall.KeyDecoder()
assert decoder.feed(b"\x1b", now=0) == []
assert decoder.feed(b"[", now=.04) == []
assert decoder.feed(b"B", now=.08) == ["\x1b[B"]
assert decoder.feed(now=.3) == []
assert decoder.feed(b"\x1b[11~\x1bOQ\x1bq") == ["\x1b[11~", "\x1bOQ", "\x1bq"]
for byte in "０１２３".encode():
    keys = decoder.feed(bytes([byte]))
    if keys:
        assert keys[0] in "０１２３"
print("PASS: lone Escape, fragmented arrows, function/Alt keys, split UTF-8 decoding")


class Session:
    def __init__(self, root, args=(), **extra):
        self.root = Path(root)
        self.master, self.slave = pty.openpty()
        self.original = termios.tcgetattr(self.slave)
        self.resize(100, 28)
        self.env = dict(os.environ, UPALL_LOG_ROOT=root, UPALL_TEST_MODE="1",
                        TERM="xterm-256color", **extra)
        self.process = subprocess.Popen([sys.executable, str(SCRIPT), *args],
            env=self.env, stdin=self.slave, stdout=self.slave, stderr=self.slave)
        self.output = b""

    def resize(self, cols, rows):
        fcntl.ioctl(self.master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

    def read(self):
        ready, _, _ = select.select([self.master], [], [], 0.03)
        if ready:
            self.output += os.read(self.master, 65536)

    def report(self):
        try:
            return json.loads((self.root / "latest/report.json").read_text())
        except (OSError, ValueError):
            return {}

    def until(self, predicate, timeout=6):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.read()
            if predicate():
                return
            assert self.process.poll() is None, self.output.decode("utf-8", "replace")[-2000:]
        raise AssertionError("PTY condition timed out: " + self.output.decode("utf-8", "replace")[-2000:])

    def send(self, key):
        os.write(self.master, key.encode())

    def close(self, code=0):
        try:
            deadline = time.monotonic() + 5
            while self.process.poll() is None and time.monotonic() < deadline:
                self.read()
            assert self.process.poll() is not None, self.output.decode("utf-8", "replace")[-3000:]
            assert self.process.returncode == code, self.output.decode("utf-8", "replace")[-2000:]
            after = termios.tcgetattr(self.slave)
            # macOS may set PENDIN when canonical input resumes; it is transient kernel state.
            after[3] &= ~getattr(termios, "PENDIN", 0)
            self.original[3] &= ~getattr(termios, "PENDIN", 0)
            assert after == self.original, ("terminal attributes were not restored", self.original, after)
        finally:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            os.close(self.master)
            os.close(self.slave)


with tempfile.TemporaryDirectory(prefix="upall-interface-") as tmp:
    engine = upall.Engine(SimpleNamespace(check=False, demo=True), list(upall.TOOLS), Path(tmp))
    try:
        for role in upall.TOOLS:
            engine.update(role, status="CURRENT", current="1.2.3", latest="1.2.3")
        view = upall.Terminal(engine)
        view.color = False
        for cols, rows in ((120, 40), (80, 24), (54, 24), (40, 16), (20, 8)):
            frame = view.frame(cols, rows)
            assert max(map(upall.width, frame)) < cols
            assert len(frame) < rows
            assert "退出" in "\n".join(frame)
        frame = "\n".join(view.frame(120, 40))
        assert "空格/1 更新" in frame and "2 重试" in frame and "3 日志" in frame
        view.key("3")
        view.selected = len(engine.jobs) - 1
        frame = "\n".join(view.frame(80, 24))
        assert "显示" in frame
        assert upall.fit("ChatGPT", 11).strip() in frame and "›" in frame
        view.selected = 0
        assert upall.clean("\x1b[31merror\x1b[0m\x1b]52;c;payload\x07\r") == "error"
        for key in ("\r", "\n", "0", "０", "\x1b", "q", "Q", "x", "X"):
            assert view.key(key) is False
        engine.futures = [Future()]
        for key in ("\r", "\n", "0", "０", "\x1b", "q", " ", "　", "1", "2", "１", "２"):
            assert view.key(key) is True
            assert not engine.stop.is_set()
        assert all(job.attempt == 0 for job in engine.snapshot())
    finally:
        engine.pool.shutdown()
print("PASS: wide/narrow/short layouts, Chinese widths, control-sequence filtering")

with tempfile.TemporaryDirectory(prefix="upall-interface-polish-") as tmp:
    engine = upall.Engine(SimpleNamespace(check=False, demo=True), list(upall.TOOLS), Path(tmp))
    try:
        for role in upall.TOOLS:
            engine.update(role, status="CURRENT", current="1.2.3", latest="1.2.3")
        view = upall.Terminal(engine)
        view.color = True
        view.truecolor = True
        from upall.icons import BRAND
        assert set(BRAND) == set(upall.TOOLS)
        frame = "\n".join(view.frame(120, 40))
        assert "✳" in frame and "\033[38;2;217;119;87m" in frame
        assert "\033[92m━" in "\n".join(view.frame(120, 40))
        engine.update("claude", status="UPDATE-FAILED", detail="命令退出码 1")
        assert "\033[91m━" in "\n".join(view.frame(120, 40))
        (Path(tmp) / "claude.log").write_text("$ cmd\npartial output line\n")
        assert "partial output line" in "\n".join(view.frame(120, 40))
        view.offset = 3
        assert "已暂停跟随" in "\n".join(view.frame(120, 40))
        view.selected, view.offset = 1, 5
        view.focus_failed()
        assert view.selected == 0 and view.offset == 0
        engine.update("claude", status="CURRENT", detail="")
        engine.update("codex", status="UPDATE-FAILED")
        view.selected = 0
        view.focus_failed()
        assert view.selected == list(upall.TOOLS).index("codex")
        folded = upall.Terminal(engine)
        assert not folded.show_logs
        folded.frame(120, 40)
        assert folded.show_logs
        folded.key("3")
        folded.frame(120, 40)
        assert not folded.show_logs
        os.environ["UPALL_ASCII"] = "1"
        try:
            plain = "\n".join(upall.Terminal(engine).frame(80, 24))
            assert "╭" not in plain and "─" not in plain and "+" in plain and "✳" not in plain
        finally:
            del os.environ["UPALL_ASCII"]
        view.selected = list(upall.TOOLS).index("claude-desktop")
        view.show_logs, view.logs_touched = True, True
        art = view.frame(140, 40)
        assert any("▀" in line or "▄" in line for line in art)
        assert max(map(upall.width, art)) <= 140
        import contextlib
        import io
        from upall import cli as upall_cli
        engine.finished = engine.started + 7
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            upall_cli.summary(engine, Path(tmp))
        text = output.getvalue()
        assert "结果摘要" in text and "总耗时 7s" in text
        assert "× ❯ Codex" in text and "✓ ✳ Claude Code" in text
        assert text.index("Codex") < text.index("Claude Code")
        engine.update("codex", status="CURRENT", detail="")
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            upall_cli.summary(engine, Path(tmp))
        text = output.getvalue()
        assert "结果摘要" not in text and "完成 12 项 · 失败 0 项" in text and "总耗时 7s" in text
    finally:
        engine.pool.shutdown()
print("PASS: bar state colors, inline log tail, follow hint, failure focus, ASCII fallback, static summary")

with tempfile.TemporaryDirectory(prefix="upall-pty-retry-") as tmp:
    session = Session(tmp, UPALL_TEST_FAILURE="codex")
    session.until(lambda: sum(j["status"] == "AVAILABLE" for j in session.report().get("jobs", [])) == 3)
    assert session.report()["mode"] == "check"
    session.send(" ")
    session.until(lambda: any(j["status"] == "UPDATE-FAILED" for j in session.report().get("jobs", [])))
    other = subprocess.run([sys.executable, str(SCRIPT), "--plain"], env=session.env, capture_output=True, timeout=5)
    assert other.returncode == 2 and "已有 upall" in other.stderr.decode()
    session.resize(52, 22)
    session.send("\x1b[B")
    session.until(lambda: "日志 · Codex".encode() in session.output)
    session.send("３3２")
    session.until(lambda: any(j["role"] == "codex" and j["attempt"] == 3 and j["status"] == "UPDATED"
                             for j in session.report().get("jobs", [])))
    report = session.report()
    assert {j["role"]: j["attempt"] for j in report["jobs"]} == {"claude": 2, "codex": 3, "kimi": 1, "hermes": 2}
    session.send("0")
    session.close()
    assert "完成 4 项 · 失败 0 项".encode() in session.output
print("PASS: default check, Space update, 2/２ failed-only retry, 3/３ logs, resize, lock, 0 exit, collapsed summary on success")

for update_key in ("1", "１", "　"):
    with tempfile.TemporaryDirectory(prefix="upall-pty-check-") as tmp:
        session = Session(tmp)
        session.until(lambda: sum(j["status"] == "AVAILABLE" for j in session.report().get("jobs", [])) == 3)
        report = session.report()
        assert report["mode"] == "check" and all(j["attempt"] == 1 for j in report["jobs"])
        session.send(update_key)
        session.until(lambda: sum(j["status"] == "UPDATED" for j in session.report().get("jobs", [])) == 3)
        report = session.report()
        assert report["mode"] == "update"
        assert {j["role"]:j["attempt"] for j in report["jobs"]} == {"claude":2,"codex":2,"kimi":1,"hermes":2}
        for byte in "０".encode():
            os.write(session.master, bytes([byte]))
            time.sleep(.03)
        session.close()
print("PASS: 1/１/full-width Space update available tools only; split full-width ０ exits")

for key in ("\r", "\n", "\x1b"):
    with tempfile.TemporaryDirectory(prefix="upall-pty-exit-") as tmp:
        session = Session(tmp, ("codex",))
        session.until(lambda: bool(session.report().get("jobs")))
        assert session.report()["mode"] == "check"
        assert session.report()["jobs"][0]["status"] == "AVAILABLE"
        session.send(key)
        session.close()
print("PASS: Return, line-feed Enter and standalone Escape exit normally")

with tempfile.TemporaryDirectory(prefix="upall-pty-running-") as tmp:
    session = Session(tmp)
    session.until(lambda: "UPALL".encode() in session.output)
    session.send(" 0\r\x1b")
    session.until(lambda: "任务运行中".encode() in session.output)
    assert session.process.poll() is None
    session.until(lambda: len(session.report().get("jobs", [])) == 4)
    assert all(j["status"] in ("CURRENT", "AVAILABLE") and j["attempt"] == 1 for j in session.report()["jobs"])
    session.send("\x1b")
    session.read()
    session.send("[")
    session.read()
    session.send("B")
    session.send("3")
    session.until(lambda: "日志 · Codex".encode() in session.output)
    assert session.process.poll() is None
    session.send("0")
    session.close()
print("PASS: exit keys leave running updates intact; fragmented arrow does not quit")

with tempfile.TemporaryDirectory(prefix="upall-pty-stop-") as tmp:
    session = Session(tmp)
    session.until(lambda: "UPALL".encode() in session.output)
    session.process.send_signal(signal.SIGINT)
    session.close(130)
    assert any(j["status"] == "CANCELLED" for j in session.report()["jobs"])
print("PASS: Ctrl-C stops workers and restores cursor/terminal settings")

