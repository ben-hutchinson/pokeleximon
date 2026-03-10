from __future__ import annotations

import unittest
from pathlib import Path


SCHEDULER_FILE = Path(__file__).resolve().parents[1] / "app" / "core" / "scheduler.py"


class SchedulerStartupTests(unittest.TestCase):
    def test_start_scheduler_has_startup_publish_guard(self):
        source = SCHEDULER_FILE.read_text(encoding="utf-8")
        guard_marker = "if config.PUBLISH_ON_STARTUP:"
        publish_marker = "_publish_daily()"
        self.assertIn(guard_marker, source)
        self.assertIn(publish_marker, source)
        guard_index = source.index(guard_marker)
        publish_after_guard_index = source.index(publish_marker, guard_index)
        self.assertLess(guard_index, publish_after_guard_index)


if __name__ == "__main__":
    unittest.main()
