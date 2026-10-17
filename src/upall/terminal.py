"""Keyboard decoding and responsive terminal rendering."""
import codecs
import os
import re
import select
import shutil
import sys
import termios
import time
import tty
from .status import ACTIVE, FAILED, LABELS
from .util import fit, tail


class KeyDecoder:
    """Keep split UTF-8 and terminal sequences intact; resolve a lone Escape on idle."""
    CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")

    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.pending = ""
        self.escape_since = None

    def feed(self, data=b"", *, now=None, final=False):
        now = time.monotonic() if now is None else now
        self.pending += self.decoder.decode(data, final=final)
        keys = []
        while self.pending:
            size = 1
            if self.pending.startswith("\x1b"):
                if self.escape_since is None:
                    self.escape_since = now
                age = now - self.escape_since
                if self.pending == "\x1b":
                    if not final and age < 0.1:
                        break
                elif self.pending.startswith("\x1b["):
                    sequence = self.CSI.match(self.pending)
                    if sequence is None:
                        if final or age >= 1:
                            self.pending = ""
                            self.escape_since = None
                        break
                    size = sequence.end()
                elif self.pending.startswith("\x1bO"):
                    if len(self.pending) < 3:
                        if final or age >= 1:
                            self.pending = ""
                            self.escape_since = None
                        break
                    size = 3
                else:
                    # Alt+key is one event, not an Escape followed by a shortcut.
                    size = 2
            keys.append(self.pending[:size])
            self.pending = self.pending[size:]
            self.escape_since = None
        return keys


