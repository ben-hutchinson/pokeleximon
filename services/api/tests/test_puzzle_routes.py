from __future__ import annotations

import unittest
from pathlib import Path


PUZZLES_FILE = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "puzzles.py"


class PuzzleRouteOrderTests(unittest.TestCase):
    def test_archive_route_is_declared_before_dynamic_puzzle_id(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        archive_marker = '@router.get("/archive"'
        dynamic_marker = '@router.get("/{puzzle_id}"'
        self.assertIn(archive_marker, source)
        self.assertIn(dynamic_marker, source)
        self.assertLess(source.index(archive_marker), source.index(dynamic_marker))

    def test_crossword_telemetry_route_exists(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        telemetry_marker = '@router.post("/crossword/telemetry"'
        self.assertIn(telemetry_marker, source)

    def test_connections_telemetry_route_exists(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        telemetry_marker = '@router.post("/connections/telemetry"'
        self.assertIn(telemetry_marker, source)

    def test_cryptic_clue_feedback_route_exists(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        marker = '@router.post("/cryptic/clue-feedback"'
        self.assertIn(marker, source)

    def test_client_error_route_exists(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        marker = '@router.post("/client-errors"'
        self.assertIn(marker, source)

    def test_personal_stats_route_exists(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        marker = '@router.get("/stats/personal"'
        self.assertIn(marker, source)

    def test_progress_routes_exist(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.get("/progress"', source)
        self.assertIn('@router.put("/progress"', source)

    def test_export_routes_exist(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.get("/export/text")', source)
        self.assertIn('@router.get("/export/pdf")', source)

    def test_challenge_and_leaderboard_routes_exist(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        self.assertIn('@router.get("/profile"', source)
        self.assertIn('@router.put("/profile"', source)
        self.assertIn('@router.post("/challenges"', source)
        self.assertIn('@router.post("/challenges/{challenge_code}/join"', source)
        self.assertIn('@router.get("/challenges/{challenge_code}"', source)
        self.assertIn('@router.post("/leaderboard/submit"', source)
        self.assertIn('@router.get("/leaderboard"', source)

    def test_progress_route_is_declared_before_dynamic_puzzle_id(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        progress_marker = '@router.get("/progress"'
        dynamic_marker = '@router.get("/{puzzle_id}"'
        self.assertIn(progress_marker, source)
        self.assertIn(dynamic_marker, source)
        self.assertLess(source.index(progress_marker), source.index(dynamic_marker))

    def test_export_route_is_declared_before_dynamic_puzzle_id(self):
        source = PUZZLES_FILE.read_text(encoding="utf-8")
        export_marker = '@router.get("/export/text")'
        dynamic_marker = '@router.get("/{puzzle_id}"'
        self.assertIn(export_marker, source)
        self.assertIn(dynamic_marker, source)
        self.assertLess(source.index(export_marker), source.index(dynamic_marker))


if __name__ == "__main__":
    unittest.main()
