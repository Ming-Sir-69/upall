"""Regression checks for publication security boundaries."""
import importlib.util
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from upall.util import atomic, clean, private_directory, state_root


class StateSecurityTests(unittest.TestCase):
    def test_xdg_path_rules_and_host_override(self):
        home = Path.home()
        with patch.dict(os.environ, {"XDG_STATE_HOME":"relative-state"}, clear=True):
            self.assertEqual(state_root(), home / ".local/state/upall")
        with tempfile.TemporaryDirectory() as temporary:
            with patch.dict(os.environ, {"XDG_STATE_HOME":temporary}, clear=True):
                self.assertEqual(state_root(), Path(temporary) / "upall")
            with patch.dict(os.environ, {"XDG_STATE_HOME":"ignored", "UPALL_LOG_ROOT":temporary}, clear=True):
                self.assertEqual(state_root(), Path(temporary))

    def test_private_permissions_and_atomic_replacement(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = private_directory(Path(temporary) / "state")
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            report = root / "report.json"
            atomic(report, '{"ok":true}')
            self.assertEqual(json.loads(report.read_text()), {"ok": True})
            self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
            self.assertEqual([p.name for p in root.iterdir()], ["report.json"])

    def test_symlink_state_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "target"
            target.mkdir()
            link = root / "link"
            link.symlink_to(target, target_is_directory=True)
            with self.assertRaises(OSError):
                private_directory(link)

    def test_report_replaces_link_without_writing_its_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside"
            target.write_text("preserve")
            report = root / "report.json"
            report.symlink_to(target)
            atomic(report, "safe")
            self.assertEqual(target.read_text(), "preserve")
            self.assertFalse(report.is_symlink())

    def test_terminal_controls_and_bidi_are_removed(self):
        self.assertEqual(clean("\x1b[31mred\x1b[0m\x1b]52;c;data\x07\x9b\u202e\r\t中文"), "red中文")

    def test_symlink_lock_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "outside"
            target.write_text("preserve")
            (root / ".lock").symlink_to(target)
            environment = dict(os.environ, UPALL_LOG_ROOT=temporary, UPALL_TEST_MODE="1")
            process = subprocess.run([sys.executable, str(ROOT / "tools/upall"), "--json"],
                                     env=environment, capture_output=True, text=True, timeout=5)
            self.assertEqual(process.returncode, 2)
            self.assertEqual(target.read_text(), "preserve")


if __name__ == "__main__":
    unittest.main()
