# Local modifications versus upstream

The hard part of keeping many tools current is not downloading releases: it is
knowing which differences are ours. Upstream converges (it merges our pull
requests, sometimes squashed or reworded), while our own changes are scattered
over forks, side branches, patched entry points and customised skill copies.
Comparing whole versions to find out is slow and ambiguous.

UPALL keeps the answer cheap by recording **what we changed**, then asking one
question per change: *does upstream carry it now?*

| Answer | What the update does |
|---|---|
| Upstream carries it ("已收敛") | Drop ours and use upstream directly |
| Upstream does not ("保留") | Update, then keep or re-apply ours |
| Both changed the same place ("冲突") | Leave everything untouched and report it |

The TUI shows this in the 本地修改 column next to each tool, and the JSON report
has it as `overlay` on every job.

## Git checkouts (`"kind": "git"`)

For a fork or patched checkout UPALL fetches only the tracked upstream branch and
classifies every local commit that upstream lacks:

1. `git cherry` patch-id match: upstream took the commit verbatim.
2. Every file the commit touched is identical in upstream: upstream took it
   squashed, reworded or combined with other work.
3. Otherwise the commit is still ours.

`git merge-tree --write-tree` predicts conflicts without touching the work tree.
An update then:

- backs up the touched refs under `refs/upall/backup/<time>/`;
- with nothing of ours left, returns to the upstream branch (fast-forward, or
  `reset --keep` when only absorbed commits differ);
- otherwise rebases our remaining commits onto upstream, aborting on any conflict;
- archives side branches upstream fully absorbed to `refs/upall/archive/<name>`
  and deletes them (branches checked out in a worktree are only reported);
- refuses to touch a work tree with uncommitted changes.

## Adapter commands (`"kind": "command"`)

For projects with their own updater, an adapter prints one JSON object on
`check` and performs the update on `update`:

~~~json
{"current": "0.2.50-multi.19", "latest": "0.2.51（含本地修改）",
 "overlay": {"local": 10, "absorbed": 0, "conflict": false, "note": "上游 main 另有 2 个提交未发版"},
 "manual": "optional reason to require manual handling"}
~~~

After `update` succeeds UPALL runs `check` again; the update counts only when the
fresh `current` equals the fresh `latest`.

## Customised copies (`"preserve"`)

Some official updaters rewrite files we have customised, such as a slimmed agent
skill. Paths listed under `preserve.<tool id>` are snapshotted before that tool's
update and restored afterwards; a path that was a symlink stays a symlink.

## Example config

~~~json
{
  "tools": [
    {"id": "mole", "label": "Mole", "group": "app",
     "check": ["/usr/bin/python3", "-I", "/path/to/adapters/mole.py", "check"],
     "update": ["/usr/bin/python3", "-I", "/path/to/adapters/mole.py", "update"], "timeout": 1800},
    {"id": "some-fork", "label": "Some Fork", "group": "host", "kind": "git",
     "repo": "/path/to/checkout", "remote": "origin", "branch": "main"}
  ],
  "preserve": {"kimi-webbridge": ["~/.codex/skills/kimi-webbridge"]}
}
~~~

The file must belong to the current user and must not be group- or
world-writable; every program path must be absolute. Groups: cli, agent, app, host.
