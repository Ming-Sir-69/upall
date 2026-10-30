"""Concurrent version checks and explicit update execution."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse
import uuid
from .discovery import TOOLS, PACKAGES, DESKTOP_APPS, Installation, discover
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
        self.desktop_feeds = {}
        self.trash_dir = Path.home() / ".Trash"

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
        found = self.installations[role]
        if found.source == "desktop":
            with (Path(found.path) / "Contents/Info.plist").open("rb") as file:
                return str(plistlib.load(file).get("CFBundleShortVersionString", ""))
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
        if found.source == "desktop":
            return self.desktop_latest(role, found)
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

    def desktop_latest(self, role, found):
        """Read-only check of a desktop app's own update feed. Each request uses
        a fresh anonymous id; nothing identifying is persisted. The feed's
        package metadata is kept for a possible explicit update; the download
        URL is only accepted on the vendor's own host."""
        feed = {"version": "", "url": "", "sha256": "", "size": 0}
        if role == "claude-desktop":
            url = ("https://releases.claude.com/api/desktop/darwin/universal/squirrel/update"
                   f"?device_id={uuid.uuid4()}&version={urllib.parse.quote(found.version)}"
                   f"&os_version={platform.mac_ver()[0]}")
            data = json.loads(self.command(role, ["curl", "-fsSL", "--connect-timeout", "6",
                                                  "--max-time", "20", url], capture=True))
            feed["version"] = data.get("currentRelease", "")
            package = (data.get("releases") or [{}])[0].get("updateTo", {})
            feed.update(url=package.get("url", ""), sha256=package.get("sha256", ""),
                        size=package.get("size", 0))
            host = "downloads.claude.ai"
        else:  # ChatGPT's Sparkle appcast
            url = ("https://updates.oaistatic.com/codex/app/appcast"
                   f"?installation_id={uuid.uuid4()}&arch={platform.machine()}"
                   f"&app_version={urllib.parse.quote(found.version)}")
            output = self.command(role, ["curl", "-fsSL", "--connect-timeout", "6",
                                         "--max-time", "20", url], capture=True)
            match = re.search(r"<sparkle:shortVersionString>([^<]+)</sparkle:shortVersionString>", output)
            feed["version"] = match.group(1) if match else ""
            enclosure = re.search(r'<enclosure url="([^"]+)" length="(\d+)"', output)
            if enclosure:
                feed.update(url=enclosure.group(1), size=int(enclosure.group(2)))
            host = "persistent.oaistatic.com"
        if not re.fullmatch(r"\d+(\.\d+){1,3}", feed["version"] or ""):
            raise CommandError("未读到有效的最新版本")
        parsed = urllib.parse.urlparse(feed["url"])
        if parsed.scheme != "https" or parsed.hostname != host:
            feed["url"] = ""  # untrusted package location: manual update only
        self.desktop_feeds[role] = feed
        return feed["version"]

    def desktop_running(self, bundle):
        """True while any process belongs to the app bundle, helpers included."""
        return subprocess.run(["pgrep", "-f", f"{bundle}.app"], capture_output=True).returncode == 0

    def install_desktop(self, role, found):
        """Update a desktop app with its own official update package.

        Claude packages carry a sha256; ChatGPT's feed only offers a Sparkle
        signature (not verifiable with the stdlib), so exact size and host
        pinning are the checks there. The old bundle goes to the Trash,
        never deleted; a running app is left untouched.
        """
        label, bundle = DESKTOP_APPS[role]
        feed = self.desktop_feeds.get(role) or {}
        if self.desktop_running(bundle):
            raise CommandError(f"请先退出 {label}，再按 2 重试")
        app_path = Path(found.path)
        archive = self.log_dir / f"{role}.zip"
        extract = self.log_dir / f"{role}-extract"
        self.command(role, ["curl", "-fsSL", "--connect-timeout", "6", "--max-time", "900",
                            feed["url"], "-o", str(archive)], timeout=960)
        size = archive.stat().st_size
        if feed.get("size") and size != feed["size"]:
            raise CommandError(f"更新包大小不符：{size} != {feed['size']}")
        if feed.get("sha256"):
            digest = hashlib.sha256()
            with archive.open("rb") as file:
                for chunk in iter(lambda: file.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != feed["sha256"]:
                raise CommandError("更新包 sha256 校验失败")
        shutil.rmtree(extract, ignore_errors=True)
        self.command(role, ["ditto", "-x", "-k", str(archive), str(extract)], timeout=120)
        unpacked = extract / f"{bundle}.app"
        try:
            with (unpacked / "Contents/Info.plist").open("rb") as file:
                version = str(plistlib.load(file).get("CFBundleShortVersionString", ""))
        except (OSError, ValueError, plistlib.InvalidFileException):
            raise CommandError("更新包中未找到有效的应用") from None
        if version != feed["version"]:
            raise CommandError(f"更新包版本不符：{version}")
        backup = self.trash_dir / f"{bundle}.app.upall-{time.strftime('%Y%m%d-%H%M%S')}"
        self.command(role, ["mv", str(app_path), str(backup)])
        self.command(role, ["ditto", str(unpacked), str(app_path)], timeout=300)
        archive.unlink(missing_ok=True)
        shutil.rmtree(extract, ignore_errors=True)

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
        if found.source == "desktop":
            self.install_desktop(role, found)
            return
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
                if not found.version:
                    self.update(role, current="-", status="INSTALLED", detail=found.reason)
                    return
                current = found.version
            else:
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
                self.update(role, status="CURRENT", detail=found.reason if found.source == "desktop" else "")
                return
            if found.source == "desktop" and not (self.desktop_feeds.get(role) or {}).get("url"):
                # No trustworthy package URL: desktop apps update themselves.
                self.update(role, status="MANUAL", detail="请在应用内更新")
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
