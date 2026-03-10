from __future__ import annotations

import unittest
from pathlib import Path


ADMIN_FILE = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "admin.py"


class AdminRouteTests(unittest.TestCase):
    def test_analytics_summary_route_exists(self):
        source = ADMIN_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.get("/analytics/summary"', source)
        self.assertIn('@router.get("/analytics/cryptic/clue-feedback"', source)

    def test_publish_rollback_route_exists(self):
        source = ADMIN_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.post("/publish/rollback")', source)

    def test_publish_routes_accept_contest_mode(self):
        source = ADMIN_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.post("/publish")', source)
        self.assertIn('@router.post("/publish/daily")', source)
        self.assertIn("contestMode", source)


if __name__ == "__main__":
    unittest.main()
