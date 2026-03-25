from __future__ import annotations

import unittest
from pathlib import Path

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

from app.services.puzzle_quality import evaluate_crossword_publishability  # noqa: E402


def _baseline_entries() -> list[dict]:
    answers = [
        "ALPHA",
        "BRAVO",
        "CHARLI",
        "DELTAA",
        "ECHOOOO",
        "FOXTROT",
        "GAMMA",
        "HELIO",
        "INDIGO",
        "JULIET",
        "KILOWWW",
        "LIMAQQQ",
    ]
    lengths = [5, 5, 6, 6, 7, 7, 5, 5, 6, 6, 7, 7]
    entries: list[dict] = []

    for idx in range(6):
        y = idx
        cells = [[x, y] for x in range(5)]
        entries.append(
            {
                "id": f"a{idx + 1}",
                "direction": "across",
                "number": idx + 1,
                "answer": answers[idx],
                "clue": f"Across clue {idx + 1}",
                "length": lengths[idx],
                "cells": cells,
            }
        )

    for idx in range(6):
        x = idx
        cells = [[x, y] for y in range(5)]
        entries.append(
            {
                "id": f"d{idx + 1}",
                "direction": "down",
                "number": idx + 1,
                "answer": answers[idx + 6],
                "clue": f"Down clue {idx + 1}",
                "length": lengths[idx + 6],
                "cells": cells,
            }
        )
    return entries


def _grid(width: int, height: int, open_cells: set[tuple[int, int]]) -> dict:
    cells = []
    for y in range(height):
        for x in range(width):
            is_open = (x, y) in open_cells
            cells.append(
                {
                    "x": x,
                    "y": y,
                    "isBlock": not is_open,
                    "solution": "A" if is_open else None,
                    "entryIdAcross": None,
                    "entryIdDown": None,
                }
            )
    return {"width": width, "height": height, "cells": cells}


class PuzzleQualityTests(unittest.TestCase):
    def test_publishable_crossword_passes_governance(self):
        entries = _baseline_entries()
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertTrue(result["isPublishable"])
        self.assertEqual(result["hardFailures"], [])

    def test_duplicate_clues_fail_governance(self):
        entries = _baseline_entries()
        for idx in range(4):
            entries[idx]["clue"] = "Repeated clue"
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertFalse(result["isPublishable"])
        self.assertIn("duplicate_clues_detected", result["hardFailures"])

    def test_answer_leak_in_clue_fails_governance(self):
        entries = _baseline_entries()
        entries[0]["clue"] = f"Includes {entries[0]['answer']} in clue text"
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertFalse(result["isPublishable"])
        self.assertIn("clue_leaks_answer_text", result["hardFailures"])

    def test_placeholder_token_clue_fails_governance(self):
        entries = _baseline_entries()
        entries[0]["clue"] = "Pokemon move catalog clue token A1B2C3; enumeration 6."
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertFalse(result["isPublishable"])
        self.assertIn("clue_contains_disallowed_content", result["hardFailures"])

    def test_structural_letter_pattern_clue_fails_governance(self):
        entries = _baseline_entries()
        entries[0]["clue"] = "Pokémon location clue with initials IA and 12 total letters."
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertFalse(result["isPublishable"])
        self.assertIn("clue_contains_disallowed_content", result["hardFailures"])

    def test_structural_vowel_count_clue_fails_governance(self):
        entries = _baseline_entries()
        entries[0]["clue"] = "Pokémon move clue: ending letters LE; vowels 6, consonants 7."
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertFalse(result["isPublishable"])
        self.assertIn("clue_contains_disallowed_content", result["hardFailures"])

    def test_generic_clue_token_fails_governance(self):
        entries = _baseline_entries()
        entries[0]["clue"] = "Clue token *****"
        open_cells = {(x, y) for x in range(6) for y in range(6)} - {(5, 5)}
        result = evaluate_crossword_publishability(
            grid=_grid(8, 8, open_cells),
            entries=entries,
            metadata={"themeTags": ["pokemon", "crossword"], "source": "curated"},
        )
        self.assertFalse(result["isPublishable"])
        self.assertIn("clue_contains_disallowed_content", result["hardFailures"])


if __name__ == "__main__":
    unittest.main()
