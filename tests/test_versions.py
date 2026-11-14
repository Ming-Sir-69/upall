"""Release-source regressions: stale native markers must not hide updates."""
import copy
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from upall.discovery import Installation
from upall.engine import CommandError, Engine


class VersionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="upall-versions-")
        install = Installation("kimi", "/fixture/.kimi-code/bin/kimi", "script", update_supported=True)
        self.engine = Engine(SimpleNamespace(check=True, demo=False, inventory=False), ["kimi"],
                             Path(self.temporary.name) / "latest", {"kimi": install})
        self.manifest = {"version": "2.6.2", "platforms": {"darwin-arm64": {
            "filename": "kimi-code-darwin-arm64", "checksum": "a" * 64}}}
        self.engine.current_version = lambda role: "2.6.1"
        self.engine.command = lambda *a, **kw: self.fail("unexpected executable invocation")
        self.system = patch("upall.engine.platform.system", return_value="Darwin")
        self.arch = patch("upall.engine.platform.machine", return_value="arm64")
        self.system.start()
        self.arch.start()

    def tearDown(self):
        self.arch.stop()
        self.system.stop()
        self.engine.pool.shutdown()
        self.temporary.cleanup()

    def test_published_release_is_found_without_stale_native_marker_or_npm(self):
        urls = []

        def fetch(role, url):
            urls.append(url)
            if url == "https://registry.npmjs.org/@moonshot-ai/kimi-code/latest":
                return {"version": "2.6.2"}
            if url == "https://code.kimi.com/kimi-code/binaries/2.6.2/manifest.json":
                return self.manifest
            self.fail(f"unexpected release source: {url}")

        self.engine.fetch_json = fetch
        self.engine.worker("kimi", False)
        job = self.engine.jobs["kimi"]
        self.assertEqual((job.current, job.latest, job.status), ("2.6.1", "2.6.2", "AVAILABLE"))
        self.assertEqual(len(urls), 2)

    def test_bad_release_metadata_never_becomes_current_or_available(self):
        for data in ([], {}, {"version": "2.6.2/../../install"}, {"version": "2.6.2\x1b[0m"},
                     {"version": 262}):
            with self.subTest(data=data):
                self.engine.fetch_json = lambda role, url: data
                self.engine.worker("kimi", False)
                self.assertEqual(self.engine.jobs["kimi"].status, "CONNECTION-FAILED")

    def test_native_package_must_exist_for_the_exact_release_and_platform(self):
        invalid = [[], {}, {"version": "2.6.2", "platforms": {}},
                   {"version": "2.6.2", "platforms": []}]
        for field, value in (("version", "2.6.1"), ("filename", "../../other"), ("checksum", "invalid")):
            data = copy.deepcopy(self.manifest)
            if field == "version":
                data[field] = value
            else:
                data["platforms"]["darwin-arm64"][field] = value
            invalid.append(data)
        for manifest in invalid:
            with self.subTest(manifest=manifest):
                self.engine.fetch_json = lambda role, url: manifest if url.endswith("manifest.json") else {"version": "2.6.2"}
                with self.assertRaises(CommandError):
                    self.engine.latest_version("kimi")

    def test_unreachable_registry_does_not_fall_back_to_false_current(self):
        self.engine.fetch_json = lambda *a: (_ for _ in ()).throw(CommandError("network unavailable"))
        self.engine.worker("kimi", False)
        self.assertEqual(self.engine.jobs["kimi"].status, "CONNECTION-FAILED")

    def test_local_ahead_keeps_remote_value_and_never_downgrades(self):
        self.engine.latest_version = lambda role: "2.5.3"
        self.engine.install = lambda role: self.fail("downgrade attempted")
        for install in (False, True):
            with self.subTest(install=install):
                self.engine.worker("kimi", install)
                job = self.engine.jobs["kimi"]
                self.assertEqual((job.current, job.latest, job.status), ("2.6.1", "2.5.3", "AHEAD"))

    def test_installer_pins_checked_version_and_detected_root(self):
        self.engine.jobs["kimi"].latest = "2.6.2"
        calls = []
        self.engine.command = lambda role, argv, **kw: calls.append((argv, kw)) or ""
        self.engine.install("kimi")
        argv, kw = calls[-1]
        self.assertEqual(argv[-2:], ["--version", "2.6.2"])
        self.assertEqual(kw["env"]["KIMI_VERSION"], "2.6.2")
        self.assertEqual(kw["env"]["KIMI_INSTALL_DIR"], "/fixture/.kimi-code")
        self.assertEqual(kw["env"]["KIMI_NO_MODIFY_PATH"], "1")
        calls.clear()
        self.engine.jobs["kimi"].latest = "../../bad"
        with self.assertRaises(CommandError):
            self.engine.install("kimi")
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
