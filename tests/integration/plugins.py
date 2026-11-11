#!/usr/bin/env python3
"""Plugins, app bundles, host tools and local-modification convergence; fixtures only."""
import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/upall"
sys.path.insert(0, str(ROOT / "src"))
from upall import hosttools, overlay


def sh(cwd, *args):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def git_runner(repo):
    def run(*args, code=False, timeout=60):
        result = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
        if code:
            return result.returncode
        assert result.returncode == 0, (args, result.stderr)
        return result.stdout.strip()
    return run


def commit(repo, name, text, message):
    (repo / name).write_text(text)
    sh(repo, "git", "add", name)
    sh(repo, "git", "commit", "-qm", message)


# --- host config validation -------------------------------------------------
with tempfile.TemporaryDirectory(prefix="upall-host-") as tmp:
    tmp = Path(tmp)
    config = tmp / "tools.json"
    config.write_text(json.dumps({"tools": [{"id": "x", "check": ["relative"], "update": ["/bin/true"]}]}))
    config.chmod(0o600)
    try:
        hosttools.load(config)
        raise AssertionError("relative argv accepted")
    except hosttools.ConfigError:
        pass
    config.write_text(json.dumps({"tools": [{"id": "x", "group": "app", "check": ["/bin/echo"], "update": ["/bin/true"]}],
                                  "preserve": {"x": ["~/keep"]}}))
    config.chmod(0o622)
    try:
        hosttools.load(config)
        raise AssertionError("group-writable config accepted")
    except hosttools.ConfigError:
        pass
    config.chmod(0o600)
    tools, preserve = hosttools.load(config)
    assert tools["x"].group == "app" and tools["x"].installed and preserve["x"] == [Path.home() / "keep"]
print("PASS: host config needs owner-only file, absolute argv, known groups")

