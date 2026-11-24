"""Only a usable desktop bundle qualifies for the default inventory."""
import json
import os
from pathlib import Path
import plistlib
import tempfile
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from upall.discovery import DESKTOP_APPS, PACKAGES, discover


class CatalogTests(unittest.TestCase):
    def test_installed_and_leftover_bundle(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for role, (name, identifier) in DESKTOP_APPS.items():
                contents = root / (name + ".app") / "Contents"
                (contents / "MacOS").mkdir(parents=True)
                (contents / "Info.plist").write_bytes(plistlib.dumps({
                    "CFBundleIdentifier": identifier, "CFBundleExecutable": name,
                    "CFBundleShortVersionString": "1.2.3"}))
                binary = contents / "MacOS" / name
                with patch.dict(os.environ, UPALL_APP_DIRS=temp):
                    self.assertFalse(discover(temp)[role].installed)
                    binary.touch(mode=0o700)
                    found = discover(temp)[role]
                    self.assertEqual(found.version, "1.2.3")
                    self.assertFalse(found.update_supported)
                    self.assertEqual(found.group, "app")

    def test_matching_global_npm_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp)
            commands = prefix / "bin"
            commands.mkdir()
            (commands / "npm").touch(mode=0o700)
            for role in ("copilot", "dsh", "omp"):
                package, = PACKAGES[role]
                install = prefix / "lib/node_modules" / package
                install.mkdir(parents=True)
                (install / "package.json").write_text(json.dumps({"name": package}))
                (install / role).touch(mode=0o700)
                (commands / role).symlink_to(install / role)
                found = discover(str(commands))[role]
                self.assertTrue(found.update_supported)
                self.assertEqual(found.package, package)
