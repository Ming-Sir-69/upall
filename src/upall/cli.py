"""CLI composition; defaults to checks without installation."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import sys
import time
from . import __version__
from .discovery import TOOLS, DEMO_ROLES, SOURCE_LABELS, discover
from .engine import Engine
from .status import ACTIVE, FAILED, LABELS
from .terminal import Terminal
from .util import fit, private_directory


def plain(engine):
    seen = {}
    if not engine.args.json:
        label = "安装检测" if engine.mode == "inventory" else "自动检查版本" if engine.mode == "check" else "检查并更新"
        print(f"UPALL · {label} · {len(engine.jobs)} 个工具 · 最多 {min(3, len(engine.jobs))} 项并行", flush=True)
    while True:
        done = engine.done()
        for job in engine.snapshot():
            if not engine.args.json and engine.mode != "inventory" and job.status != seen.get(job.role) and job.status not in ACTIVE:
                versions = f"{job.current} → {job.latest}"
                print(f"{job.label}: {LABELS[job.status]} · {versions}" + (f" · {job.detail}" if job.detail else ""), flush=True)
                seen[job.role] = job.status
        if done:
            break
        time.sleep(0.08)
    if engine.mode == "inventory" and not engine.args.json:
        print(f"{fit('工具 [命令]', 32)} {fit('状态', 12)} {fit('版本', 14)} 来源")
        for job in engine.snapshot():
            status = "未安装" if not job.installed else LABELS[job.status]
            print(f"{fit(job.label + ' [' + job.role + ']', 32)} {fit(status, 12)} {fit(job.current, 14)} {SOURCE_LABELS[job.source]}")
            if job.installed:
                print("  " + job.path + (" · " + job.detail if job.detail else ""))


def main(argv=None):
    parser = argparse.ArgumentParser(description="自动发现并检查已安装的 AI CLI；空格更新，回车退出。")
    parser.add_argument("tools", nargs="*", metavar="工具", help="工具名；默认只处理检测到的 CLI")
    parser.add_argument("--version", action="version", version="upall " + __version__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-c", "--check", dest="check", action="store_true", help="检查版本，等待空格更新（默认）")
    mode.add_argument("--update", dest="check", action="store_false", help="显式执行检查并更新，适合脚本")
    parser.set_defaults(check=True)
    parser.add_argument("-r", "--retry", action="store_true", help="只重试上次失败的工具")
    parser.add_argument("--plain", action="store_true", help="纯文本输出")
    parser.add_argument("--json", action="store_true", help="输出最终 JSON，适合脚本")
    parser.add_argument("--no-wait", action="store_true", help="完成后自动退出交互界面")
    parser.add_argument("--demo", action="store_true", help="演示交互，不执行真实更新")
    parser.add_argument("--list", dest="inventory", action="store_true", help="查看全部支持工具的安装状态、版本、来源；不联网检查")
    parser.add_argument("--all", action="store_true", help="同时显示未安装候选；未安装项只跳过")
    args = parser.parse_args(argv)
    args.demo = args.demo or os.environ.get("UPALL_TEST_MODE") == "1"
    unknown = set(args.tools) - TOOLS.keys()
    if unknown:
        parser.error("未知工具：" + ", ".join(sorted(unknown)))
    installations = discover(os.environ.get("UPALL_SEARCH_PATH"))
    if args.inventory:
        args.plain = True
    root = Path(os.environ.get("UPALL_LOG_ROOT") or
                Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local/state") / "upall")
    if args.demo and "UPALL_LOG_ROOT" not in os.environ:
        root = root / "demo"
    root = private_directory(root)
    log_dir = private_directory(root / ("inventory" if args.inventory else "latest"))
    lock_path = root / (".inventory.lock" if args.inventory else ".lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(descriptor, "a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("已有 upall 任务运行中，请在原终端查看。", file=sys.stderr)
            return 2
        roles = list(dict.fromkeys(args.tools)) or (list(TOOLS) if args.inventory or args.all else
                list(DEMO_ROLES) if args.demo else [role for role, item in installations.items()
                                                  if item.installed and item.source != "desktop"])
        if args.retry:
            try:
                previous = json.loads((log_dir / "report.json").read_text())
                candidates = args.tools or list(TOOLS)
                roles = [job["role"] for job in previous["jobs"] if job["role"] in candidates and job["status"] in FAILED]
            except (OSError, ValueError, KeyError, TypeError):
                print("没有可读取的上次结果；请先运行 upall。", file=sys.stderr)
                return 2
            if not roles:
                print(json.dumps({"schema": 1, "jobs": [], "message": "上次没有失败项。"}, ensure_ascii=False)
                      if args.json else "上次没有失败项。")
                return 0
        if not roles:
            message = "未检测到已安装的 AI CLI；可用 upall --list 查看支持列表。"
            print(json.dumps({"schema": 1, "jobs": [], "message": message}, ensure_ascii=False) if args.json else message)
            return 0
        log_dir.mkdir(parents=True, exist_ok=True)
        if not args.retry:
            for role in roles:
                (log_dir / f"{role}.log").write_text("")
        engine = Engine(args, roles, log_dir, installations)
        for role in roles:
            engine.update(role, current="-", latest="-", status="QUEUED")
        prior_handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
        for sig in prior_handlers:
            signal.signal(sig, lambda *_: engine.stop.set())
        engine.start()
        interactive = not (args.plain or args.json or os.environ.get("TERM") == "dumb") and (
            (sys.stdin.isatty() and sys.stdout.isatty()) or os.environ.get("UPALL_FORCE_TUI") == "1")
        try:
            if interactive:
                Terminal(engine).run()
            else:
                plain(engine)
        except BaseException:
            engine.stop.set()
            raise
        finally:
            engine.pool.shutdown(wait=True)
            engine.done()
            engine.save()
            for sig, handler in prior_handlers.items():
                signal.signal(sig, handler)
        if args.json:
            print(json.dumps(engine.report(), ensure_ascii=False))
        else:
            jobs = engine.snapshot()
            if interactive:
                for job in jobs:
                    print(f"{job.label}: {LABELS[job.status]} · {job.current} → {job.latest}")
            print(f"完成 {len(jobs)} 项 · 失败 {sum(job.status in FAILED for job in jobs)} 项 · 日志 {log_dir}")
        return 130 if engine.stop.is_set() else int(any(job.status in FAILED for job in engine.snapshot()))
