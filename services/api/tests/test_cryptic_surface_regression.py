from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import cryptic_runtime


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "cryptic_surface_golden.json"


class CrypticSurfaceRegressionTests(unittest.TestCase):
    def test_mechanism_variant_counts_include_multiple_surface_patterns(self):
        entry = {
            "answer_key": "FIRESTONE",
            "answer_tokens": ["FIRE", "STONE"],
            "enumeration": "4,5",
            "source_type": "item",
        }
        ranked = cryptic_runtime.build_ranked_candidates(entry)
        counts: dict[str, int] = {}
        for row in ranked:
            counts[str(row.get("mechanism", ""))] = counts.get(str(row.get("mechanism", "")), 0) + 1

        self.assertGreaterEqual(counts.get("charade", 0), 3)
        self.assertGreaterEqual(counts.get("anagram", 0), 3)
        self.assertGreaterEqual(counts.get("deletion", 0), 3)

    def test_hidden_mechanism_has_multiple_surface_patterns_when_enabled(self):
        entry = {
            "answer_key": "SMOGON",
            "answer_tokens": ["SMOGON"],
            "enumeration": "6",
            "source_type": "move",
        }
        with patch.object(cryptic_runtime, "ALLOW_HIDDEN_MECHANISM", True):
            ranked = cryptic_runtime.build_ranked_candidates(entry)

        hidden_rows = [row for row in ranked if row.get("mechanism") == "hidden"]
        self.assertGreaterEqual(len(hidden_rows), 3)

    def test_surface_duplicate_rate_below_ten_percent(self):
        entry = {
            "answer_key": "FIRESTONE",
            "answer_tokens": ["FIRE", "STONE"],
            "enumeration": "4,5",
            "source_type": "item",
        }
        ranked = cryptic_runtime.build_ranked_candidates(entry)
        publishable = [row for row in ranked if cryptic_runtime.is_ranked_candidate_publishable(row)]
        self.assertGreaterEqual(len(publishable), 10)
        clues = [str(row["clue"]).strip().upper() for row in publishable]
        duplicate_rate = 1 - (len(set(clues)) / len(clues))
        self.assertLess(duplicate_rate, 0.10)

    def test_formulaic_surface_is_detected_by_validator(self):
        entry = {
            "answer_key": "SMOG",
            "answer_tokens": ["SMOG"],
            "enumeration": "4",
            "source_type": "move",
        }
        candidate = {
            "mechanism": "anagram",
            "clue": "Mixed letters in GOMS produce battle technique (4)",
            "metadata": {"indicator": "mixed", "fodder": "GOMS"},
        }
        passed, issues = cryptic_runtime._validate_candidate(entry, candidate)
        self.assertTrue(any(issue.get("code") == "clue_surface_formulaic" for issue in issues))
        self.assertTrue(passed)

    def test_golden_selected_clues_are_stable(self):
        fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
        for _, payload in fixture.items():
            entry = payload["entry"]
            expected = payload["selected"]
            ranked = cryptic_runtime.build_ranked_candidates(entry)
            selected = cryptic_runtime.select_ranked_candidate(ranked)
            self.assertIsNotNone(selected)
            assert selected is not None
            self.assertEqual(selected["mechanism"], expected["mechanism"])
            self.assertEqual(selected["clue"], expected["clue"])


if __name__ == "__main__":
    unittest.main()
