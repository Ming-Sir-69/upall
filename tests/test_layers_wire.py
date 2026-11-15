"""Lead wiring: monitors on args, layer report, WebBridge sync after update."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from upall.discovery import Installation
from upall.engine import Engine


class LayerWireTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="upall-layers-wire-")
        self.log_dir = Path(self.tmp.name) / "latest"
        self.log_dir.mkdir()
        self.args = Namespace(check=True, demo=False, inventory=False, json=True,
                              monitors=frozenset({"runtime", "skill", "mcp"}))

    def tearDown(self):
        self.tmp.cleanup()

    def _engine(self, role="claude"):
        found = Installation(role, path="/bin/true", source="demo", update_supported=True)
        return Engine(self.args, [role], self.log_dir, {role: found})

    def test_report_includes_monitors_and_layers(self):
        engine = self._engine()
        with patch.object(engine, "layer_report", return_value={"mcp": [{"id": "x", "status": "ok"}]}):
            report = engine.report()
        self.assertEqual(set(report["monitors"]), {"runtime", "skill", "mcp"})
        self.assertEqual(report["layers"]["mcp"][0]["status"], "ok")

    def test_layer_report_skips_in_demo(self):
        self.args.demo = True
        engine = self._engine()
        self.assertEqual(engine.layer_report(), {})

    def test_webbridge_sync_after_install_when_skill_monitor_on(self):
        role = "kimi-webbridge"
        found = Installation(role, path="/bin/true", source="script", update_supported=True)
        engine = Engine(self.args, [role], self.log_dir, {role: found})
        with patch.object(engine, "install_one"), \
             patch.object(engine, "sync_webbridge_skills") as sync:
            engine.install(role)
        sync.assert_called_once_with(role)

    def test_sync_webbridge_skills_passes_preferred_source(self):
        role = "kimi-webbridge"
        found = Installation(role, path="/bin/true", source="script", update_supported=True)
        engine = Engine(self.args, [role], self.log_dir, {role: found})
        preferred = Path(self.tmp.name) / "fresh-skill"
        preferred.mkdir()
        (preferred / "SKILL.md").write_text("---\nname: kimi-webbridge\n---\n")
        with patch.object(engine, "webbridge_skill_source", return_value=preferred), \
             patch("upall.layers.plan_webbridge_sync") as plan_fn, \
             patch("upall.layers.apply_sync_plan", return_value=[]):
            plan_fn.return_value.needs_sync = False
            engine.sync_webbridge_skills(role)
        plan_fn.assert_called_once()
        self.assertEqual(plan_fn.call_args.kwargs.get("source"), preferred)

    def test_webbridge_sync_skipped_when_skill_monitor_off(self):
        self.args.monitors = frozenset({"runtime", "mcp"})
        role = "kimi-webbridge"
        found = Installation(role, path="/bin/true", source="script", update_supported=True)
        engine = Engine(self.args, [role], self.log_dir, {role: found})
        with patch.object(engine, "install_one"), \
             patch.object(engine, "sync_webbridge_skills") as sync:
            engine.install(role)
        sync.assert_not_called()


if __name__ == "__main__":
    unittest.main()
