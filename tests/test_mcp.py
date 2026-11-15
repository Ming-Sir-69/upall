"""Read-only MCP npx check regressions (fixtures only; no real installs)."""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from upall.layers.mcp import (
    check_mcp_entry,
    check_npx_package,
    compare_versions,
    discover_mcp_entries,
    fetch_npm_latest,
    iter_mcp_checks,
    npx_cache_dir,
    parse_npx_package,
    read_npx_cached_version,
)


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _seed_npx_cache(home: Path, spec: str, package_name: str, version: str) -> Path:
    root = npx_cache_dir(spec, home)
    _write(root / "package.json", {"dependencies": {package_name: f"^{version}"}})
    pkg_json = root / "node_modules" / Path(*package_name.split("/")) / "package.json"
    _write(pkg_json, {"name": package_name, "version": version})
    return root


class ParseNpxTests(unittest.TestCase):
    def test_extracts_scoped_latest_and_skips_flags(self):
        parsed = parse_npx_package("npx", ["-y", "@modelcontextprotocol/server-filesystem@latest", "/tmp"])
        self.assertEqual(parsed, {
            "name": "@modelcontextprotocol/server-filesystem",
            "tag": "latest",
            "spec": "@modelcontextprotocol/server-filesystem@latest",
        })

    def test_package_flag_and_non_npx(self):
        self.assertIsNone(parse_npx_package("/usr/bin/node", ["server.js"]))
        parsed = parse_npx_package("npx", ["--package", "eslint", "-c", "eslint ."])
        self.assertEqual(parsed["name"], "eslint")


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="upall-mcp-")
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_discovers_cursor_and_claude_entries_without_secrets(self):
        _write(self.home / ".cursor" / "mcp.json", {
            "mcpServers": {
                "fs": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-filesystem@latest", "/tmp"],
                    "env": {"API_KEY": "should-not-appear"},
                },
                "remote": {"type": "http", "url": "https://example.test/mcp", "headers": {"Authorization": "secret"}},
                "off": {"command": "npx", "args": ["pkg@latest"], "disabled": True},
                "bin": {"command": "/opt/local/mcp-server", "args": []},
            }
        })
        _write(
            self.home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json",
            {"mcpServers": {"playwright": {"command": "npx", "args": ["-y", "@playwright/mcp@latest"]}}},
        )
        entries = discover_mcp_entries(self.home)
        by_id = {e["id"]: e for e in entries}
        self.assertIn("fs", by_id)
        self.assertEqual(by_id["fs"]["host"], "cursor")
        self.assertNotIn("env", by_id["fs"]["config"])
        self.assertNotIn("headers", by_id["remote"]["config"])
        self.assertEqual(by_id["playwright"]["host"], "claude-desktop")
        # Disabled / missing absolute binaries are not installed → omitted
        self.assertNotIn("off", by_id)
        self.assertNotIn("bin", by_id)

    def test_dedupes_identical_fingerprint_across_hosts(self):
        payload = {
            "mcpServers": {
                "playwright": {"command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
            }
        }
        _write(self.home / ".cursor" / "mcp.json", payload)
        _write(self.home / ".kimi-code" / "mcp.json", payload)
        entries = discover_mcp_entries(self.home)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "playwright")
        self.assertEqual(sorted(entries[0]["hosts"]), ["cursor", "kimi-code"])


class CacheAndCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="upall-mcp-cache-")
        self.home = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_npx_cache_dir_matches_npm_sha512_prefix(self):
        spec = "@playwright/mcp@latest"
        digest = hashlib.sha512(spec.encode()).hexdigest()[:16]
        self.assertEqual(npx_cache_dir(spec, self.home).name, digest)

    def test_read_cached_version_from_spec_hash(self):
        pkg = "@playwright/mcp"
        _seed_npx_cache(self.home, f"{pkg}@latest", pkg, "0.0.85")
        self.assertEqual(read_npx_cached_version(pkg, home=self.home, specs=[f"{pkg}@latest"]), "0.0.85")

    def test_check_npx_package_ok_outdated_unknown(self):
        pkg = "@modelcontextprotocol/server-filesystem"
        _seed_npx_cache(self.home, f"{pkg}@latest", pkg, "1.0.0")

        ok = check_npx_package(pkg, home=self.home, registry=lambda n, t: "1.0.0", specs=[f"{pkg}@latest"])
        self.assertEqual(ok["status"], "ok")
        self.assertEqual((ok["current"], ok["latest"]), ("1.0.0", "1.0.0"))

        old = check_npx_package(pkg, home=self.home, registry=lambda n, t: "2.0.0", specs=[f"{pkg}@latest"])
        self.assertEqual(old["status"], "outdated")

        miss = check_npx_package("missing-pkg", home=self.home, registry=lambda n, t: None)
        self.assertEqual(miss["status"], "unknown")

    def test_iter_mcp_checks_classifies_skip_and_npx(self):
        pkg = "@modelcontextprotocol/server-filesystem"
        _seed_npx_cache(self.home, f"{pkg}@latest", pkg, "1.2.3")
        existing = self.home / "bin" / "native-mcp"
        existing.parent.mkdir(parents=True)
        existing.write_text("#!/bin/sh\n", encoding="utf-8")
        existing.chmod(0o755)
        _write(self.home / ".cursor" / "mcp.json", {
            "mcpServers": {
                "fs": {"command": "npx", "args": ["-y", f"{pkg}@latest", "/data"]},
                "remote": {"type": "sse", "url": "https://example.test/sse"},
                "off": {"command": "npx", "args": ["other@latest"], "disabled": True},
                "native": {"command": str(existing), "args": []},
                "missing": {"command": "/no/such/mcp-binary", "args": []},
            }
        })
        results = {r["id"]: r for r in iter_mcp_checks(
            self.home, registry=lambda n, t: "1.2.4" if n == pkg else None)}
        self.assertEqual(results["fs"]["status"], "outdated")
        self.assertEqual(results["fs"]["package"], pkg)
        self.assertEqual(results["remote"]["status"], "skip")
        self.assertIn("remote", results["remote"]["reason"])
        self.assertEqual(results["native"]["status"], "skip")
        self.assertNotIn("off", results)
        self.assertNotIn("missing", results)

    def test_compare_versions(self):
        self.assertEqual(compare_versions("1.0.0", "1.0.1"), "outdated")
        self.assertEqual(compare_versions("2.0.0", "2.0.0"), "ok")
        self.assertEqual(compare_versions("bad", "1.0.0"), "unknown")

    def test_check_mcp_entry_passthrough(self):
        entry = {
            "id": "fs",
            "host": "cursor",
            "config": {"command": "npx", "args": ["-y", "eslint@latest"]},
        }
        _seed_npx_cache(self.home, "eslint@latest", "eslint", "9.0.0")
        result = check_mcp_entry(entry, home=self.home, registry=lambda n, t: "9.0.0")
        self.assertEqual(result["status"], "ok")


class LiveRegistryTests(unittest.TestCase):
    """Optional live read-only registry call; skips cleanly when offline."""

    def test_fetch_npm_latest_live_readonly(self):
        # LIVE_NETWORK: read-only HTTPS GET to registry.npmjs.org; no install.
        version = fetch_npm_latest("@modelcontextprotocol/server-filesystem", timeout=8.0)
        if version is None:
            self.skipTest("npm registry unreachable (offline or blocked)")
        self.assertRegex(version, r"^\d+\.\d+\.\d+")


class ExportTests(unittest.TestCase):
    def test_layers_package_exports_helpers(self):
        import upall.layers as layers
        self.assertTrue(callable(getattr(layers, "iter_mcp_checks", None)))
        self.assertTrue(callable(getattr(layers, "check_npx_package", None)))


if __name__ == "__main__":
    unittest.main()
