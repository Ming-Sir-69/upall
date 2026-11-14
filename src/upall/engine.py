"""Concurrent version checks and explicit update execution."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import signal
import subprocess
import tempfile
import threading
import time
import urllib.parse
from .discovery import APP_BUNDLES, GROUPS, PACKAGES, Installation, app_info, discover
from .models import Job
from . import overlay as overlays
from .status import LABELS
from .util import atomic, clean, private_directory

VERSION = re.compile(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?")
GITHUB_LATEST = {"cc-switch": "farion1231/cc-switch", "mole": "tw93/Mole"}


def newer(current, latest):
    """True when current is a strictly newer release than latest (never downgrade)."""
    try:
        core = lambda v: tuple(map(int, v.lstrip("vV").split("-", 1)[0].split("+", 1)[0].split(".")))
        return core(current) > core(latest)
    except ValueError:
        return False


class CommandError(Exception):
    pass


class ManualError(Exception):
    """The tool's own check says it must be handled by hand."""


class Engine:
    def __init__(self, args, roles, log_dir, installations=None, preserve=None, hooks=None):
        self.args, self.log_dir = args, log_dir
        self.mode = "inventory" if getattr(args, "inventory", False) else "check" if args.check else "update"
        self.state_dir = log_dir / "state"
        private_directory(self.state_dir)
        self.hermes_root = Path.home() / ".hermes/hermes-agent"
        self.installations = installations or (dict.fromkeys(roles) if args.demo else discover(os.environ.get("UPALL_SEARCH_PATH")))
        self.preserve = preserve or {}
        self.hooks = hooks or {}
        self.meta = {}
        self.jobs = {}
        for role in roles:
            found = self.installations.get(role)
            if args.demo:
                known = found if isinstance(found, Installation) else Installation(role)
                found = Installation(role, role, "demo", update_supported=True,
                                     label=known.label, group=known.group)
            self.installations[role] = found
            self.jobs[role] = Job(role, found.label, path=found.path, source=found.source, group=found.group,
                                  installed=found.installed, update_supported=found.update_supported,
                                  overlay=self.preserve_text(role))
        if "hermes" in self.installations and self.installations["hermes"].root:
            self.hermes_root = Path(self.installations["hermes"].root)
        self.guard = threading.RLock()
        self.stop = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="upall")
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

    def preserve_text(self, role):
        count = len(self.preserve.get(role, ())) + (1 if role in self.hooks else 0)
        return f"保留 {count}" if count else ""

    def log(self, role, text):
        with (self.log_dir / f"{role}.log").open("a") as log:
            log.write(clean(text) + "\n")

    def record_network(self, role, operation, tool, route, attempt, started, elapsed, *,
                       size=None, error=""):
        event = {"operation": operation, "tool": tool, "route": route, "attempt": attempt,
                 "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(started)),
                 "elapsed": round(elapsed, 2), "status": "failed" if error else "success"}
        if size is not None:
            event["bytes"] = size
            event["bytes_per_second"] = round(size / elapsed) if elapsed > 0 else 0
        if error:
            event["error"] = clean(str(error))[:300]
        with self.guard:
            self.jobs[role].network.append(event)
        route_label = "直连" if route == "direct" else "继承环境代理"
        detail = (f"网络记录：{operation} · 第 {attempt} 次 · {route_label} · {tool} · "
                  f"{'失败' if error else '成功'} · {elapsed:.2f}s")
        if size is not None:
            detail += f" · {size} B"
            if elapsed > 0:
                detail += f" · {size / elapsed / 1048576:.2f} MiB/s"
        if error:
            detail += f" · {error}"
        self.log(role, detail)

    def network_env(self, direct, extra=None):
        env = dict(os.environ)
        if direct:
            for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy",
                        "npm_config_proxy", "npm_config_https_proxy", "NODE_USE_ENV_PROXY"):
                env.pop(key, None)
        env.update(extra or {})
        return env

    def network_command(self, role, command, operation, route, attempt, *,
                        capture=False, timeout=30, env=None, artifact=None):
        started_wall, started = time.time(), time.monotonic()
        try:
            result = self.command(role, command, capture=capture, timeout=timeout, env=env)
            size = artifact.stat().st_size if artifact else len(result.encode()) if capture else None
            if artifact and size <= 0:
                raise CommandError("下载文件为空")
        except Exception as error:
            self.record_network(role, operation, Path(command[0]).name, route, attempt, started_wall,
                                time.monotonic() - started, error=error)
            raise
        self.record_network(role, operation, Path(command[0]).name, route, attempt, started_wall,
                            time.monotonic() - started, size=size)
        return result

    def npm_command(self, role, command, operation, *, capture=False, timeout=30, extra_env=None):
        for attempt, direct in enumerate((True, False), 1):
            route = "direct" if direct else "inherited"
            env = self.network_env(direct, dict(extra_env or {}, npm_config_fetch_retries="0",
                                                npm_config_fetch_timeout="15000"))
            try:
                return self.network_command(role, command, operation, route, attempt, capture=capture,
                                            timeout=min(timeout, 180) if direct else timeout, env=env)
            except CommandError:
                if self.stop.is_set() or not direct:
                    raise
                self.log(role, "直连失败；本次操作改用继承环境代理")
        raise AssertionError("unreachable")

    def download_file(self, role, url, archive, *, sha256="", size=0):
        aria2 = shutil.which("aria2c")
        commands = []
        if aria2:
            commands.append([aria2, "-x8", "-s8", "-k1M", "--file-allocation=none",
                             "--max-tries=3", "--retry-wait=2", "--connect-timeout=20",
                             "--show-console-readout=false", "--summary-interval=5",
                             "--dir", str(archive.parent), "--out", archive.name, url])
        commands.append(["curl", "-fsSL", "--retry", "3", "--retry-delay", "2", "--retry-all-errors",
                         "-C", "-", "--connect-timeout", "20", "--max-time", "1500", url,
                         "-o", str(archive)])
        for attempt, command in enumerate(commands, 1):
            if attempt > 1:
                self.log(role, f"多连接下载失败；删除不完整文件并回退 {Path(command[0]).name}")
                archive.unlink(missing_ok=True)
                Path(str(archive) + ".aria2").unlink(missing_ok=True)
            try:
                self.network_command(role, command, "download", "inherited", attempt,
                                     timeout=1800 if aria2 and attempt == 1 else 1600, artifact=archive)
            except CommandError:
                if self.stop.is_set() or attempt == len(commands):
                    raise
            else:
                self.verify_download(role, archive, sha256=sha256, size=size)
                return
        raise AssertionError("unreachable")

    def verify_download(self, role, archive, *, sha256="", size=0):
        actual_size = archive.stat().st_size
        if size and actual_size != size:
            raise CommandError(f"下载文件大小不符：{actual_size} != {size}")
        if sha256:
            digest = hashlib.sha256()
            with archive.open("rb") as file:
                for chunk in iter(lambda: file.read(1 << 20), b""):
                    digest.update(chunk)
            if digest.hexdigest() != sha256:
                raise CommandError("下载文件 sha256 校验失败")
            self.log(role, "校验：官方 sha256 通过")
        if size:
            self.log(role, f"校验：文件大小 {actual_size} B 通过")

    def command(self, role, command, *, capture=False, timeout=30, env=None, code=False, merge=False, cwd=None):
        """Run argv; capture returns stdout, code returns the exit status instead of raising."""
        if self.stop.is_set():
            raise CommandError("已停止")
        with (self.log_dir / f"{role}.log").open("ab", buffering=0) as log, tempfile.TemporaryFile() as output:
            log.write(("$ " + shlex.join(map(str, command)) + "\n").encode())
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL,
                                       stdout=output if capture else log,
                                       stderr=output if capture and merge else log,
                                       env=env, start_new_session=True, cwd=cwd or Path.home())
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
            if code:
                return process.returncode
            if process.returncode:
                raise CommandError(f"命令退出码 {process.returncode}")
            return text

    def git(self, role, repo):
        def run(*args, code=False, timeout=60):
            return self.command(role, ["git", "-C", repo, *args], capture=not code, code=code, timeout=timeout)
        return run

    def fetch_json(self, role, url, timeout=20):
        output = self.network_command(role, ["curl", "-fsSL", "--connect-timeout", "8", "--max-time", str(timeout),
                                             "-H", "Accept: application/vnd.github+json",
                                             "-H", "User-Agent: upall", url],
                                      "metadata", "inherited", 1, capture=True, timeout=timeout + 5)
        try:
            return json.loads(output)
        except ValueError:
            raise CommandError("远端返回的不是 JSON") from None

    def tool_json(self, role, argv, timeout=60):
        output = self.command(role, argv, capture=True, timeout=timeout)
        start = output.find("{")
        try:
            data = json.loads(output[start:]) if start >= 0 else None
        except ValueError:
            data = None
        if not isinstance(data, dict):
            raise CommandError("工具未返回有效 JSON")
        return data

    def webbridge_status(self, role):
        found = self.installations[role]
        data = self.tool_json(role, [found.path, "status"], timeout=20)
        if not data.get("running"):
            raise CommandError("WebBridge 守护进程未运行；先执行 kimi-webbridge start")
        return data

    def current_version(self, role):
        found = self.installations[role]
        kind = found.spec.get("kind")
        if kind == "command":
            data = self.tool_json(role, found.spec["check"], timeout=min(600, found.spec["timeout"]))
            self.meta[role] = data
            return clean(str(data.get("current", "")))[:40] or "-"
        if kind == "git":
            git = self.git(role, found.spec["repo"])
            return git("rev-parse", "--short=8", "HEAD")
        if role in APP_BUNDLES:
            version = app_info(found.path).get("version", "")
            self.log(role, f"{found.path} · CFBundleShortVersionString={version}")
            if not VERSION.fullmatch(version) and not re.fullmatch(r"\d+\.\d+", version):
                raise CommandError("未读到应用版本")
            return version
        if role == "kimi-webbridge":
            data = self.webbridge_status(role)
            self.meta[role] = data
            return str(data.get("version", "")).removeprefix("v") or "-"
        if role == "cursor-agent":
            data = self.tool_json(role, [found.path, "about", "--format", "json"], timeout=45)
            self.meta[role] = data
            version = str(data.get("cliVersion", ""))
            if not VERSION.fullmatch(version):
                raise CommandError("未读到有效的当前版本")
            return version
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
        kind = found.spec.get("kind")
        if kind == "command":
            data = self.meta.get(role) or {}
            if data.get("manual"):
                raise ManualError(clean(str(data["manual"]))[:200])
            info = data.get("overlay") or {}
            if info:
                state = overlays.Overlay(local=int(info.get("local", 0)), absorbed=int(info.get("absorbed", 0)),
                                         conflict=bool(info.get("conflict")), note=clean(str(info.get("note", "")))[:80])
                self.update(role, overlay=state.text())
            return clean(str(data.get("latest", "")))[:40] or "-"
        if kind == "git":
            git = self.git(role, found.spec["repo"])
            state = overlays.git_state(git, found.spec["remote"], found.spec["branch"])
            self.meta[role] = state
            self.update(role, overlay=state["overlay"].text(), detail=state["overlay"].note)
            if state["behind"] == 0:
                return git("rev-parse", "--short=8", "HEAD")
            return state["upstream"][:8]
        if role == "kimi-cu":
            data = self.fetch_json(role, "https://cdn.kimi.com/kimi-computer-use/latest/version.json")
            package = data.get("app" if platform.machine() == "arm64" else "app_x86_64") or {}
            url = str(package.get("url", ""))
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "cdn.kimi.com" or \
                    not re.fullmatch(r"[0-9a-f]{64}", str(package.get("sha256", ""))):
                raise CommandError("KimiCU 更新清单无效")
            self.meta[role] = {"url": url, "sha256": package["sha256"], "team": str(package.get("team_id", ""))}
            version = str(data.get("version", ""))
            if not VERSION.fullmatch(version):
                raise CommandError("未读到有效的最新版本")
            return version
        if role == "cc-switch":
            data = self.fetch_json(role, f"https://api.github.com/repos/{GITHUB_LATEST[role]}/releases/latest")
            version = str(data.get("tag_name", "")).removeprefix("v")
            asset = next((a for a in data.get("assets", [])
                          if str(a.get("name", "")).endswith("-macOS.zip")), {})
            url = str(asset.get("browser_download_url", ""))
            digest = str(asset.get("digest", ""))
            sha256 = digest.removeprefix("sha256:") if digest.startswith("sha256:") else ""
            parsed = urllib.parse.urlparse(url)
            if not VERSION.fullmatch(version) or parsed.scheme != "https" or parsed.hostname != "github.com" or \
                    digest and not re.fullmatch(r"[0-9a-f]{64}", sha256):
                raise CommandError("CC Switch 发布信息无效")
            self.meta[role] = {"url": url, "sha256": sha256}
            return version
        if role == "mole" and found.source != "brew":
            for release in self.fetch_json(role, f"https://api.github.com/repos/{GITHUB_LATEST[role]}/releases?per_page=15"):
                tag = str(release.get("tag_name", ""))
                if re.fullmatch(r"V\d+\.\d+\.\d+", tag) and not release.get("draft") and not release.get("prerelease"):
                    return tag[1:]
            raise CommandError("未找到 Mole 正式版")
        if role == "kimi-webbridge":
            data = self.meta.get(role) or self.webbridge_status(role)
            target = (data.get("version_mismatch") or {}).get("extension") or \
                (data.get("update_available") or {}).get("latest") or data.get("version", "")
            target = str(target).removeprefix("v")
            if not VERSION.fullmatch(target):
                raise CommandError("WebBridge 未返回有效版本")
            return target
        if role == "iphone-use":
            data = self.tool_json(role, [found.path, "upgrade", "--json"], timeout=45)
            version = str(data.get("latest", ""))
            if not VERSION.fullmatch(version):
                raise CommandError("未读到有效的最新版本")
            return version
        if role == "cursor-agent":
            data = self.meta.get(role) or {}
            version = str(data.get("latestVersion", ""))
            if not VERSION.fullmatch(version):
                raise CommandError("未读到有效的最新版本")
            return version
        if role == "kimi" and found.source == "script":
            # The native /latest marker can lag published releases. Read the
            # official npm channel without requiring npm, then ensure the same
            # release has a native package for this installation's platform.
            data = self.fetch_json(role, "https://registry.npmjs.org/@moonshot-ai/kimi-code/latest")
            version = data.get("version") if isinstance(data, dict) else None
            if not isinstance(version, str) or not VERSION.fullmatch(version):
                raise CommandError("Kimi 发布信息未返回有效版本")
            system = {"Darwin": "darwin", "Linux": "linux"}.get(platform.system())
            arch = {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x64", "AMD64": "x64"}.get(platform.machine())
            if not system or not arch:
                raise ManualError("此平台的 Kimi 原生安装尚未支持")
            target = f"{system}-{arch}"
            manifest = self.fetch_json(role, f"https://code.kimi.com/kimi-code/binaries/{version}/manifest.json")
            platforms = manifest.get("platforms") if isinstance(manifest, dict) else None
            package = platforms.get(target) if isinstance(platforms, dict) else None
            if not isinstance(package, dict) or manifest.get("version") != version or \
                    package.get("filename") != f"kimi-code-{target}" or \
                    not re.fullmatch(r"[0-9a-f]{64}", str(package.get("checksum", ""))):
                raise CommandError(f"Kimi {version} 的原生发布清单无效或缺少 {target}")
            return version
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
        command = [found.manager or "npm", "view", package, "version", "--silent"]
        output = self.npm_command(role, command, "version-check", capture=True)
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
        records = []
        try:
            paths = list(self.preserve.get(role, ()))
            if role == "kimi-webbridge":
                # The upgrade rewrites every installed skill copy; links must stay links.
                paths += [Path(item["path"]) for item in (self.meta.get(role) or {}).get("skills", [])
                          if isinstance(item, dict) and Path(str(item.get("path", ""))).is_symlink()]
            if paths:
                records = overlays.snapshot(paths, self.state_dir / "preserve" / role)
            self.install_one(role)
        finally:
            try:
                if records:
                    overlays.restore(records, lambda text: self.log(role, text))
            finally:
                lock.release()
        if role in self.hooks:
            # Re-apply our modification on top of the new upstream release.
            self.command(role, self.hooks[role], timeout=300)

    def install_one(self, role):
        found = self.installations[role]
        kind = found.spec.get("kind")
        if kind == "command":
            self.command(role, found.spec["update"], timeout=found.spec["timeout"])
            return
        if kind == "git":
            git = self.git(role, found.spec["repo"])
            try:
                overlays.git_converge(git, found.spec["remote"], found.spec["branch"], self.meta[role],
                                      lambda text: self.log(role, text))
            except RuntimeError as error:
                raise CommandError(str(error)) from None
            if found.spec.get("after_update"):
                self.command(role, found.spec["after_update"], timeout=found.spec["timeout"], cwd=found.spec["repo"])
            return
        if role in APP_BUNDLES:
            self.install_app(role)
            return
        if role in ("kimi-webbridge", "iphone-use"):
            self.command(role, [found.path, "upgrade"], timeout=900)
            return
        if role == "mole" and found.source != "brew":
            self.command(role, [found.path, "update"], timeout=900)
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
            if role in ("claude", "mcode", "agent-desktop"):
                command += ["--ignore-scripts=false", "--include=optional", "--allow-scripts=" +
                            {"claude": "@anthropic-ai/claude-code", "mcode": "@minimax-ai/code,better-sqlite3",
                             "agent-desktop": "agent-desktop"}[role]]
            self.npm_command(role, command, "install", timeout=1200,
                             extra_env={"PATH": str(Path(found.manager).parent) + os.pathsep + os.environ.get("PATH", "")})
            return
        if role == "kimi":
            version = self.jobs[role].latest
            if not VERSION.fullmatch(version):
                raise CommandError("Kimi 更新目标版本无效")
            installer = self.log_dir / "kimi-install.sh"
            self.command(role, ["curl", "-fsSL", "--connect-timeout", "6", "--max-time", "60",
                               "https://code.kimi.com/kimi-code/install.sh", "-o", str(installer)], timeout=65)
            self.command(role, ["bash", str(installer), "--version", version], timeout=1200,
                         env=dict(os.environ, KIMI_NO_MODIFY_PATH="1", KIMI_VERSION=version,
                                  KIMI_INSTALL_DIR=str(Path(found.path).resolve().parent.parent)))
        elif role == "mcode":
            installer = self.log_dir / "mcode-install.sh"
            self.command(role, ["curl", "-fsSL", "--connect-timeout", "6", "--max-time", "60",
                               "https://filecdn.minimax.chat/public/install.sh", "-o", str(installer)], timeout=65)
            self.command(role, ["bash", str(installer)], timeout=1200,
                         env=dict(os.environ, MCODE_INSTALL_DIR=found.root, MCODE_NO_MODIFY_PATH="1"))
        elif role == "claude" and found.source == "native":
            self.install_claude_native(role)
        else:
            arguments = ["upgrade", "--method", "curl"] if role == "opencode" else ["update"]
            self.command(role, [found.path, *arguments, *(["--yes"] if role == "hermes" else [])], timeout=1200)

    def install_claude_native(self, role):
        version = self.jobs[role].latest
        machine = platform.machine()
        target = {"arm64": "darwin-arm64", "aarch64": "darwin-arm64",
                  "x86_64": "darwin-x64", "amd64": "darwin-x64"}.get(machine)
        if not target:
            raise CommandError(f"Claude Code 暂不支持此架构：{machine}")
        base = f"https://downloads.claude.ai/claude-code-releases/{version}"
        manifest = self.fetch_json(role, base + "/manifest.json")
        try:
            item = manifest["platforms"][target]
            expected_size = int(item["size"])
            expected_hash = str(item["checksum"])
        except (KeyError, TypeError, ValueError):
            raise CommandError("Claude Code 官方清单缺少当前平台") from None
        if item.get("binary") != "claude" or expected_size <= 0 or not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
            raise CommandError("Claude Code 官方清单无效")
        work = self.log_dir / "claude-package"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(mode=0o700)
        binary = work / "claude"
        zstd = shutil.which("zstd")
        compressed = False
        if zstd:
            try:
                zmanifest = self.fetch_json(role, base + "/manifest.zst.json")
                zitem = zmanifest["platforms"][target]
                zsize, zhash = int(zitem["size"]), str(zitem["checksum"])
                if zitem.get("binary") != "claude.zst" or zsize <= 0 or not re.fullmatch(r"[0-9a-f]{64}", zhash):
                    raise ValueError("invalid compressed manifest")
                archive = work / "claude.zst"
                self.download_file(role, base + f"/{target}/claude.zst", archive, sha256=zhash, size=zsize)
                compressed = True
            except (CommandError, KeyError, TypeError, ValueError) as error:
                self.log(role, f"压缩包不可用；回退官方完整程序：{error}")
        if compressed:
            self.command(role, [zstd, "-d", "-q", "-f", str(archive), "-o", str(binary)], timeout=300)
        else:
            self.download_file(role, base + f"/{target}/claude", binary,
                               sha256=expected_hash, size=expected_size)
        self.verify_download(role, binary, sha256=expected_hash, size=expected_size)
        binary.chmod(0o700)
        self.command(role, [str(binary), "install", version], timeout=300)
        shutil.rmtree(work, ignore_errors=True)

    def team(self, role, bundle):
        output = self.command(role, ["codesign", "-d", "--verbose=2", str(bundle)], capture=True, merge=True)
        match = re.search(r"^TeamIdentifier=([A-Z0-9]{10})$", output, re.M)
        return match.group(1) if match else ""

    def app_running(self, bundle):
        return subprocess.run(["pgrep", "-f", f"{bundle}/Contents/MacOS/"], capture_output=True).returncode == 0

    def install_app(self, role):
        """Replace an app bundle with the vendor's package after signature checks.

        Trust anchors: manifest sha256 when offered, a valid strict code
        signature, and the same Developer ID team as the installed copy.
        The previous bundle is kept as the role's single rollback copy.
        """
        name, bundle_id, service = APP_BUNDLES[role]
        found = self.installations[role]
        meta = self.meta.get(role) or {}
        destination = Path(found.path)
        work = self.log_dir / f"{role}-package"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(mode=0o700)
        archive = work / "package.zip"
        self.download_file(role, meta["url"], archive, sha256=meta.get("sha256", ""))
        self.command(role, ["ditto", "-x", "-k", str(archive), str(work / "x")], timeout=300)
        apps = [p for p in (work / "x").glob("*.app") if app_info(p).get("id") == bundle_id]
        if len(apps) != 1:
            raise CommandError("更新包中未找到对应的应用")
        unpacked = apps[0]
        if app_info(unpacked).get("version") != self.jobs[role].latest:
            raise CommandError(f"更新包版本不符：{app_info(unpacked).get('version')}")
        self.command(role, ["codesign", "--verify", "--deep", "--strict", str(unpacked)], timeout=180)
        expected = self.team(role, destination)
        if not expected or self.team(role, unpacked) != expected or (meta.get("team") and meta["team"] != expected):
            raise CommandError("更新包签名团队与已安装应用不一致")
        reopen = False
        if self.app_running(destination):
            if not service:
                self.command(role, ["osascript", "-e", f'tell application id "{bundle_id}" to quit'], timeout=20, code=True)
                for _ in range(60):
                    if not self.app_running(destination) or self.stop.wait(.25):
                        break
                if self.app_running(destination):
                    raise CommandError(f"{name} 仍在运行；退出后按 2 重试")
                reopen = True
        backups = private_directory(self.log_dir.parent / "backups")
        backup = backups / f"{name}.app"
        shutil.rmtree(backup, ignore_errors=True)
        try:
            os.rename(destination, backup)
        except OSError:
            self.command(role, ["ditto", str(destination), str(backup)], timeout=300)
            shutil.rmtree(destination)
        try:
            try:
                os.rename(unpacked, destination)
            except OSError:
                self.command(role, ["ditto", str(unpacked), str(destination)], timeout=300)
        except BaseException:
            shutil.rmtree(destination, ignore_errors=True)
            os.rename(backup, destination)
            raise
        self.log(role, f"旧版本保留在 {backup}")
        shutil.rmtree(work, ignore_errors=True)
        if service:
            uid = os.getuid()
            if self.command(role, ["launchctl", "print", f"gui/{uid}/{service}"], capture=True, code=True) == 0:
                self.command(role, ["launchctl", "kickstart", "-k", f"gui/{uid}/{service}"], timeout=30)
        if reopen:
            self.command(role, ["open", "-g", "-b", bundle_id], timeout=30, code=True)

    def verify(self, role, latest):
        """Read the version after an update; returns (current, ok)."""
        found = self.installations[role]
        kind = found.spec.get("kind")
        if kind == "git":
            git = self.git(role, found.spec["repo"])
            after = git("rev-parse", "--short=8", "HEAD")
            upstream = f"{found.spec['remote']}/{found.spec['branch']}"
            return after, git("merge-base", "--is-ancestor", upstream, "HEAD", code=True) == 0
        if role == "kimi-webbridge":
            for _ in range(40):
                try:
                    data = self.webbridge_status(role)
                    after = str(data.get("version", "")).removeprefix("v")
                    return after, after == latest
                except CommandError:
                    if self.stop.wait(.5):
                        break
            raise CommandError("升级后 WebBridge 守护进程未恢复")
        after = self.current_version(role)
        if kind == "command":
            # The adapter's own fresh check decides: current must now equal its latest.
            data = self.meta.get(role) or {}
            return after, after == clean(str(data.get("latest", "")))[:40]
        return after, after == latest

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
            if not found.update_supported:
                self.update(role, status="MANUAL", detail=found.reason)
                return
            current = self.current_version(role)
            self.update(role, current=current)
            if self.mode == "inventory":
                self.update(role, status="INSTALLED")
                return
            phase = "CONNECTION-FAILED"
            try:
                latest = self.latest_version(role)
            except ManualError as error:
                self.update(role, status="MANUAL", detail=str(error))
                return
            # Keep the queried value visible when the channel trails the local
            # install. Never disguise stale metadata as a successful equality.
            self.update(role, latest=latest)
            if role != "hermes" and newer(current, latest):
                self.update(role, status="AHEAD", detail="本机版本高于查询渠道，保留本机版本")
                return
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
            after, ok = self.verify(role, latest)
            self.update(role, current=after)
            if not ok:
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
                "log_dir": str(self.log_dir), "groups": GROUPS,
                "inventory": [item.public() for item in self.installations.values() if isinstance(item, Installation)],
                "jobs": [dict(asdict(job), elapsed=round(job.elapsed(), 2)) for job in self.snapshot()]}

    def save(self):
        report = self.report()
        atomic(self.log_dir / "report.json", json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        history = self.log_dir.parent / "history.jsonl"
        descriptor = os.open(history, os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(descriptor, "a", encoding="utf-8") as log:
            log.write(json.dumps(report, ensure_ascii=False) + "\n")
