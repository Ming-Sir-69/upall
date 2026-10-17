"""Task state snapshots."""
from dataclasses import dataclass
import time


@dataclass
class Job:
    role: str
    label: str
    current: str = "-"
    latest: str = "-"
    status: str = "QUEUED"
    detail: str = ""
    started: float = 0
    ended: float = 0
    attempt: int = 0
    path: str = ""
    source: str = "missing"
    installed: bool = False
    update_supported: bool = False

    def elapsed(self):
        return max(0, (self.ended or time.monotonic()) - self.started) if self.started else 0