class Terminal:
    def __init__(self, engine):
        self.engine = engine
        self.selected = 0
        self.show_logs = True
        self.offset = 0
        self.hint = ""
        self.color = "NO_COLOR" not in os.environ
        self.tick = 0

    def paint(self, text, color):
        return f"\033[{color}m{text}\033[0m" if self.color else text

    def frame(self, cols, rows):
        jobs = self.engine.snapshot()
        self.selected %= len(jobs)
        inner = max(1, min(92, cols - 6))
        done = sum(job.status not in ACTIVE for job in jobs)
        ended = self.engine.done()
        failed = sum(job.status in FAILED for job in jobs)
        mode = "安装检测" if self.engine.mode == "inventory" else "自动检查版本" if self.engine.mode == "check" else "检查并更新"
        if self.engine.args.demo:
            mode += " · 演示"
        bar_size = max(5, min(24, inner - 31))
        filled = int(done / len(jobs) * bar_size)
        elapsed = int((self.engine.finished or time.monotonic()) - self.engine.started)
        content = [("UPALL · 工具更新", "1;96"), (f"{mode} · {len(jobs)} 个工具 · 最多 {min(3, len(jobs))} 项并行", "90"),
                   (f"{'━' * filled}{'─' * (bar_size - filled)}  {done}/{len(jobs)} 完成 · {elapsed}s", "96"), ("", "0")]
        wide = inner >= 68
        if wide:
            content.append((f"  {fit('工具', 11)} {fit('当前版本', 15)} {fit('目标版本', 15)} 状态", "90"))
        spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[self.tick % 10]
        row_height = 2 if not wide and rows >= 18 else 1
        capacity = max(1, (rows - (16 if self.show_logs and rows >= 18 else 12)) // row_height)
        if rows < 12:
            capacity = max(1, rows - 6)
        first = max(0, min(self.selected - capacity // 2, len(jobs) - capacity))
        visible = list(enumerate(jobs))[first:first + capacity]
        for index, job in visible:
            icon = spinner if job.status in ACTIVE else "×" if job.status in FAILED else "!" if job.status == "MANUAL" else "↑" if job.status == "AVAILABLE" else "✓" if job.status != "SKIPPED" else "–"
            status = f"{icon} {LABELS[job.status]}"
            color = "91" if job.status in FAILED else "93" if job.status in {"AVAILABLE", "UPDATING", "VERIFYING", "MANUAL"} else "92" if job.status in {"CURRENT", "UPDATED", "INSTALLED"} else "90" if job.status == "SKIPPED" else "96"
            prefix = "›" if index == self.selected else " "
            if wide:
                text = f"{prefix} {fit(job.label, 11)} {fit(job.current, 15)} {fit(job.latest, 15)} {status} · {int(job.elapsed())}s"
                content.append((text, color))
            else:
                content.append((f"{prefix} {job.label}  {status} · {int(job.elapsed())}s", color))
                if rows >= 18:
                    content.append((f"  {job.current} → {job.latest}", "90"))
        if len(jobs) > capacity and rows >= 12:
            content.append((f"显示 {first + 1}–{min(first + capacity, len(jobs))}/{len(jobs)} · ↑↓ 浏览", "90"))
        content.append(("", "0"))
        chosen = jobs[self.selected]
        if self.show_logs and rows >= 18:
            content.append((f"日志 · {chosen.label}   [ / ] 滚动", "96"))
            count = max(1, min(5, rows - len(content) - 7))
            lines = tail(self.engine.log_dir / f"{chosen.role}.log", count, self.offset)
            content.extend((line, "90") for line in (lines or ["等待输出…"]))
            content.append(("", "0"))
        if self.hint:
            content.append((self.hint, "93"))
        elif ended:
            available = sum(job.status == "AVAILABLE" for job in jobs)
            manual = sum(job.status == "MANUAL" for job in jobs)
            message = f"任务已结束 · {failed} 项失败" if failed else f"检查完成 · {available} 项可更新，按空格开始" if available else f"检查完成 · {manual} 项需手动处理" if manual else "全部完成"
            content.append((message, "91" if failed else "92"))
        else:
            content.append(("正在并行检查版本" if self.engine.mode == "check" else "正在并行检查和更新", "90"))
        if ended:
            actions = "空格/1 更新 · 2 重试 · 3 日志 · ↑↓ 选择"
            content.append((actions, "90"))
            content.append(("回车/0 返回终端 · Esc 退出" if inner >= 26 else "回车/0 退出", "90"))
        else:
            help_text = "↑↓ 选择 · 3 日志 · Ctrl-C 停止" if inner >= 34 else "3 日志 · Ctrl-C 停止" if inner >= 20 else "Ctrl-C 停止"
            content.append((help_text, "90"))
        if rows < 12:
            content = [content[0], content[2],
                       *[(f"{'›' if i == self.selected else ' '} {job.label} · {LABELS[job.status]}", "96") for i, job in visible],
                       content[-1]]
        limit = max(1, rows - 3)
        if len(content) > limit:
            content = content[:max(0, limit - 1)] + [content[-1]]
        border = "─" * (inner + 2)
        lines = [self.paint("╭" + border + "╮", "90")]
        lines += [self.paint("│ ", "90") + self.paint(fit(text, inner), color) + self.paint(" │", "90") for text, color in content]
        lines.append(self.paint("╰" + border + "╯", "90"))
        return lines

    def draw(self):
        try:
            size = os.get_terminal_size(sys.stdout.fileno())
            if not size.columns or not size.lines:
                size = shutil.get_terminal_size((80, 24))
        except OSError:
            size = shutil.get_terminal_size((80, 24))
        lines = self.frame(size.columns, size.lines)
        margin = " " * max(0, (size.columns - min(96, size.columns - 2)) // 2)
        rendered = [margin + line for line in lines]
        rendered += [""] * max(0, size.lines - 1 - len(rendered))
        sys.stdout.write("\033[H" + "\n".join("\033[2K" + line for line in rendered) + "\033[J")
        sys.stdout.flush()
        self.tick += 1

    def key(self, key):
        key = key.translate(str.maketrans("０１２３　", "0123 "))
        jobs = self.engine.snapshot()
        if key in ("\x03", "\x04"):
            self.engine.stop.set()
        elif key in ("\x1b[A", "\x1bOA", "k", "K"):
            self.selected = (self.selected - 1) % len(jobs)
            self.offset = 0
        elif key in ("\x1b[B", "\x1bOB", "j", "J", "\t"):
            self.selected = (self.selected + 1) % len(jobs)
            self.offset = 0
        elif key.lower() in ("3", "l"):
            self.show_logs = not self.show_logs
        elif key == "[":
            self.offset = min(1000, self.offset + 3)
        elif key == "]":
            self.offset = max(0, self.offset - 3)
        elif key.lower() in ("\r", "\n", "0", "\x1b", "q", "x"):
            if self.engine.done():
                return False
            self.hint = "任务运行中；完成后回车/0 退出"
        elif self.engine.done() and key.lower() in (" ", "1", "2", "r", "u"):
            retry = key.lower() in ("2", "r")
            wanted = [job.role for job in jobs if job.status in (FAILED if retry else {"AVAILABLE"})]
            if wanted:
                self.hint = ""
                self.offset = 0
                self.engine.start(wanted, install=not retry)
            else:
                self.hint = "没有失败项" if retry else "没有可更新项"
        return True

    def run(self):
        terminal = os.isatty(sys.stdin.fileno())
        previous = termios.tcgetattr(sys.stdin.fileno()) if terminal else None
        alternate = os.environ.get("UPALL_NO_ALT_SCREEN") != "1"
        saved, eof = False, False
        decoder = KeyDecoder()
        try:
            if terminal:
                tty.setcbreak(sys.stdin.fileno())
            sys.stdout.write(("\033[?1049h" if alternate else "") + "\033[?25l\033[2J")
            while True:
                if self.engine.done() and not saved:
                    self.engine.save()
                    saved = True
                if self.engine.stop.is_set():
                    break
                self.draw()
                if self.engine.done() and (self.engine.args.no_wait or eof):
                    break
                ready, _, _ = select.select([] if eof else [sys.stdin], [], [], 0.12)
                keys = []
                if ready:
                    data = os.read(sys.stdin.fileno(), 64)
                    if not data:
                        eof = True
                    keys = decoder.feed(data, final=eof)
                elif not eof:
                    keys = decoder.feed()
                for key in keys:
                    if not self.key(key):
                        return
                    if not self.engine.done():
                        saved = False
        finally:
            if previous is not None:
                termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, previous)
            sys.stdout.write("\033[?25h" + ("\033[?1049l" if alternate else ""))
            sys.stdout.flush()
