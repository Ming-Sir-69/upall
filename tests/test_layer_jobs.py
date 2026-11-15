"""MCP/Skill layer jobs and expanded discovery (incl. kimi-code mcp.json)."""
import json
from argparse import Namespace
from pathlib import Path
import tempfile
import unittest

from upall.discovery import Installation
from upall.engine import Engine
from upall.layerjobs import build_mcp_installations, is_layer_role, layer_role
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
            tools = build_mcp_installations(home)
            role = layer_role("mcp", "kimi-code", "playwright")
            self.assertIn(role, tools)
            self.assertEqual(tools[role].monitor, "mcp")
            self.assertTrue(is_layer_role(role))


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
