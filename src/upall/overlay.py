"""Local modifications versus upstream: what is ours, what upstream absorbed.

Git checkouts: every local commit missing from upstream is classified with
cheap git plumbing instead of comparing whole trees:
  1. `git cherry` patch-id match  -> absorbed (upstream took it verbatim)
  2. files the commit touched are identical in upstream -> absorbed
     (squash merges, reworded or re-authored commits)
  3. otherwise it is still ours and must be kept.
`git merge-tree --write-tree` predicts conflicts without touching the worktree.

Preserved paths: customised copies are snapshotted before an upstream
update and restored afterwards; a symlink stays a symlink.
"""
from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
import time

MAX_BRANCHES = 40
MAX_COMMITS = 200


@dataclass
class Overlay:
    local: int = 0          # our modifications still needed
    absorbed: int = 0       # our modifications upstream now carries
    conflict: bool = False
    note: str = ""
    branches: dict = field(default_factory=dict)

    def text(self):
        if self.conflict:
            return f"冲突 · 本地 {self.local}"
        parts = []
        if self.local:
            parts.append(f"保留 {self.local}")
        if self.absorbed:
            parts.append(f"已收敛 {self.absorbed}")
        return " · ".join(parts) or "无"  # notes go to the job detail, not the column


def classify_branch(git, upstream, ref):
    """Return (pending, absorbed) commit lists for one local ref."""
    pending, absorbed = [], []
    lines = git("cherry", upstream, ref).splitlines()[-MAX_COMMITS:]
    for line in lines:
        sign, _, commit = line.partition(" ")
        if sign == "-":
            absorbed.append(commit)
            continue
        files = [f for f in git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", commit).splitlines() if f]
        if files and git("diff", "--quiet", commit, upstream, "--", *files, code=True) == 0:
            absorbed.append(commit)
        else:
            pending.append(commit)
    return pending, absorbed


def git_state(git, remote, branch, *, fetch=True):
    """Inspect a checkout. `git(*args, code=False)` runs git in the repo."""
    if fetch:
        git("fetch", "--quiet", "--no-tags", remote, branch, timeout=90)
    upstream = f"{remote}/{branch}"
    head = git("rev-parse", "HEAD")
    up = git("rev-parse", upstream)
    current_branch = git("rev-parse", "--abbrev-ref", "HEAD")
    dirty = bool(git("status", "--porcelain", "--untracked-files=no"))
    behind = int(git("rev-list", "--count", f"HEAD..{upstream}") or 0)
    pending, absorbed = classify_branch(git, upstream, "HEAD")
    overlay = Overlay(local=len(pending), absorbed=len(absorbed))
    if pending and behind:
        code = git("merge-tree", "--write-tree", "--name-only", upstream, "HEAD", code=True)
        overlay.conflict = code == 1
    worktrees = set()
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("branch refs/heads/"):
            worktrees.add(line.removeprefix("branch refs/heads/"))
    for name in git("for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()[:MAX_BRANCHES]:
        if not name or name == current_branch:
            continue
        p, a = classify_branch(git, upstream, name)
        if p or a:
            overlay.branches[name] = {"pending": len(p), "absorbed": len(a), "worktree": name in worktrees}
    extra = [n for n, b in overlay.branches.items() if b["pending"]]
    done = [n for n, b in overlay.branches.items() if not b["pending"]]
    notes = []
    if extra:
        notes.append(f"另有 {len(extra)} 个分支含未收敛修改")
    if done:
        notes.append(f"{len(done)} 个分支已被上游收录")
    if dirty:
        notes.append("工作区有未提交改动")
    overlay.note = "；".join(notes)
    return {"head": head, "upstream": up, "branch": current_branch, "behind": behind,
            "dirty": dirty, "overlay": overlay}


def git_converge(git, remote, branch, state, log):
    """Move the checkout onto upstream while keeping every unabsorbed change.

    All touched refs are backed up under refs/upall/backup/<time>/ first.
    Absorbed-only branches without a worktree are archived and removed.
    """
    upstream = f"{remote}/{branch}"
    if state["dirty"]:
        raise RuntimeError("工作区有未提交改动；已保持原样")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    current = state["branch"]
    git("update-ref", f"refs/upall/backup/{stamp}/HEAD", state["head"])
    overlay = state["overlay"]
    if overlay.local == 0:
        if current != branch:
            # Our feature branch is fully upstream now: return to the main line.
            if git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", code=True) == 0:
                git("update-ref", f"refs/upall/backup/{stamp}/{branch}", git("rev-parse", branch))
                git("checkout", "--quiet", branch)
            else:
                git("checkout", "--quiet", "-b", branch, upstream)
            log(f"本地分支 {current} 的修改已全部被上游收录，切回 {branch}")
            if current != "HEAD":
                # The branch we left is fully upstream now; archive it like any other.
                overlay.branches[current] = {"pending": 0, "absorbed": overlay.absorbed, "worktree": False}
        if git("merge-base", "--is-ancestor", "HEAD", upstream, code=True) == 0:
            git("merge", "--quiet", "--ff-only", upstream)
        else:
            git("reset", "--quiet", "--keep", upstream)  # only absorbed commits differ
    elif state["behind"]:
        if overlay.conflict:
            raise RuntimeError(f"本地 {overlay.local} 项修改与上游冲突；已保持原样，需人工合并")
        try:
            git("rebase", "--quiet", upstream, timeout=300)
        except Exception:
            git("rebase", "--abort", code=True)
            raise RuntimeError("变基失败，已恢复原状；本地修改需人工合并") from None
        log(f"已在上游最新提交上保留本地 {overlay.local} 项修改")
    for name, info in overlay.branches.items():
        if info["pending"] == 0 and not info["worktree"] and name != branch:
            git("update-ref", f"refs/upall/archive/{name}", git("rev-parse", name))
            git("branch", "--quiet", "-D", name)
            log(f"分支 {name} 已被上游收录，归档到 refs/upall/archive/{name} 后删除")
    if git("show-ref", "--verify", "--quiet", f"refs/heads/{branch}", code=True) == 0 and \
            git("rev-parse", "--abbrev-ref", "HEAD") != branch and \
            git("merge-base", "--is-ancestor", branch, upstream, code=True) == 0:
        git("update-ref", f"refs/heads/{branch}", git("rev-parse", upstream))


def snapshot(paths, store):
    """Copy customised paths aside; returns records for restore()."""
    records = []
    shutil.rmtree(store, ignore_errors=True)
    store.mkdir(parents=True, mode=0o700)
    for index, path in enumerate(paths):
        path = Path(path)
        record = {"path": path, "link": None, "copy": None}
        if path.is_symlink():
            record["link"] = os.readlink(path)
        elif path.exists():
            copy = store / str(index)
            if path.is_dir():
                shutil.copytree(path, copy, symlinks=True)
            else:
                shutil.copy2(path, copy)
            record["copy"] = copy
        else:
            continue
        records.append(record)
    return records


def restore(records, log):
    restored = 0
    for record in records:
        path = record["path"]
        if record["link"] is not None:
            if path.is_symlink() and os.readlink(path) == record["link"]:
                continue
            _remove(path)
            path.symlink_to(record["link"])
            restored += 1
            log(f"恢复符号链接 {path}")
        elif record["copy"] is not None:
            if _same(record["copy"], path):
                continue
            _remove(path)
            if record["copy"].is_dir():
                shutil.copytree(record["copy"], path, symlinks=True)
            else:
                shutil.copy2(record["copy"], path)
            restored += 1
            log(f"保留本地修改 {path}")
    return restored


def _remove(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def _same(a, b):
    if not b.exists() or b.is_symlink() != a.is_symlink():
        return False
    if a.is_file():
        return b.is_file() and a.read_bytes() == b.read_bytes()
    left = sorted(p.relative_to(a).as_posix() for p in a.rglob("*"))
    right = sorted(p.relative_to(b).as_posix() for p in b.rglob("*"))
    if left != right:
        return False
    return all((a / n).is_dir() or (a / n).read_bytes() == (b / n).read_bytes() for n in left)
