from __future__ import annotations

import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace

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

from app.data.sample import redact_puzzle  # noqa: E402
from app.services.puzzle_export import build_pdf_export_bytes, build_text_export_payload  # noqa: E402


class PuzzleExportTests(unittest.TestCase):
    def test_text_payload_does_not_include_answers(self):
        puzzle = {
            "id": "puz_test",
            "date": "2026-03-03",
            "gameType": "crossword",
            "title": "Test Puzzle",
            "timezone": "Europe/London",
            "grid": {
                "width": 3,
                "height": 2,
                "cells": [
                    {"x": 0, "y": 0, "isBlock": False, "solution": "A"},
                    {"x": 1, "y": 0, "isBlock": True, "solution": None},
                    {"x": 2, "y": 0, "isBlock": False, "solution": "B"},
                    {"x": 0, "y": 1, "isBlock": False, "solution": "C"},
                    {"x": 1, "y": 1, "isBlock": False, "solution": "D"},
                    {"x": 2, "y": 1, "isBlock": False, "solution": "E"},
                ],
            },
            "entries": [
                {
                    "id": "1-across",
                    "number": 1,
                    "direction": "across",
                    "answer": "ZZTOP",
                    "clue": "Rocking group",
                    "length": 5,
                    "cells": [[0, 0], [2, 0], [0, 1], [1, 1], [2, 1]],
                }
            ],
            "metadata": {"difficulty": "easy", "themeTags": [], "source": "curated"},
        }
        redacted = redact_puzzle(puzzle)
        payload = build_text_export_payload(redacted)
        self.assertEqual(payload["grid"]["rows"], [".#.", "..."])
        self.assertEqual(payload["entries"][0]["clue"], "Rocking group")
        self.assertEqual(payload["entries"][0]["enumeration"], "5")
        self.assertNotIn("answer", payload["entries"][0])

    def test_pdf_export_is_valid_and_answer_not_leaked(self):
        payload = {
            "id": "puz_cryptic",
            "date": "2026-03-03",
            "gameType": "cryptic",
            "title": "Cryptic Export",
            "timezone": "Europe/London",
            "metadata": {"difficulty": "medium", "themeTags": []},
            "grid": {"width": 0, "height": 0, "rows": []},
            "entries": [
                {
                    "id": "1-across",
                    "number": 1,
                    "direction": "across",
                    "clue": "Odd clue text",
                    "length": 6,
                    "enumeration": "6",
                }
            ],
            "redactedAnswers": True,
        }
        pdf = build_pdf_export_bytes(payload)
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"Odd clue text", pdf)
        self.assertNotIn(b"PIKACHU", pdf)

    def test_connections_redaction_removes_group_answers(self):
        puzzle = {
            "id": "puz_connections_test",
            "date": "2026-03-04",
            "gameType": "connections",
            "title": "Connections Test",
            "timezone": "Europe/London",
            "grid": {
                "width": 4,
                "height": 4,
                "cells": [],
            },
            "entries": [],
            "metadata": {
                "difficulty": "medium",
                "themeTags": ["pokemon", "connections"],
                "source": "curated",
                "connections": {
                    "version": 1,
                    "tiles": [
                        {"id": "tile_1", "label": "BULBASAUR", "groupId": "yellow"},
                        {"id": "tile_2", "label": "CHARMANDER", "groupId": "yellow"},
                    ],
                    "groups": [
                        {
                            "id": "yellow",
                            "title": "Pokemon species",
                            "difficulty": "yellow",
                            "labels": ["BULBASAUR", "CHARMANDER", "SQUIRTLE", "PIKACHU"],
                        }
                    ],
                    "difficultyOrder": ["yellow", "green", "blue", "purple"],
                },
            },
        }

        redacted = redact_puzzle(puzzle)
        connections = redacted["metadata"]["connections"]
        self.assertIsNone(connections["tiles"][0]["groupId"])
        self.assertIsNone(connections["tiles"][1]["groupId"])
        self.assertEqual(connections["groups"][0]["labels"], [])


if __name__ == "__main__":
    unittest.main()
