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

from app.data import repo  # noqa: E402
from app.services import reserve_generator  # noqa: E402


class _FakeCursor:
    def __init__(self, *, fetchall_rows: list[dict] | None = None):
        self._fetchall_rows = list(fetchall_rows or [])

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, query: str, params: dict):  # noqa: ARG002
        return None

    def fetchall(self):
        return list(self._fetchall_rows)


class _FakeConn:
    def __init__(self, cursor: _FakeCursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, row_factory=None):  # noqa: ARG002
        return self._cursor


class DraftWorkflowTests(unittest.TestCase):
    def test_crossword_draft_builder_emits_blank_clues(self):
        lexicon = [{"answer": "ABRA", "enumeration": "4"}]
        governed_payload = {
            "id": "puz_test",
            "grid": reserve_generator.json.dumps({"width": 4, "height": 1, "cells": []}),
            "entries": reserve_generator.json.dumps(
                [
                    {
                        "id": "a1",
                        "direction": "across",
                        "number": 1,
                        "answer": "ABRA",
                        "clue": "Teleporting Gen I psychic",
                        "length": 4,
                        "cells": [[0, 0], [1, 0], [2, 0], [3, 0]],
                        "sourceRef": "csv://wordlist_crossword_answer_clue.csv#ABRA",
                        "enumeration": "4",
                    }
                ]
            ),
            "metadata": reserve_generator.json.dumps({"difficulty": "easy", "themeTags": ["pokemon"], "source": "curated"}),
        }
        quality_report = {"isPublishable": True, "score": 91.0, "hardFailures": [], "warnings": []}

        with patch.object(
            reserve_generator,
            "_build_governed_crossword_draft_payload",
            return_value=(governed_payload, quality_report, 1),
        ):
            payload = reserve_generator._build_crossword_draft_payload(
                target_date=date(2026, 3, 30),
                timezone="Europe/London",
                lexicon=lexicon,
                seed_value=20260330,
            )

        entries = reserve_generator.json.loads(payload["entries"])
        metadata = reserve_generator.json.loads(payload["metadata"])
        self.assertEqual(entries[0]["clue"], "")
        self.assertEqual(metadata["editorial"]["state"], "draft")
        self.assertTrue(metadata["editorial"]["validation"]["structuralQuality"]["isPublishable"])

    def test_crossword_draft_materializer_keeps_answers_without_clues(self):
        rows = reserve_generator._materialize_crossword_lexicon_for_draft(
            [{"answer": "ABANDONEDSHIP", "enumeration": "9,4", "source_ref": "csv://wordlist_crossword_answer_clue.csv#ABANDONEDSHIP"}]
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["answer"], "ABANDONEDSHIP")
        self.assertEqual(rows[0]["clue"], "")
        self.assertEqual(rows[0]["enumeration"], "9,4")

    def test_cryptic_draft_validation_rejects_blank_and_answer_leak(self):
        blank_report = repo._validate_cryptic_draft_entries(
            [{"id": "a1", "answer": "MEW", "clue": "", "length": 3, "cells": [[0, 0], [1, 0], [2, 0]]}]
        )
        leak_report = repo._validate_cryptic_draft_entries(
            [{"id": "a1", "answer": "MEW", "clue": "Legendary MEW clue", "length": 3, "cells": [[0, 0], [1, 0], [2, 0]]}]
        )

        self.assertFalse(blank_report["isPublishable"])
        self.assertIn("blank_clues_present", blank_report["hardFailures"])
        self.assertFalse(leak_report["isPublishable"])
        self.assertIn("clue_leaks_answer_text", leak_report["hardFailures"])

    def test_crossword_draft_validation_ignores_structural_metrics(self):
        report = repo._validate_crossword_draft_entries(
            [
                {"id": "a1", "answer": "ABRA", "clue": "Gen I teleporter", "length": 4, "cells": [[0, 0], [1, 0], [2, 0], [3, 0]]},
                {"id": "a2", "answer": "KADABRA", "clue": "Abra evolution", "length": 7, "cells": [[0, 1], [1, 1], [2, 1], [3, 1], [4, 1], [5, 1], [6, 1]]},
                {"id": "a3", "answer": "ALAKAZAM", "clue": "Final spoon-bender", "length": 8, "cells": [[0, 2], [1, 2], [2, 2], [3, 2], [4, 2], [5, 2], [6, 2], [7, 2]]},
                {"id": "a4", "answer": "MEWTWO", "clue": "Armored clone in one movie", "length": 7, "cells": [[0, 3], [1, 3], [2, 3], [3, 3], [4, 3], [5, 3], [6, 3]]},
                {"id": "a5", "answer": "LUGIA", "clue": "Whirl Islands legend", "length": 5, "cells": [[0, 4], [1, 4], [2, 4], [3, 4], [4, 4]]},
                {"id": "a6", "answer": "HOOPA", "clue": "Ring-bearing Mythical", "length": 5, "cells": [[0, 5], [1, 5], [2, 5], [3, 5], [4, 5]]},
                {"id": "a7", "answer": "RAYQUAZA", "clue": "Sky High Pokemon", "length": 8, "cells": [[0, 6], [1, 6], [2, 6], [3, 6], [4, 6], [5, 6], [6, 6], [7, 6]]},
                {"id": "a8", "answer": "GROUDON", "clue": "Land-shaping titan", "length": 7, "cells": [[0, 7], [1, 7], [2, 7], [3, 7], [4, 7], [5, 7], [6, 7]]},
                {"id": "a9", "answer": "KYOGRE", "clue": "Sea Basin legend", "length": 6, "cells": [[0, 8], [1, 8], [2, 8], [3, 8], [4, 8], [5, 8]]},
                {"id": "a10", "answer": "GIRATINA", "clue": "Origin Forme renegade", "length": 8, "cells": [[0, 9], [1, 9], [2, 9], [3, 9], [4, 9], [5, 9], [6, 9], [7, 9]]},
                {"id": "a11", "answer": "RESHIRAM", "clue": "Truth-seeking dragon", "length": 8, "cells": [[0, 10], [1, 10], [2, 10], [3, 10], [4, 10], [5, 10], [6, 10], [7, 10]]},
                {"id": "a12", "answer": "ZEKROM", "clue": "Ideals dragon", "length": 6, "cells": [[0, 11], [1, 11], [2, 11], [3, 11], [4, 11], [5, 11]]},
            ]
        )
        self.assertTrue(report["isPublishable"])
        self.assertEqual(report["hardFailures"], [])

    def test_draft_ready_notification_waits_for_both_game_types(self):
        cursor = _FakeCursor(
            fetchall_rows=[
                {"id": "puz_cross_1", "game_type": "crossword", "metadata": {}},
                {"id": "puz_crypt_1", "game_type": "cryptic", "metadata": {}},
            ]
        )
        with (
            patch.object(repo, "get_db", return_value=_FakeConn(cursor)),
            patch.object(repo, "create_operational_alert", return_value=({"id": 1}, True)) as create_alert,
            patch.object(repo, "notify_external_alert") as notify,
        ):
            item = repo.maybe_emit_draft_ready_notification(date_value="2026-03-30", timezone="Europe/London")

        self.assertEqual(item, {"id": 1})
        create_alert.assert_called_once()
        notify.assert_called_once()
        details = create_alert.call_args.kwargs["details"]
        self.assertEqual(details["date"], "2026-03-30")
        self.assertEqual([draft["gameType"] for draft in details["drafts"]], ["crossword", "cryptic"])

    def test_draft_ready_notification_skips_when_one_draft_missing(self):
        cursor = _FakeCursor(fetchall_rows=[{"id": "puz_cross_1", "game_type": "crossword", "metadata": {}}])
        with (
            patch.object(repo, "get_db", return_value=_FakeConn(cursor)),
            patch.object(repo, "create_operational_alert") as create_alert,
            patch.object(repo, "notify_external_alert") as notify,
        ):
            item = repo.maybe_emit_draft_ready_notification(date_value="2026-03-30", timezone="Europe/London")

        self.assertIsNone(item)
        create_alert.assert_not_called()
        notify.assert_not_called()


if __name__ == "__main__":
    unittest.main()
