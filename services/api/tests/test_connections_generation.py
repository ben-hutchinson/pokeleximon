from __future__ import annotations

import json
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


class ConnectionsGenerationTests(unittest.TestCase):
    def test_connections_quality_report_rejects_disallowed_labels(self):
        report = reserve_generator._connections_quality_report(
            groups=[
                {"title": "A", "labels": ["BULBASAUR", "CHARMANDER", "SQUIRTLE", "PIKACHU"]},
                {"title": "B", "labels": ["FLAMETHROWER", "THUNDERBOLT", "ICE BEAM", "SURF"]},
                {"title": "C", "labels": ["INTIMIDATE", "LEVITATE", "PRESSURE", "CLUE TOKEN"]},
                {"title": "D", "labels": ["POTION", "SUPER POTION", "FULL RESTORE", "REVIVE"]},
            ]
        )
        self.assertFalse(report["isPublishable"])
        self.assertIn("label_contains_disallowed_content", report["hardFailures"])

    def test_connections_payload_builder_produces_4x4_valid_set(self):
        rules = [
            {"id": "species", "title": "Pokemon species", "sourceType": "pokemon-species", "minLength": 4, "maxLength": 14},
            {"id": "moves", "title": "Pokemon moves", "sourceType": "move", "minLength": 4, "maxLength": 14},
            {"id": "abilities", "title": "Pokemon abilities", "sourceType": "ability", "minLength": 4, "maxLength": 14},
            {"id": "items", "title": "Pokemon items", "sourceType": "item", "minLength": 4, "maxLength": 14},
        ]
        corpus_rows = [
            {"sourceType": "pokemon-species", "answerDisplay": "Bulbasaur"},
            {"sourceType": "pokemon-species", "answerDisplay": "Charmander"},
            {"sourceType": "pokemon-species", "answerDisplay": "Squirtle"},
            {"sourceType": "pokemon-species", "answerDisplay": "Pikachu"},
            {"sourceType": "move", "answerDisplay": "Flamethrower"},
            {"sourceType": "move", "answerDisplay": "Thunderbolt"},
            {"sourceType": "move", "answerDisplay": "Ice Beam"},
            {"sourceType": "move", "answerDisplay": "Hydro Pump"},
            {"sourceType": "ability", "answerDisplay": "Intimidate"},
            {"sourceType": "ability", "answerDisplay": "Levitate"},
            {"sourceType": "ability", "answerDisplay": "Pressure"},
            {"sourceType": "ability", "answerDisplay": "Overgrow"},
            {"sourceType": "item", "answerDisplay": "Potion"},
            {"sourceType": "item", "answerDisplay": "Revive"},
            {"sourceType": "item", "answerDisplay": "Rare Candy"},
            {"sourceType": "item", "answerDisplay": "Quick Claw"},
        ]

        with (
            patch.object(reserve_generator, "_load_connections_overrides", return_value={}),
            patch.object(reserve_generator, "_load_connections_rules", return_value=rules),
            patch.object(reserve_generator, "_load_answer_corpus_rows", return_value=corpus_rows),
            patch.object(reserve_generator, "_append_connections_quality_report", return_value=None),
        ):
            payload, report = reserve_generator._build_connections_puzzle_payload(
                target_date=date(2026, 3, 7),
                timezone="Europe/London",
                seed_value=20260307,
            )

        self.assertTrue(report["isPublishable"])
        metadata = json.loads(payload["metadata"])
        connections = metadata["connections"]
        self.assertEqual(connections["version"], 1)
        self.assertEqual(connections["difficultyOrder"], ["yellow", "green", "blue", "purple"])
        self.assertEqual(len(connections["tiles"]), 16)
        self.assertEqual(len(connections["groups"]), 4)

        all_labels = [tile["label"] for tile in connections["tiles"]]
        self.assertEqual(len(all_labels), 16)
        self.assertEqual(len(set(all_labels)), 16)

        group_ids = {group["id"] for group in connections["groups"]}
        self.assertSetEqual(group_ids, {"yellow", "green", "blue", "purple"})
        tile_group_ids = {tile["groupId"] for tile in connections["tiles"]}
        self.assertSetEqual(tile_group_ids, group_ids)


if __name__ == "__main__":
    unittest.main()
