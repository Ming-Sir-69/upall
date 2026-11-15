"""MCP/Skill layer jobs and expanded discovery (incl. kimi-code mcp.json)."""
import json
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest

from upall.discovery import Installation
from upall.engine import Engine
from upall.layerjobs import (
    build_mcp_installations,
    build_skill_installations,
    is_layer_role,
    layer_role,
)
from upall.layers.mcp import discover_mcp_entries
from upall.terminal import Terminal


class McpDiscoveryTests(unittest.TestCase):
    def test_discovers_kimi_code_npx_playwright(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            path = home / ".kimi-code" / "mcp.json"
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({
                "mcpServers": {
                    "playwright": {
                        "command": "npx",
                        "args": ["-y", "@playwright/mcp@latest"],
                        "transport": "stdio",
                    },
                    "bundled": {
                        "command": "/Apps/Thing.app/mcp",
                        "args": ["mcp"],
                    },
                },
            }))
            entries = {f"{e['host']}:{e['id']}": e for e in discover_mcp_entries(home)}
            self.assertIn("kimi-code:playwright", entries)
            self.assertEqual(entries["kimi-code:playwright"]["config"]["command"], "npx")
            self.assertNotIn("kimi-code:bundled", entries)  # missing binary → not installed
            tools = build_mcp_installations(home)
            role = layer_role("mcp", "kimi-code", "playwright")
            self.assertIn(role, tools)
            self.assertEqual(tools[role].monitor, "mcp")
            self.assertTrue(is_layer_role(role))

    def test_mcp_and_skill_dedupe_hosts_in_one_row(self):
        with tempfile.TemporaryDirectory() as temporary:
            home = Path(temporary)
            payload = {"mcpServers": {
                "playwright": {"command": "npx", "args": ["-y", "@playwright/mcp@latest"]},
            }}
            for host in (".cursor", ".kimi-code"):
                path = home / host / "mcp.json"
                path.parent.mkdir(parents=True)
                path.write_text(json.dumps(payload))
            body = "---\nname: demo-skill\n---\n# demo\n"
            for host in (".claude", ".codex"):
                skill = home / host / "skills" / "demo-skill"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text(body, encoding="utf-8")
            # Empty skill root (no SKILL.md children) must not appear
            (home / ".hermes" / "skills").mkdir(parents=True)

            mcp_tools = build_mcp_installations(home)
            self.assertEqual(len(mcp_tools), 1)
            mcp = next(iter(mcp_tools.values()))
            self.assertIn("cursor", mcp.label)
            self.assertIn("kimi-code", mcp.label)

            skill_tools = build_skill_installations(home)
            self.assertEqual(len(skill_tools), 1)
            skill = next(iter(skill_tools.values()))
            self.assertEqual(skill.spec["name"], "demo-skill")
            self.assertEqual(sorted(skill.spec["hosts"]), ["claude", "codex"])
            self.assertNotIn("hermes", skill.spec["hosts"])


class LiveRefreshTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="upall-live-")
        self.log_dir = Path(self.tmp.name)
        args = Namespace(check=True, demo=True, inventory=False, no_wait=False, all=False,
                         monitors=frozenset({"runtime", "skill", "mcp"}))
        found = {"claude": Installation("claude", path="claude", source="demo", update_supported=True)}
        self.engine = Engine(args, ["claude"], self.log_dir, found)
        self.engine.update("claude", status="CURRENT", current="1", latest="1")
        self.view = Terminal(self.engine)
        self.view.color = False

    def tearDown(self):
        self.engine.stop.set()
        self.engine.pool.shutdown(wait=True)
        self.tmp.cleanup()

    def test_key_2_refreshes_when_no_failures(self):
        text = "\n".join(self.view.frame(120, 40))
        self.assertIn("2 重试/刷新", text)
        self.assertTrue(self.view.key("2"))
        self.assertFalse(self.engine.done())  # refresh started
        self.engine.stop.set()
        while not self.engine.done():
            pass


if __name__ == "__main__":
    unittest.main()
