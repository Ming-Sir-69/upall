"""An earlier unknown agy must never redirect updates to a later signed copy."""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from upall.discovery import discover


class AntigravityDiscoveryTests(unittest.TestCase):
    def test_shadow_and_alias(self):
        with tempfile.TemporaryDirectory() as root:
            first, second = [Path(root) / name for name in ("first", "second")]
            for directory in (first, second):
                directory.mkdir()
                binary = directory / "agy"
                binary.touch(mode=0o700)
            search = os.pathsep.join(map(str, (first, second)))
            with patch("upall.discovery.sys.platform", "darwin"), patch("upall.discovery.subprocess.run") as sign:
                sign.return_value.returncode = 1
                found = discover(search)["antigravity-cli"]
                self.assertEqual(found.path, str(first / "agy"))
                self.assertFalse(found.update_supported)
                (first / "agy").unlink()
                (first / "agy").symlink_to(second / "agy")
                sign.return_value.returncode = 0
                found = discover(search)["antigravity-cli"]
                self.assertEqual(found.path, str((second / "agy").resolve()))
                self.assertEqual(sign.call_args.args[0][-1], found.path)
                self.assertTrue(found.update_supported)
