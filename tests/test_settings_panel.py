"""TUI settings panel (key 4) and monitors.json persistence."""
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from upall.discovery import DEFAULT_MONITORS, Installation, MONITORS
from upall.engine import Engine
from upall import hosttools
from upall.terminal import Terminal


class SaveMonitorsTests(unittest.TestCase):
    def test_save_round_trip_owner_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitors.json"
            saved = hosttools.save_monitors({"runtime", "mcp"}, path)
            self.assertEqual(saved, frozenset({"runtime", "mcp"}))
            self.assertEqual(oct(path.stat().st_mode & 0o777), "0o600")
            self.assertEqual(hosttools.load_monitors(path), frozenset({"runtime", "mcp"}))

    def test_save_rejects_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitors.json"
            with self.assertRaises(hosttools.ConfigError):
                hosttools.save_monitors(set(), path)


class SettingsPanelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="upall-settings-")
        self.log_dir = Path(self.tmp.name)
        args = Namespace(check=True, demo=True, inventory=False, no_wait=False,
                         monitors=frozenset(DEFAULT_MONITORS))
        found = {role: Installation(role, path=role, source="demo", update_supported=True)
                 for role in ("claude", "codex")}
        self.engine = Engine(args, list(found), self.log_dir, found)
        for role in found:
            self.engine.update(role, status="CURRENT", current="1.0.0", latest="1.0.0")
        self.view = Terminal(self.engine)
        self.view.color = False

    def tearDown(self):
        self.engine.pool.shutdown(wait=False)
        self.tmp.cleanup()

    def test_footer_advertises_settings_key(self):
        text = "\n".join(self.view.frame(120, 40))
        self.assertIn("4 设置", text)
        self.assertIn("空格/1", text)

    def test_key_4_opens_and_closes_settings(self):
        self.assertTrue(self.view.key("4"))
        self.assertEqual(self.view.panel, "settings")
        text = "\n".join(self.view.frame(100, 30))
        self.assertIn("UPALL · 设置", text)
        self.assertIn("编程工具本体", text)
        self.assertIn("MCP", text)
        self.assertTrue(self.view.key("0"))
        self.assertIsNone(self.view.panel)
        self.assertIn("4 设置", "\n".join(self.view.frame(120, 40)))

    def test_escape_closes_settings_without_quitting(self):
        self.view.key("4")
        self.assertTrue(self.view.key("\x1b"))
        self.assertIsNone(self.view.panel)

    def test_space_toggles_and_persists(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitors.json"
            self.view.key("4")
            # plugin is last in MONITORS order: runtime, plugin, skill, mcp
            self.view.settings_index = list(MONITORS).index("plugin")
            with patch.dict("os.environ", {"UPALL_MONITORS_CONFIG": str(path)}, clear=False):
                # Force save path via explicit patch of monitors_path
                with patch("upall.hosttools.monitors_path", return_value=path):
                    self.view.toggle_draft_monitor()
            self.assertIn("plugin", self.view.draft_monitors)
            self.assertEqual(hosttools.load_monitors(path), self.view.engine.args.monitors)
            self.assertIn("已生效", self.view.hint)
            self.assertIsNone(self.view.panel)

    def test_fullwidth_4_opens_settings(self):
        self.assertTrue(self.view.key("４"))
        self.assertEqual(self.view.panel, "settings")


if __name__ == "__main__":
    unittest.main()
