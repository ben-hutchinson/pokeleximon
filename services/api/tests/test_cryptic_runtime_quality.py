from __future__ import annotations

import unittest
from pathlib import Path

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

from app.services.cryptic_runtime import (  # noqa: E402
    _validate_candidate,
    build_ranked_candidates,
    is_ranked_candidate_publishable,
    select_ranked_candidate,
)


class CrypticRuntimeQualityTests(unittest.TestCase):
    def test_short_single_word_has_no_candidates_when_hidden_disabled(self):
        entry = {
            "answer_key": "SMOG",
            "answer_tokens": ["SMOG"],
            "enumeration": "4",
            "source_type": "move",
        }
        ranked = build_ranked_candidates(entry)
        self.assertEqual(ranked, [])

    def test_validator_flags_standalone_answer_token(self):
        entry = {
            "answer_key": "SMOG",
            "answer_tokens": ["SMOG"],
            "enumeration": "4",
            "source_type": "move",
        }
        candidate = {
            "mechanism": "hidden",
            "clue": "Concealed in rapid SMOG line appears battle technique (4)",
            "metadata": {"indicator": "concealed in", "surface": "rapid SMOG line"},
        }
        passed, issues = _validate_candidate(entry, candidate)
        self.assertFalse(passed)
        self.assertTrue(any(issue.get("code") == "answer_leak_standalone" for issue in issues))

    def test_boilerplate_clue_is_not_publishable(self):
        ranked = [
            {
                "clue": "Mixed letters in MLSREGAE produce pokemon species (8)",
                "mechanism": "anagram",
                "validator_passed": True,
                "validator_issues": [],
                "rank_score": 88.0,
                "rank_position": 1,
            }
        ]
        self.assertFalse(is_ranked_candidate_publishable(ranked[0]))
        self.assertIsNone(select_ranked_candidate(ranked))

    def test_placeholder_token_clue_is_not_publishable(self):
        ranked = [
            {
                "clue": "Clue token ***** (8)",
                "mechanism": "anagram",
                "validator_passed": True,
                "validator_issues": [],
                "rank_score": 88.0,
                "rank_position": 1,
            }
        ]
        self.assertFalse(is_ranked_candidate_publishable(ranked[0]))
        self.assertIsNone(select_ranked_candidate(ranked))

    def test_validator_flags_disallowed_surface(self):
        entry = {
            "answer_key": "SMOG",
            "answer_tokens": ["SMOG"],
            "enumeration": "4",
            "source_type": "move",
        }
        candidate = {
            "mechanism": "hidden",
            "clue": "Fallback clue token ***** (4)",
            "metadata": {"indicator": "concealed in", "surface": "rapid SMOG line"},
        }
        passed, issues = _validate_candidate(entry, candidate)
        self.assertFalse(passed)
        self.assertTrue(any(issue.get("code") == "clue_surface_disallowed" for issue in issues))

    def test_valid_non_boilerplate_clue_is_publishable(self):
        ranked = [
            {
                "clue": "Mixed letters in MLSREGAE produce creature (8)",
                "mechanism": "anagram",
                "validator_passed": True,
                "validator_issues": [],
                "rank_score": 88.0,
                "rank_position": 1,
            }
        ]
        self.assertTrue(is_ranked_candidate_publishable(ranked[0]))
        selected = select_ranked_candidate(ranked)
        self.assertIsNotNone(selected)
        self.assertEqual(selected["mechanism"], "anagram")


if __name__ == "__main__":
    unittest.main()
