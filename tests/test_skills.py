"""Fixture-based tests for vendor Skill multi-host sync (WebBridge)."""
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from upall.layers import skills
from upall.layers.skills import (
    SkillRoot,
    apply_sync_plan,
    check_webbridge_skills,
    discover_skills,
    fingerprint_skill,
    plan_webbridge_sync,
)


SKILL_BODY_A = """---
name: kimi-webbridge
description: fixture A
---

# WebBridge A
"""

SKILL_BODY_B = """---
name: kimi-webbridge
description: fixture B
---

# WebBridge B
"""

OTHER_SKILL = """---
name: phone-to-mac
description: self maintained
---

# Phone
"""


def _write_skill(path: Path, body: str, extra: str | None = None):
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(body, encoding="utf-8")
    if extra is not None:
        (path / "extra.txt").write_text(extra, encoding="utf-8")
    return path


class SkillFixtureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="upall-skills-")
        self.home = Path(self.temporary.name) / "home"
        self.home.mkdir()
        self.claude = self.home / ".claude" / "skills"
        self.codex = self.home / ".codex" / "skills"
        self.kimi = self.home / ".kimi-code" / "skills"
        self.agents = self.home / ".agents" / "skills"
        for root in (self.claude, self.codex, self.kimi, self.agents):
            root.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def test_discover_webbridge_copies_and_fingerprints(self):
        _write_skill(self.claude / "kimi-webbridge", SKILL_BODY_A, "refs")
        _write_skill(self.codex / "kimi-webbridge", SKILL_BODY_A, "refs")
        _write_skill(self.kimi / "kimi-webbridge", SKILL_BODY_A, "refs")
        _write_skill(self.claude / "phone-to-mac", OTHER_SKILL)

        installs = check_webbridge_skills(home=self.home)
        self.assertEqual(len(installs), 3)
        self.assertTrue(all(item.sync_state == "in_sync" for item in installs))
        self.assertEqual(len({item.fingerprint for item in installs}), 1)
        self.assertTrue(all(item.fingerprint_kind == "tree" for item in installs))
        # Non-webbridge skills are excluded by default.
        self.assertFalse(any(item.name == "phone-to-mac" for item in installs))

    def test_drift_and_alone_and_symlink_skip(self):
        _write_skill(self.claude / "kimi-webbridge", SKILL_BODY_A, "a")
        _write_skill(self.codex / "kimi-webbridge", SKILL_BODY_B, "b")
        project = Path(self.temporary.name) / "project" / "my-skill"
        _write_skill(project, OTHER_SKILL)
        link = self.agents / "my-skill"
        link.symlink_to(project, target_is_directory=True)

        webbridge = check_webbridge_skills(home=self.home)
        self.assertEqual(sorted(item.sync_state for item in webbridge), ["drift", "drift"])

        all_skills = skills.annotate_sync_state(discover_skills(home=self.home, names=None))
        linked = [item for item in all_skills if item.path == link]
        self.assertEqual(len(linked), 1)
        self.assertEqual(linked[0].sync_state, "skip")
        self.assertTrue(linked[0].is_symlink)
        self.assertTrue(linked[0].project_link)

        alone_root = self.home / ".hermes" / "skills"
        alone_root.mkdir(parents=True)
        _write_skill(alone_root / "kimi-webbridge", SKILL_BODY_A)
        # Only one host when scanning a single root → alone
        only = check_webbridge_skills(roots=[SkillRoot("hermes", alone_root)])
        self.assertEqual([item.sync_state for item in only], ["alone"])

    def test_plan_never_overwrites_symlinks_and_reports_replace(self):
        source = _write_skill(self.kimi / "kimi-webbridge", SKILL_BODY_B, "fresh")
        stale = _write_skill(self.claude / "kimi-webbridge", SKILL_BODY_A, "stale")
        project = Path(self.temporary.name) / "proj" / "kimi-webbridge"
        _write_skill(project, SKILL_BODY_A)
        link = self.codex / "kimi-webbridge"
        link.symlink_to(project, target_is_directory=True)

        installs = check_webbridge_skills(home=self.home)
        plan = plan_webbridge_sync(installs, source=source)
        self.assertTrue(plan.needs_sync)
        self.assertEqual(plan.source, source)
        kinds = {(action.kind, action.host): action for action in plan.actions}
        self.assertEqual(kinds[("replace_tree", "claude")].destination, stale)
        self.assertEqual(kinds[("skip", "codex")].reason, "symlink to project / self-maintained")
        self.assertNotIn(("replace_tree", "codex"), kinds)

        # Default apply refuses; confirm=True updates only the copied tree.
        with self.assertRaises(RuntimeError):
            apply_sync_plan(plan)
        updated = apply_sync_plan(plan, confirm=True)
        self.assertEqual(updated, [stale])
        self.assertEqual(fingerprint_skill(stale)[0], fingerprint_skill(source)[0])
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), project.resolve())

    def test_webbridge_alias_dirname_and_exports(self):
        _write_skill(self.claude / "webbridge", SKILL_BODY_A)
        installs = check_webbridge_skills(home=self.home)
        self.assertEqual(len(installs), 1)
        self.assertTrue(skills.is_webbridge_name(installs[0].path.name))

        import upall.layers as layers
        self.assertTrue(hasattr(layers, "plan_webbridge_sync"))
        self.assertTrue(hasattr(layers, "check_webbridge_skills"))
        # layers package must not pull engine/cli (inspect source, not global sys.modules)
        init_src = (Path(__file__).resolve().parents[1] / "src/upall/layers/__init__.py").read_text(encoding="utf-8")
        skills_src = (Path(__file__).resolve().parents[1] / "src/upall/layers/skills.py").read_text(encoding="utf-8")
        for blob in (init_src, skills_src):
            self.assertNotIn("upall.engine", blob)
            self.assertNotIn("upall.cli", blob)
            self.assertNotIn("upall.discovery", blob)

    def test_plan_skips_when_already_in_sync(self):
        _write_skill(self.claude / "kimi-webbridge", SKILL_BODY_A, "same")
        _write_skill(self.codex / "kimi-webbridge", SKILL_BODY_A, "same")
        plan = plan_webbridge_sync(home=self.home)
        self.assertFalse(plan.needs_sync)
        self.assertTrue(all(action.kind == "skip" for action in plan.actions))


if __name__ == "__main__":
    unittest.main()
