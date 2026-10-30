"""Concurrent version checks and explicit update execution."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
import os
from pathlib import Path
import re
import shlex
import signal
import subprocess
import tempfile
import threading
import time
from .discovery import TOOLS, PACKAGES, Installation, discover
from .models import Job
from .status import LABELS
from .util import atomic, clean, private_directory


class CommandError(Exception):
    pass


class Engine:
    def __init__(self, args, roles, log_dir, installations=None):
        self.args, self.log_dir = args, log_dir
        self.mode = "inventory" if getattr(args, "inventory", False) else "check" if args.check else "update"
        self.state_dir = log_dir / "state"
        private_directory(self.state_dir)
        self.hermes_root = Path.home() / ".hermes/hermes-agent"
        self.installations = installations or (dict.fromkeys(roles) if args.demo else discover(os.environ.get("UPALL_SEARCH_PATH")))
        self.jobs = {}
        for role in roles:
            found = Installation(role, role, "demo", update_supported=True) if args.demo else self.installations[role]
            self.installations[role] = found
            self.jobs[role] = Job(role, TOOLS[role], path=found.path, source=found.source,
                                  installed=found.installed, update_supported=found.update_supported)
        if "hermes" in self.installations and self.installations["hermes"].root:
            self.hermes_root = Path(self.installations["hermes"].root)
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=3, thread_name_prefix="upall")
        self.futures = []
        self.started = time.monotonic()
        self.finished = 0
        self.install_locks = {}

    def update(self, role, **values):
        with self.guard:
            job = self.jobs[role]
            for name, value in values.items():
                setattr(job, name, value)
                if name in {"current", "latest", "status"}:
                    atomic(self.state_dir / f"{role}.{name}", str(value) + "\n")

    def snapshot(self):
        with self.guard:
            return [Job(**asdict(job)) for job in self.jobs.values()]

    def start(self, roles=None, *, install=False):
        if install:
            self.mode = "update"
        self.finished = 0
        self.futures = []
        for role in list(roles or self.jobs):
            self.update(role, status="QUEUED", detail="", started=time.monotonic(), ended=0,
                        attempt=self.jobs[role].attempt + 1)
            self.futures.append(self.pool.submit(self.worker, role, self.mode == "update"))

    def done(self):
        done = all(future.done() for future in self.futures)
        if done and not self.finished:
            self.finished = time.monotonic()
        return done

    def command(self, role, command, *, capture=False, timeout=30, env=None):
        if self.stop.is_set():
            raise CommandError("已停止")
        with (self.log_dir / f"{role}.log").open("ab", buffering=0) as log, tempfile.TemporaryFile() as output:
            log.write(("$ " + shlex.join(map(str, command)) + "\n").encode())
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=output if capture else log, stderr=log,
                                       env=env, start_new_session=True, cwd=Path.home())
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if self.stop.wait(0.08) or time.monotonic() >= deadline:
                    try:
                        os.killpg(process.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        process.wait()
                    raise CommandError("已停止" if self.stop.is_set() else f"命令超时（{timeout}s）")
            text = ""
            if capture:
                output.seek(0)
                text = output.read(4 * 1024 * 1024).decode("utf-8", "replace").strip()
                if text:
                    log.write((text + "\n").encode())
            if process.returncode:
                raise CommandError(f"命令退出码 {process.returncode}")
            return text

    def current_version(self, role):
        if role == "hermes":
            result = self.command(role, ["git", "-C", str(self.hermes_root), "rev-parse", "--short=8", "HEAD"], capture=True)
            if not re.fullmatch(r"[0-9a-f]{8,40}", result):
                raise CommandError("未读到有效的当前提交")
            return result
        output = self.command(role, [self.installations[role].path, "--version"], capture=True)
        match = re.search(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", output)
        if not match:
            raise CommandError("未读到有效的当前版本")
        return match.group()

    def latest_version(self, role):
        found = self.installations[role]
        if found.source == "brew":
            data = json.loads(self.command(role, [found.manager, "info", "--json=v2",
                "--cask" if found.cask else "--formula", found.package], capture=True, timeout=60))
            item = data["casks" if found.cask else "formulae"][0]
            value = item["version"] if found.cask else item["versions"]["stable"]
            return value.split(",", 1)[0]
        if role == "hermes":
            output = self.command(role, [found.path, "--run-module", "hermes_cli.source_check",
                "--install-root", str(self.hermes_root), "--home", os.environ.get("HERMES_HOME") or str(Path.home() / ".hermes"),
                "--cache-path", str(self.log_dir / "hermes-check.json"), "--force"], capture=True, timeout=45)
            data = json.loads(output)
            if not data.get("supported") or data.get("error"):
                raise CommandError(data.get("message") or data.get("reason") or "Hermes 通道检查失败")
            revision = data.get("targetSha" if data.get("updateAvailable") else "currentSha", "")
            if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                raise CommandError("Hermes 未返回有效提交")
            return revision[:8]
        if role == "openclaw":
            data = json.loads(self.command(role, [found.path, "update", "--dry-run", "--json"], capture=True, timeout=60))
            value = data.get("targetVersion")
            if not value:
                raise CommandError(data.get("targetVersionReason") or "OpenClaw 未返回更新目标")
            return value.removeprefix("v")
        package = found.package or next(iter(PACKAGES.get(role, ())), "")
        if role == "claude" and found.channel != "latest":
            package += "@" + found.channel
        command = (["curl", "-fsSL", "--connect-timeout", "6", "--max-time", "20", "https://code.kimi.com/kimi-code/latest"]
                   if role == "kimi" else [found.manager or "npm", "view", package, "version", "--silent"])
        env = dict(os.environ, npm_config_fetch_retries="0", npm_config_fetch_timeout="15000")
        output = self.command(role, command, capture=True, env=env)
        if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", output):
            raise CommandError("未读到有效的最新版本")
        return output

    def install(self, role):
        found = self.installations[role]
        key = (found.source, found.prefix) if found.source in ("brew", "npm") else ("tool", role)
        with self.guard:
            lock = self.install_locks.setdefault(key, threading.Lock())
        while not lock.acquire(timeout=.1):
            if self.stop.is_set():
                raise CommandError("已停止")
        try:
            self.install_one(role)
        finally:
            lock.release()

    def install_one(self, role):
        found = self.installations[role]
        if found.source == "brew":
            self.command(role, [found.manager, "upgrade", "--cask" if found.cask else "--formula", found.package], timeout=1200)
            return
        if role == "openclaw":
            self.command(role, [found.path, "update", "--yes"], timeout=1200)
            return
        if found.source == "npm":
            command = [found.manager, "install", "--global", "--prefix", found.prefix,
                       found.package + "@" + self.jobs[role].latest]
            if role in ("claude", "mcode"):
                command += ["--ignore-scripts=false", "--include=optional", "--allow-scripts=" +
                            ("@anthropic-ai/claude-code" if role == "claude" else "@minimax-ai/code,better-sqlite3")]
            self.command(role, command, timeout=1200,
                         env=dict(os.environ, PATH=str(Path(found.manager).parent) + os.pathsep + os.environ.get("PATH", "")))
            return
        if role == "kimi":
            installer = self.log_dir / "kimi-install.sh"
            self.command(role, ["curl", "-fsSL", "--connect-timeout", "6", "--max-time", "60",
                               "https://code.kimi.com/kimi-code/install.sh", "-o", str(installer)], timeout=65)
            self.command(role, ["bash", str(installer)], timeout=1200,
                         env=dict(os.environ, KIMI_NO_MODIFY_PATH="1"))
        elif role == "mcode":
            installer = self.log_dir / "mcode-install.sh"
            self.command(role, ["curl", "-fsSL", "--connect-timeout", "6", "--max-time", "60",
                               "https://filecdn.minimax.chat/public/install.sh", "-o", str(installer)], timeout=65)
            self.command(role, ["bash", str(installer)], timeout=1200,
                         env=dict(os.environ, MCODE_INSTALL_DIR=found.root, MCODE_NO_MODIFY_PATH="1"))
        else:
            arguments = ["upgrade", "--method", "curl"] if role == "opencode" else ["update"]
            self.command(role, [found.path, *arguments, *(["--yes"] if role == "hermes" else [])], timeout=1200)

    def demo(self, role, install):
        self.stop.wait(0.35)
        self.update(role, current="2.2.0" if role == "kimi" else "1.0.0", latest="2.2.0" if role == "kimi" else "1.1.0")
        if role == "kimi":
            self.update(role, status="CURRENT")
        elif not install:
            self.update(role, status="AVAILABLE")
        else:
            self.update(role, status="UPDATING")
            self.stop.wait(0.7 if role == "codex" else 1.2)
            if os.environ.get("UPALL_TEST_FAILURE") == role and self.jobs[role].attempt == 2:
                raise CommandError("演示：网络暂不可用，按 2 仅重试失败项")
            self.update(role, current="1.1.0", status="UPDATED")
        with (self.log_dir / f"{role}.log").open("a") as log:
            log.write(f"demo: {role} · {LABELS[self.jobs[role].status]}\n")

    def worker(self, role, install):
        phase = "QUERY-FAILED"
        try:
            self.update(role, status="CHECKING")
            with (self.log_dir / f"{role}.log").open("a") as log:
                log.write(f"\n--- 第 {self.jobs[role].attempt} 次 · {time.strftime('%H:%M:%S')} ---\n")
            if self.args.demo:
                phase = "UPDATE-FAILED"
                self.demo(role, install)
                return
            found = self.installations[role]
            if not found.installed:
                self.update(role, status="SKIPPED", detail="未找到可执行命令")
                return
            if found.source == "desktop":
                self.update(role, current=found.version or "-", status="INSTALLED", detail=found.reason)
                return
            if not found.update_supported:
                self.update(role, status="MANUAL", detail=found.reason)
                return
            current = self.current_version(role)
            self.update(role, current=current)
            if self.mode == "inventory":
                self.update(role, status="INSTALLED")
                return
            phase = "CONNECTION-FAILED"
            latest = self.latest_version(role)
            # A stable channel may lag an already-installed newer release; never downgrade.
            if role != "hermes":
                current_core = tuple(map(int, current.split("-", 1)[0].split("+", 1)[0].split(".")))
                latest_core = tuple(map(int, latest.split("-", 1)[0].split("+", 1)[0].split(".")))
                if current_core > latest_core:
                    latest = current
            self.update(role, latest=latest)
            if current == latest:
                self.update(role, status="CURRENT")
                return
            if not install:
                self.update(role, status="AVAILABLE")
                return
            phase = "UPDATE-FAILED"
            self.update(role, status="UPDATING")
            self.install(role)
            self.update(role, status="VERIFYING")
            after = self.current_version(role)
            self.update(role, current=after)
            if after != latest:
                raise CommandError(f"更新未生效：current={after} expected={latest}")
            self.update(role, status="UPDATED")
        except Exception as error:
            detail = clean(str(error))[:500]
            with (self.log_dir / f"{role}.log").open("a") as log:
                log.write(detail + "\n")
            self.update(role, status="CANCELLED" if self.stop.is_set() else phase, detail=detail)
        finally:
            if self.stop.is_set():
                self.update(role, status="CANCELLED", detail="用户已停止")
            self.update(role, ended=time.monotonic())

    def report(self):
        return {"schema": 1, "mode": self.mode, "demo": self.args.demo,
                "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
                "elapsed": round((self.finished or time.monotonic()) - self.started, 2),
                "log_dir": str(self.log_dir), "inventory": [item.public() for item in self.installations.values()],
                "jobs": [dict(asdict(job), elapsed=round(job.elapsed(), 2)) for job in self.snapshot()]}

    def save(self):
        atomic(self.log_dir / "report.json", json.dumps(self.report(), ensure_ascii=False, indent=2) + "\n")
