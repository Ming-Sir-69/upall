"""Monitor kinds: defaults, config loading, and CLI filtering."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from upall.cli import parse_monitor_args
from upall.discovery import DEFAULT_MONITORS, GROUPS, Installation, MONITORS, ROLE_GROUPS
from upall import hosttools


class MonitorConstantsTests(unittest.TestCase):
    def test_monitors_sit_beside_groups_without_replacing_them(self):
        self.assertEqual(set(GROUPS), {"cli", "agent", "app", "host"})
        self.assertEqual(set(MONITORS), {"runtime", "plugin", "skill", "mcp"})
        self.assertEqual(DEFAULT_MONITORS, frozenset({"runtime", "skill", "mcp"}))
        self.assertNotIn("plugin", DEFAULT_MONITORS)

    def test_builtin_installations_default_to_runtime(self):
        item = Installation("claude")
        self.assertEqual(item.monitor, "runtime")
        self.assertEqual(item.group, "cli")
        agent = Installation("kimi-webbridge")
        self.assertEqual(agent.group, ROLE_GROUPS["kimi-webbridge"])
        self.assertEqual(agent.monitor, "runtime")

    def test_explicit_monitor_on_spec_tool_is_kept(self):
        item = Installation("layer-mcp", path="/tmp/x", source="host", monitor="mcp",
                            group="agent", spec={"kind": "command"})
        self.assertEqual(item.monitor, "mcp")


class MonitorConfigTests(unittest.TestCase):
    def test_missing_config_returns_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {key: value for key, value in os.environ.items()
                   if key not in {"UPALL_SEARCH_PATH", "UPALL_MONITORS_CONFIG", "UPALL_CONFIG"}}
            env["XDG_CONFIG_HOME"] = temporary
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(hosttools.load_monitors(), DEFAULT_MONITORS)

    def test_monitors_json_enabled_list(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitors.json"
            path.write_text(json.dumps({"enabled": ["runtime", "plugin"]}))
            path.chmod(0o600)
            self.assertEqual(hosttools.load_monitors(path), frozenset({"runtime", "plugin"}))

    def test_tools_json_monitors_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            tools = Path(temporary) / "tools.json"
            tools.write_text(json.dumps({"monitors": ["mcp"], "tools": []}))
            tools.chmod(0o600)
            # Isolated search path skips default user files; pass tools path explicitly.
            with patch.dict(os.environ, {"UPALL_SEARCH_PATH": str(temporary)}):
                self.assertEqual(hosttools.load_monitors(tools_config=tools), frozenset({"mcp"}))

    def test_dedicated_file_wins_over_tools_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            tools = base / "tools.json"
            tools.write_text(json.dumps({"monitors": ["plugin"], "tools": []}))
            tools.chmod(0o600)
            monitors = base / "monitors.json"
            monitors.write_text(json.dumps({"enabled": ["skill"]}))
            monitors.chmod(0o600)
            env = {key: value for key, value in os.environ.items() if key != "UPALL_SEARCH_PATH"}
            env.update({"UPALL_MONITORS_CONFIG": str(monitors), "UPALL_CONFIG": str(tools)})
            with patch.dict(os.environ, env, clear=True):
                self.assertEqual(hosttools.load_monitors(), frozenset({"skill"}))

    def test_group_writable_monitors_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "monitors.json"
            path.write_text(json.dumps({"enabled": ["runtime"]}))
            path.chmod(0o622)
            with self.assertRaises(hosttools.ConfigError):
                hosttools.load_monitors(path)

    def test_host_tool_monitor_field(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "tools.json"
            config.write_text(json.dumps({
                "tools": [{"id": "demo-skill", "group": "agent", "monitor": "skill",
                           "check": ["/bin/echo"], "update": ["/bin/true"]}],
            }))
            config.chmod(0o600)
            tools, _, _ = hosttools.load(config)
            self.assertEqual(tools["demo-skill"].monitor, "skill")
            self.assertEqual(tools["demo-skill"].group, "agent")

    def test_unknown_tool_monitor_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "tools.json"
            config.write_text(json.dumps({
                "tools": [{"id": "x", "monitor": "nope",
                           "check": ["/bin/echo"], "update": ["/bin/true"]}],
            }))
            config.chmod(0o600)
            with self.assertRaises(hosttools.ConfigError):
                hosttools.load(config)

    def test_absolute_path_rules_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            config = Path(temporary) / "tools.json"
            config.write_text(json.dumps({
                "tools": [{"id": "x", "check": ["relative"], "update": ["/bin/true"]}],
            }))
            config.chmod(0o600)
            with self.assertRaises(hosttools.ConfigError):
                hosttools.load(config)


class MonitorCliTests(unittest.TestCase):
    def test_parse_monitor_args(self):
        self.assertEqual(parse_monitor_args(["runtime,skill", "mcp"]),
                         frozenset({"runtime", "skill", "mcp"}))
        with self.assertRaises(ValueError):
            parse_monitor_args(["nope"])
        self.assertIsNone(parse_monitor_args(None))
        self.assertIsNone(parse_monitor_args([]))

    def test_cli_monitor_filters_roles_and_keeps_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            adapter = temporary / "adapter.sh"
            adapter.write_text("#!/bin/sh\nprintf '%s\\n' '{\"current\":\"1\",\"latest\":\"1\"}'\n")
            adapter.chmod(0o755)
            config = temporary / "tools.json"
            config.write_text(json.dumps({
                "tools": [
                    {"id": "rt-tool", "group": "cli", "monitor": "runtime",
                     "check": [str(adapter)], "update": ["/bin/true"]},
                    {"id": "pl-tool", "group": "cli", "monitor": "plugin",
                     "check": [str(adapter)], "update": ["/bin/true"]},
                    {"id": "sk-tool", "group": "agent", "monitor": "skill",
                     "check": [str(adapter)], "update": ["/bin/true"]},
                ],
            }))
            config.chmod(0o600)
            empty = temporary / "empty-bin"
            empty.mkdir()
            env = dict(
                os.environ,
                PYTHONPATH=str(ROOT / "src"),
                UPALL_SEARCH_PATH=str(empty),
                UPALL_CONFIG=str(config),
                UPALL_LOG_ROOT=str(temporary / "state"),
                UPALL_TEST_MODE="0",
            )
            script = ROOT / "tools/upall"

            def run(*extra):
                result = subprocess.run(
                    [sys.executable, str(script), "--list", "--json", *extra],
                    env=env, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                return {job["role"] for job in json.loads(result.stdout)["jobs"]}

            # --list includes missing built-ins; assert only on this fixture's host tools.
            host_ids = {"rt-tool", "pl-tool", "sk-tool"}
            # Defaults: runtime+skill+mcp → plugin host tool hidden.
            default_roles = run() & host_ids
            self.assertEqual(default_roles, {"rt-tool", "sk-tool"})

            only_plugin = run("--monitor", "plugin") & host_ids
            self.assertEqual(only_plugin, {"pl-tool"})

            group_and_monitor = run("-g", "cli", "--monitor", "runtime,plugin") & host_ids
            self.assertEqual(group_and_monitor, {"rt-tool", "pl-tool"})

    def test_retry_reapplies_monitor_filter(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            adapter = temporary / "adapter.sh"
            adapter.write_text("#!/bin/sh\nprintf '%s\\n' '{\"current\":\"1\",\"latest\":\"2\"}'\n")
            adapter.chmod(0o755)
            config = temporary / "tools.json"
            config.write_text(json.dumps({
                "tools": [
                    {"id": "rt-tool", "group": "cli", "monitor": "runtime",
                     "check": [str(adapter)], "update": ["/bin/true"]},
                    {"id": "pl-tool", "group": "cli", "monitor": "plugin",
                     "check": [str(adapter)], "update": ["/bin/true"]},
                ],
            }))
            config.chmod(0o600)
            empty = temporary / "empty-bin"
            empty.mkdir()
            state = temporary / "state" / "latest"
            state.mkdir(parents=True)
            (state / "report.json").write_text(json.dumps({
                "jobs": [
                    {"role": "rt-tool", "status": "QUERY-FAILED"},
                    {"role": "pl-tool", "status": "QUERY-FAILED"},
                ],
            }))
            env = dict(
                os.environ,
                PYTHONPATH=str(ROOT / "src"),
                UPALL_SEARCH_PATH=str(empty),
                UPALL_CONFIG=str(config),
                UPALL_LOG_ROOT=str(temporary / "state"),
                UPALL_TEST_MODE="0",
            )
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/upall"), "--retry", "--monitor", "runtime",
                 "--plain", "--json", "--no-wait"],
                env=env, capture_output=True, text=True, timeout=20)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            roles = {job["role"] for job in json.loads(result.stdout)["jobs"]}
            self.assertEqual(roles, {"rt-tool"})


if __name__ == "__main__":
    unittest.main()
