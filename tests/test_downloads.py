"""Download fallback, transport telemetry and native Claude trust boundaries."""
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from upall.discovery import Installation
from upall.engine import CommandError, Engine


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="upall-downloads-")
        root = Path(self.temporary.name)
        installations = {
            "codex": Installation("codex", "/fixture/codex", "npm", package="@openai/codex"),
            "claude": Installation("claude", "/fixture/claude", "native"),
        }
        args = SimpleNamespace(check=False, demo=False, inventory=False)
        self.engine = Engine(args, list(installations), root / "latest", installations)

    def tearDown(self):
        self.engine.pool.shutdown()
        self.temporary.cleanup()

    def test_multiconnection_fallback_records_each_attempt_and_history(self):
        archive = self.engine.log_dir / "package.zip"
        payload = b"package"
        calls = []

        def command(role, command, **kwargs):
            calls.append(command)
            if Path(command[0]).name == "aria2c":
                raise CommandError("single route failed")
            Path(command[command.index("-o") + 1]).write_bytes(payload)
            return ""

        self.engine.command = command
        with patch("upall.engine.shutil.which", side_effect=lambda name: "/fake/aria2c" if name == "aria2c" else None):
            self.engine.download_file("codex", "https://github.com/vendor/package.zip", archive,
                                      sha256=hashlib.sha256(payload).hexdigest(), size=len(payload))
        events = self.engine.jobs["codex"].network
        self.assertEqual([(event["tool"], event["status"]) for event in events],
                         [("aria2c", "failed"), ("curl", "success")])
        self.assertEqual(events[1]["bytes"], len(payload))
        self.assertIn("回退 curl", (self.engine.log_dir / "codex.log").read_text())
        self.engine.save()
        self.engine.save()
        history = self.engine.log_dir.parent / "history.jsonl"
        rows = [json.loads(line) for line in history.read_text().splitlines()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]["jobs"][0]["network"], rows[-2]["jobs"][0]["network"])
        self.assertEqual(stat.S_IMODE(history.stat().st_mode), 0o600)

    def test_npm_direct_failure_retries_with_inherited_proxy(self):
        calls = []

        def command(role, command, **kwargs):
            calls.append(kwargs["env"])
            if len(calls) == 1:
                raise CommandError("direct unavailable")
            return "1.2.3"

        self.engine.command = command
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.invalid"}):
            output = self.engine.npm_command("codex", ["npm", "view", "@openai/codex", "version"],
                                             "version-check", capture=True)
        self.assertEqual(output, "1.2.3")
        self.assertNotIn("HTTPS_PROXY", calls[0])
        self.assertEqual(calls[1]["HTTPS_PROXY"], "http://proxy.invalid")
        self.assertEqual([(event["route"], event["status"]) for event in self.engine.jobs["codex"].network],
                         [("direct", "failed"), ("inherited", "success")])

    def test_claude_zstd_package_is_verified_and_installed_at_exact_version(self):
        payload = b"verified native binary"
        compressed = b"verified compressed binary"
        manifest = {"platforms": {"darwin-arm64": {"binary": "claude", "size": len(payload),
                    "checksum": hashlib.sha256(payload).hexdigest()}}}
        zmanifest = {"platforms": {"darwin-arm64": {"binary": "claude.zst", "size": len(compressed),
                     "checksum": hashlib.sha256(compressed).hexdigest()}}}
        self.engine.jobs["claude"].latest = "1.2.3"
        self.engine.fetch_json = lambda role, url: zmanifest if url.endswith(".zst.json") else manifest
        downloads = []

        def download(role, url, archive, **kwargs):
            downloads.append((url, kwargs))
            archive.write_bytes(compressed)

        installs = []

        def command(role, command, **kwargs):
            if command[0] == "/fake/zstd":
                Path(command[command.index("-o") + 1]).write_bytes(payload)
            else:
                installs.append(command)
            return ""

        self.engine.download_file = download
        self.engine.command = command
        with patch("upall.engine.platform.machine", return_value="arm64"), \
                patch("upall.engine.shutil.which", return_value="/fake/zstd"):
            self.engine.install_claude_native("claude")
        self.assertEqual(downloads[0][1]["sha256"], hashlib.sha256(compressed).hexdigest())
        self.assertEqual(installs[0][-2:], ["install", "1.2.3"])

    def test_claude_checksum_mismatch_never_executes_download(self):
        payload = b"not the vendor binary"
        manifest = {"platforms": {"darwin-arm64": {"binary": "claude", "size": len(payload),
                    "checksum": hashlib.sha256(b"different").hexdigest()}}}
        self.engine.jobs["claude"].latest = "1.2.3"
        self.engine.fetch_json = lambda role, url: manifest
        self.engine.download_file = lambda role, url, archive, **kwargs: archive.write_bytes(payload)
        self.engine.command = lambda *args, **kwargs: self.fail("unverified binary was executed")
        with patch("upall.engine.platform.machine", return_value="arm64"), \
                patch("upall.engine.shutil.which", return_value=None):
            with self.assertRaises(CommandError):
                self.engine.install_claude_native("claude")


if __name__ == "__main__":
    unittest.main()
