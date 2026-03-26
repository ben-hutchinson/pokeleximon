from __future__ import annotations

import unittest
from datetime import date
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

if "psycopg" not in sys.modules:
    psycopg_module = ModuleType("psycopg")
    psycopg_rows_module = ModuleType("psycopg.rows")
    psycopg_rows_module.dict_row = object()
    psycopg_module.rows = psycopg_rows_module
    sys.modules["psycopg"] = psycopg_module
    sys.modules["psycopg.rows"] = psycopg_rows_module

if "psycopg_pool" not in sys.modules:
    psycopg_pool_module = ModuleType("psycopg_pool")
    psycopg_pool_module.ConnectionPool = object
    sys.modules["psycopg_pool"] = psycopg_pool_module

if "redis" not in sys.modules:
    redis_module = ModuleType("redis")
    redis_module.Redis = SimpleNamespace(from_url=lambda *args, **kwargs: None)
    sys.modules["redis"] = redis_module

from app.services import reserve_generator  # noqa: E402


class CrosswordQualityGateTests(unittest.TestCase):
    def test_governed_builder_rejects_non_publishable_after_retries(self):
        payload = {"id": "puz_test", "grid": "{}", "entries": "[]", "metadata": "{}"}
        report = {
            "isPublishable": False,
            "score": 42.0,
            "hardFailures": ["duplicate_clues_detected"],
            "warnings": ["fill_ratio_sparse"],
        }

        with (
            patch.object(reserve_generator, "_build_crossword_puzzle_payload", return_value=payload),
            patch.object(reserve_generator, "_attach_crossword_quality_report", return_value=report),
        ):
            with self.assertRaises(reserve_generator.QualityGateError) as ctx:
                reserve_generator._build_governed_crossword_puzzle_payload(
                    target_date=date(2026, 3, 3),
                    timezone="Europe/London",
                    lexicon=[],
                    seed_value=20260303,
                    max_attempts=2,
                )

        err = ctx.exception
        self.assertEqual(err.code, "crossword_quality_gate_rejected")
        detail = err.to_detail()
        self.assertEqual(detail["code"], "crossword_quality_gate_rejected")
        self.assertEqual(detail["attemptsUsed"], 2)
        self.assertEqual(detail["qualityReport"]["hardFailures"], ["duplicate_clues_detected"])

    def test_governed_builder_uses_disallowed_content_error_code(self):
        payload = {"id": "puz_test", "grid": "{}", "entries": "[]", "metadata": "{}"}
        report = {
            "isPublishable": False,
            "score": 11.0,
            "hardFailures": ["clue_contains_disallowed_content"],
            "warnings": [],
        }

        with (
            patch.object(reserve_generator, "_build_crossword_puzzle_payload", return_value=payload),
            patch.object(reserve_generator, "_attach_crossword_quality_report", return_value=report),
        ):
            with self.assertRaises(reserve_generator.QualityGateError) as ctx:
                reserve_generator._build_governed_crossword_puzzle_payload(
                    target_date=date(2026, 3, 3),
                    timezone="Europe/London",
                    lexicon=[],
                    seed_value=20260303,
                    max_attempts=1,
                )

        self.assertEqual(ctx.exception.code, "crossword_disallowed_clue_content_detected")

    def test_draft_governed_builder_uses_structural_gate(self):
        payload = {"id": "puz_test", "grid": "{}", "entries": "[]", "metadata": "{}"}
        report = {
            "isPublishable": False,
            "score": 38.0,
            "hardFailures": ["intersection_ratio_too_low"],
            "warnings": ["fill_ratio_sparse"],
        }

        with (
            patch.object(reserve_generator, "_build_crossword_puzzle_payload", return_value=payload),
            patch.object(reserve_generator, "_attach_crossword_structural_report", return_value=report),
        ):
            with self.assertRaises(reserve_generator.QualityGateError) as ctx:
                reserve_generator._build_governed_crossword_draft_payload(
                    target_date=date(2026, 3, 3),
                    timezone="Europe/London",
                    lexicon=[],
                    seed_value=20260303,
                    max_attempts=1,
                )

        self.assertEqual(ctx.exception.code, "crossword_structure_gate_rejected")


if __name__ == "__main__":
    unittest.main()
