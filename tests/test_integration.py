"""Portable integration scenarios use fake software and PTYs, never real updates."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class IntegrationTests(unittest.TestCase):
    def scenario(self, name):
        environment = dict(os.environ, PYTHONPATH=str(ROOT / "src"), TERM="xterm-256color")
        process = subprocess.run([sys.executable, str(ROOT / "tests/integration" / (name + ".py"))],
                                 cwd=ROOT, env=environment, capture_output=True, text=True, timeout=90)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)

    def test_discovery(self):
        self.scenario("discovery")

    def test_workers(self):
        self.scenario("workers")

    def test_terminal(self):
        self.scenario("interface")


if __name__ == "__main__":
    unittest.main()