# --- git convergence ----------------------------------------------------------
with tempfile.TemporaryDirectory(prefix="upall-git-") as tmp:
    tmp = Path(tmp)
    env_setup = ["-c", "user.name=t", "-c", "user.email=t@t"]
    os.environ.update(GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    upstream = tmp / "upstream"
    upstream.mkdir()
    sh(upstream, "git", "init", "-q", "-b", "main")
    commit(upstream, "base.txt", "base\n", "base")
    local = tmp / "local"
    sh(tmp, "git", "clone", "-q", str(upstream), str(local))
    # Ours: one taken verbatim upstream, one squash-merged with a new message, one still ours.
    commit(local, "a.txt", "ours a\n", "feat: a")
    commit(local, "b.txt", "ours b\n", "feat: b")
    commit(local, "c.txt", "ours c\n", "feat: c")
    sh(local, "git", "branch", "old-fix", "HEAD~2")      # absorbed-only side branch
    sh(local, "git", "branch", "side-wip", "HEAD")       # has a pending commit
    commit(upstream, "a.txt", "ours a\n", "feat: a (#1)")
    (upstream / "b.txt").write_text("ours b\n")
    (upstream / "other.txt").write_text("upstream work\n")
    sh(upstream, "git", "add", ".")
    sh(upstream, "git", "commit", "-qm", "Squashed PR #2 (b) plus upstream work")
    git = git_runner(local)
    state = overlay.git_state(git, "origin", "main")
    ov = state["overlay"]
    assert (ov.local, ov.absorbed, ov.conflict) == (1, 2, False), ov
    assert state["behind"] == 2
    assert ov.branches["old-fix"] == {"pending": 0, "absorbed": 1, "worktree": False}
    logs = []
    overlay.git_converge(git, "origin", "main", state, logs.append)
    assert git("merge-base", "--is-ancestor", "origin/main", "HEAD", code=True) == 0
    assert (local / "c.txt").read_text() == "ours c\n" and (local / "other.txt").exists()
    assert git("rev-list", "--count", "origin/main..HEAD") == "1", "only the unabsorbed change is kept"
    assert git("show-ref", "--verify", "--quiet", "refs/heads/old-fix", code=True) != 0
    assert git("show-ref", "--verify", "--quiet", "refs/upall/archive/old-fix", code=True) == 0
    assert git("show-ref", "--verify", "--quiet", "refs/heads/side-wip", code=True) == 0
    assert git("for-each-ref", "refs/upall/backup")
    # Conflict: our edit and upstream's touch the same line; nothing may change.
    commit(local, "base.txt", "ours\n", "ours on base")
    commit(upstream, "base.txt", "theirs\n", "theirs on base")
    state = overlay.git_state(git, "origin", "main")
    assert state["overlay"].conflict
    before = git("rev-parse", "HEAD")
    try:
        overlay.git_converge(git, "origin", "main", state, logs.append)
        raise AssertionError("conflict converged")
    except RuntimeError as error:
        assert "冲突" in str(error)
    assert git("rev-parse", "HEAD") == before and not git("status", "--porcelain")
    # A feature branch upstream fully took: return to main at upstream.
    feature = tmp / "feature"
    sh(tmp, "git", "clone", "-q", str(upstream), str(feature))
    sh(feature, "git", "checkout", "-qb", "feat/x")
    commit(feature, "x.txt", "x\n", "feat: x")
    commit(upstream, "x.txt", "x\n", "feat: x (#3)")
    git = git_runner(feature)
    state = overlay.git_state(git, "origin", "main")
    assert (state["overlay"].local, state["overlay"].absorbed) == (0, 1)
    overlay.git_converge(git, "origin", "main", state, logs.append)
    assert git("rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert git("rev-parse", "HEAD") == git("rev-parse", "origin/main")
print("PASS: git overlay finds verbatim/squashed absorption, keeps pending work, archives absorbed branches, refuses conflicts")

# --- preserved customisations ----------------------------------------------------
with tempfile.TemporaryDirectory(prefix="upall-preserve-") as tmp:
    tmp = Path(tmp)
    custom = tmp / "codex/skill"
    custom.mkdir(parents=True)
    (custom / "SKILL.md").write_text("our slim skill\n")
    link = tmp / "claude/skill"
    link.parent.mkdir()
    link.symlink_to(custom)
    records = overlay.snapshot([custom, link], tmp / "store")
    link.unlink()
    shutil.copytree(tmp / "store/0", link)          # updater replaced the link with a copy
    (custom / "SKILL.md").write_text("upstream skill\n")
    (custom / "extra.md").write_text("upstream extra\n")
    restored = overlay.restore(records, lambda text: None)
    assert restored == 2 and link.is_symlink() and (custom / "SKILL.md").read_text() == "our slim skill\n"
    assert not (custom / "extra.md").exists()
print("PASS: customised copies and symlinks survive an upstream refresh")

# --- app bundle replacement and host command tool, end to end ---------------------
STUB = r'''
import json, os, shutil, sys
from pathlib import Path
root = Path(os.environ["UPALL_FIXTURE_ROOT"])
tool, args = Path(sys.argv[0]).name, sys.argv[1:]
with (root / "calls").open("a") as log:
    log.write(tool + " " + " ".join(args) + "\n")
if tool == "curl" and args[-1].endswith("/latest/version.json"):
    print(json.dumps({"version": "0.7.2", "app": {"url": "https://cdn.kimi.com/kimi-computer-use/0.7.2/KimiCU.app.zip",
          "sha256": (root / "sha").read_text().strip(), "team_id": "TEAM000001"},
          "app_x86_64": {"url": "https://cdn.kimi.com/kimi-computer-use/0.7.2/KimiCU-x86_64.app.zip",
          "sha256": (root / "sha").read_text().strip(), "team_id": "TEAM000001"}}))
elif tool == "curl" and "-o" in args:
    shutil.copyfile(root / "package.zip", args[args.index("-o") + 1])
elif tool == "codesign" and args[0] == "-d":
    team = "TEAM999999" if os.environ.get("UPALL_FIXTURE_CASE") == "badteam" and "package" in args[-1] else "TEAM000001"
    print("Identifier=ai.kimi.cu\nTeamIdentifier=" + team, file=sys.stderr)
elif tool == "codesign":
    pass
elif tool == "launchctl":
    sys.exit(3 if args[0] == "print" else 0)
elif tool == "adapter" and args == ["check"]:
    state = root / "adapter.version"
    current = state.read_text().strip() if state.exists() else "1.0.0"
    print(json.dumps({"current": current, "latest": "1.1.0",
                      "overlay": {"local": 2, "absorbed": 1, "note": "fixture"}}))
elif tool == "adapter" and args == ["update"]:
    (root / "adapter.version").write_text("1.1.0")
else:
    sys.exit("unexpected fixture command: " + tool + " " + " ".join(args))
'''


def bundle(path, version):
    (path / "Contents/MacOS").mkdir(parents=True)
    with (path / "Contents/Info.plist").open("wb") as file:
        plistlib.dump({"CFBundleIdentifier": "ai.kimi.cu", "CFBundleShortVersionString": version}, file)
    (path / "Contents/MacOS/kimi-cu").write_text(version)


for case, expected in (("ok", "UPDATED"), ("badteam", "UPDATE-FAILED")):
    with tempfile.TemporaryDirectory(prefix="upall-apps-") as tmp:
        tmp = Path(tmp)
        bin_dir = tmp / "bin"
        bin_dir.mkdir()
        stub = bin_dir / "fixture"
        stub.write_text(f"#!{sys.executable}\n" + STUB)
        stub.chmod(0o755)
        for name in ("curl", "codesign", "launchctl", "adapter"):
            (bin_dir / name).symlink_to(stub)
        apps = tmp / "Apps"
        bundle(apps / "KimiCU.app", "0.6.8")
        build = tmp / "build"
        bundle(build / "KimiCU.app", "0.7.2")
        with zipfile.ZipFile(tmp / "package.zip", "w") as archive:
            for file in (build).rglob("*"):
                archive.write(file, file.relative_to(build).as_posix())
        import hashlib
        (tmp / "sha").write_text(hashlib.sha256((tmp / "package.zip").read_bytes()).hexdigest())
        config = tmp / "tools.json"
        config.write_text(json.dumps({"tools": [{"id": "fork", "label": "Fork", "group": "host",
                                                 "check": [str(bin_dir / "adapter"), "check"],
                                                 "update": [str(bin_dir / "adapter"), "update"]}]}))
        config.chmod(0o600)
        env = dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin", UPALL_SEARCH_PATH=str(bin_dir / "none"),
                   UPALL_APP_DIRS=str(apps), UPALL_CONFIG=str(config), UPALL_LOG_ROOT=str(tmp / "state"),
                   UPALL_FIXTURE_ROOT=str(tmp), UPALL_FIXTURE_CASE=case, UPALL_TEST_MODE="0")
        result = subprocess.run([sys.executable, str(SCRIPT), "--json"], env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=30)
        jobs = {j["role"]: j for j in json.loads(result.stdout)["jobs"]}
        assert jobs["kimi-cu"]["status"] == "AVAILABLE" and jobs["kimi-cu"]["group"] == "agent", jobs
        assert jobs["fork"]["status"] == "AVAILABLE" and jobs["fork"]["overlay"] == "保留 2 · 已收敛 1", jobs
        assert "-o" not in (tmp / "calls").read_text(), "check downloaded a package"
        result = subprocess.run([sys.executable, str(SCRIPT), "--json", "--update"], env=env,
                                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
        jobs = {j["role"]: j for j in json.loads(result.stdout)["jobs"]}
        logs = "\n".join(p.read_text() for p in (tmp / "state/latest").glob("*.log"))
        assert jobs["kimi-cu"]["status"] == expected, (jobs, logs)
        assert jobs["fork"]["status"] == "UPDATED", (jobs, logs)
        installed = plistlib.loads((apps / "KimiCU.app/Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]
        assert installed == ("0.7.2" if case == "ok" else "0.6.8"), installed
        if case == "ok":
            assert (tmp / "state/backups/KimiCU.app/Contents/MacOS/kimi-cu").read_text() == "0.6.8"
        else:
            assert "签名团队" in logs
print("PASS: app bundles update only with matching sha256 and signing team, keep a rollback copy; host tools report overlays")
