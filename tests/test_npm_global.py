"""npm global install backend: shared prep and per-role flag customization."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from upall.discovery import Installation
from upall.engine import CommandError, Engine
from upall.installers import npm_global
from upall.models import Job


class NpmGlobalHelpersTests(unittest.TestCase):
    def test_slug_and_staging_for_scoped_and_plain(self):
        self.assertEqual(npm_global.package_slug("agent-desktop"), "agent-desktop")
        self.assertEqual(npm_global.package_slug("@openai/codex"), "openai-codex")
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            modules = npm_global.node_modules(prefix)
            modules.mkdir(parents=True)
            live = modules / "agent-desktop"
            live.mkdir()
            (live / "package.json").write_text(json.dumps({
                "name": "agent-desktop",
                "bin": {"agent-desktop": "bin/agent-desktop"},
            }))
            staging = modules / ".agent-desktop-ECznR15G"
            staging.mkdir()
            (staging / "package.json").write_text(json.dumps({
                "name": "agent-desktop",
                "bin": {"agent-desktop": "bin/agent-desktop"},
            }))
            (modules / ".unrelated-XXXX").mkdir()
            found = npm_global.staging_dirs(prefix, "agent-desktop")
            self.assertEqual([path.name for path in found], [".agent-desktop-ECznR15G"])

    def test_prepare_clears_staging_and_broken_bin_link(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            modules = npm_global.node_modules(prefix)
            modules.mkdir(parents=True)
            package = modules / "agent-desktop"
            package.mkdir()
            (package / "bin").mkdir()
            (package / "package.json").write_text(json.dumps({
                "name": "agent-desktop",
                "bin": {"agent-desktop": "bin/agent-desktop"},
            }))
            staging = modules / ".agent-desktop-ECznR15G"
            staging.mkdir()
            binary = staging / "bin" / "agent-desktop-darwin-arm64"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\n")
            binary.chmod(0o755)
            bindir = prefix / "bin"
            bindir.mkdir()
            link = bindir / "agent-desktop"
            link.symlink_to(binary)

            notes = npm_global.prepare(prefix, "agent-desktop")
            self.assertFalse(staging.exists())
            self.assertFalse(link.exists())
            self.assertTrue(package.exists())
            self.assertTrue(any("残留目录" in note for note in notes))
            self.assertTrue(any("失效命令链接" in note for note in notes))

    def test_prepare_scoped_package_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            prefix = Path(temporary)
            modules = npm_global.node_modules(prefix)
            package = modules / "@openai" / "codex"
            package.mkdir(parents=True)
            (package / "package.json").write_text(json.dumps({"name": "@openai/codex", "bin": {"codex": "codex"}}))
            staging = modules / ".openai-codex-AbCdEf12"
            staging.mkdir()
            notes = npm_global.prepare(prefix, "@openai/codex")
            self.assertFalse(staging.exists())
            self.assertTrue(any(".openai-codex-AbCdEf12" in note for note in notes))

    def test_prepare_refuses_paths_outside_prefix(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prefix = root / "prefix"
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "keep"
            marker.write_text("safe")
            modules = npm_global.node_modules(prefix)
            modules.mkdir(parents=True)
            # Symlink staging name under node_modules pointing outside must not be followed for delete.
            link = modules / ".agent-desktop-OUTSIDE"
            link.symlink_to(outside, target_is_directory=True)
            npm_global.prepare(prefix, "agent-desktop")
            self.assertTrue(marker.exists())
            self.assertTrue(link.exists())

    def test_build_install_command_customizes_only_listed_roles(self):
        plain = npm_global.build_install_command("npm", "/p", "@openai/codex", "1.2.3", role="codex")
        self.assertEqual(plain, ["npm", "install", "--global", "--prefix", "/p", "@openai/codex@1.2.3"])
        special = npm_global.build_install_command(
            "npm", "/p", "agent-desktop", "1.3.1", role="agent-desktop")
        self.assertEqual(special[-3:], [
            "--ignore-scripts=false",
            "--include=optional",
            "--allow-scripts=agent-desktop",
        ])


class NpmInstallEngineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="upall-npm-")
        self.prefix = Path(self.temporary.name)
        (self.prefix / "bin").mkdir(parents=True)
        self.engines = []

    def tearDown(self):
        for engine in self.engines:
            engine.pool.shutdown(wait=False)
        self.temporary.cleanup()

    def _engine(self, package="agent-desktop", role="agent-desktop"):
        args = SimpleNamespace(check=False, inventory=False, demo=False, update=True,
                               monitors=frozenset({"runtime"}))
        installations = {
            role: Installation(role, str(self.prefix / "bin" / role), "npm",
                               package=package, prefix=str(self.prefix),
                               manager=str(self.prefix / "bin/npm"), update_supported=True),
        }
        engine = Engine(args, [role], self.prefix / "logs", installations=installations)
        engine.jobs[role] = Job(role, label=role, current="1.0.0", latest="1.3.1",
                                installed=True, update_supported=True)
        self.engines.append(engine)
        return engine

    def test_install_npm_prepares_then_invokes_shared_command(self):
        modules = npm_global.node_modules(self.prefix)
        staging = modules / ".agent-desktop-ECznR15G"
        staging.mkdir(parents=True)
        engine = self._engine()
        calls = []

        def fake_npm(role, command, operation, **kwargs):
            calls.append((role, command, operation))
            return ""

        with patch.object(engine, "npm_command", side_effect=fake_npm):
            engine.install_npm("agent-desktop")
        self.assertFalse(staging.exists())
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1][:5],
                         [str(self.prefix / "bin/npm"), "install", "--global", "--prefix", str(self.prefix)])
        self.assertIn("agent-desktop@1.3.1", calls[0][1])

    def test_install_npm_retries_once_after_layout_error(self):
        engine = self._engine()
        attempts = []

        def fake_npm(role, command, operation, **kwargs):
            attempts.append(1)
            if len(attempts) == 1:
                raise CommandError("npm error code ENOTEMPTY\nnpm error directory not empty")
            return ""

        with patch.object(engine, "npm_command", side_effect=fake_npm):
            engine.install_npm("agent-desktop")
        self.assertEqual(len(attempts), 2)


if __name__ == "__main__":
    unittest.main()
