from __future__ import annotations

import unittest
from pathlib import Path


SCHEDULER_FILE = Path(__file__).resolve().parents[1] / "app" / "core" / "scheduler.py"


class SchedulerRefreshTests(unittest.TestCase):
    def test_scheduler_declares_draft_generation_job_and_cron_builder(self):
        source = SCHEDULER_FILE.read_text(encoding="utf-8")
        self.assertIn("_build_draft_generation_trigger", source)
        self.assertIn("_generate_daily_drafts", source)
        self.assertIn('id="draft_generation"', source)
        self.assertIn("DRAFT_GENERATION_CRON", source)

    def test_scheduler_declares_refresh_job_and_cron_builder(self):
        source = SCHEDULER_FILE.read_text(encoding="utf-8")
        self.assertIn("_build_refresh_trigger", source)
        self.assertIn('id="pokeapi_refresh"', source)
        self.assertIn("POKEAPI_REFRESH_CRON", source)

    def test_scheduler_has_refresh_startup_guard(self):
        source = SCHEDULER_FILE.read_text(encoding="utf-8")
        guard_marker = "if config.POKEAPI_REFRESH_ENABLED and config.POKEAPI_REFRESH_ON_STARTUP:"
        run_marker = "_refresh_pokeapi_artifacts()"
        self.assertIn(guard_marker, source)
        self.assertIn(run_marker, source)
        guard_index = source.index(guard_marker)
        run_index = source.index(run_marker, guard_index)
        self.assertLess(guard_index, run_index)


if __name__ == "__main__":
    unittest.main()
