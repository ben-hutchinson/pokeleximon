from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from tempfile import TemporaryDirectory

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

CROSSWORD_GEN_ROOT = Path(__file__).resolve().parents[2] / "crossword-gen"
if str(CROSSWORD_GEN_ROOT) not in sys.path:
    sys.path.append(str(CROSSWORD_GEN_ROOT))

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

from crossword.clue_bank import build_clue_bank, build_connections_rules  # noqa: E402
from app.services import reserve_generator  # noqa: E402


class ClueBankRuntimeTests(unittest.TestCase):
    def test_build_clue_bank_produces_three_approved_clues_and_descriptors(self):
        answer_rows = [
            {
                "answerKey": "ACADEMYBALL",
                "answerDisplay": "ACADEMY BALL",
                "sourceType": "item",
                "sourceRef": "https://pokeapi.co/api/v2/item/2030/",
            },
            {
                "answerKey": "AERILATE",
                "answerDisplay": "AERILATE",
                "sourceType": "ability",
                "sourceRef": "https://pokeapi.co/api/v2/ability/184/",
            },
            {
                "answerKey": "FIRE",
                "answerDisplay": "FIRE",
                "sourceType": "type",
                "sourceRef": "https://pokeapi.co/api/v2/type/10/",
            },
        ]
        payload_index = {
            ("item", 2030): {
                "id": 2030,
                "name": "academy-ball",
                "category": {"name": "pick-ingredients"},
                "game_indices": [{"generation": {"name": "generation-ix"}}],
                "effect_entries": [],
                "attributes": [],
            },
            ("ability", 184): {
                "id": 184,
                "name": "aerilate",
                "generation": {"name": "generation-vi"},
                "is_main_series": True,
                "effect_entries": [],
            },
        }

        entries, report = build_clue_bank(answer_rows, payload_index, overrides={})

        self.assertEqual(report["totalAnswers"], 3)
        self.assertGreaterEqual(report["approvedCoveragePct"], 100.0)

        by_answer = {row["answerKey"]: row for row in entries}
        self.assertGreaterEqual(sum(1 for row in by_answer["ACADEMYBALL"]["standardClues"] if row["approved"]), 3)
        self.assertGreaterEqual(sum(1 for row in by_answer["AERILATE"]["standardClues"] if row["approved"]), 3)
        self.assertGreaterEqual(sum(1 for row in by_answer["FIRE"]["standardClues"] if row["approved"]), 3)
        self.assertIn("burning element", by_answer["FIRE"]["crypticDefinitionSeeds"])
        self.assertTrue(by_answer["ACADEMYBALL"]["connectionsDescriptors"])

    def test_connections_rules_use_explicit_descriptor_labels(self):
        entries = [
            {
                "answerKey": "BULBASAUR",
                "answerDisplay": "BULBASAUR",
                "connectionsDescriptors": ["Gen I species", "Green species"],
            },
            {
                "answerKey": "CHARMANDER",
                "answerDisplay": "CHARMANDER",
                "connectionsDescriptors": ["Gen I species"],
            },
            {
                "answerKey": "SQUIRTLE",
                "answerDisplay": "SQUIRTLE",
                "connectionsDescriptors": ["Gen I species"],
            },
            {
                "answerKey": "PIKACHU",
                "answerDisplay": "PIKACHU",
                "connectionsDescriptors": ["Gen I species"],
            },
        ]

        rules = build_connections_rules(entries, max_rules=10)
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["title"], "Gen I species")
        self.assertEqual(sorted(rules[0]["labels"]), ["BULBASAUR", "CHARMANDER", "PIKACHU", "SQUIRTLE"])

    def test_crossword_variant_selection_is_deterministic_by_seed(self):
        lexicon = [
            {
                "answer": "PIKACHU",
                "clues": ["Electric mascot", "Mouse Pokemon", "Gen I mascot"],
                "enumeration": "7",
            }
        ]

        selected_a = reserve_generator._materialize_crossword_lexicon_for_run(lexicon, seed_value=20260311)
        selected_b = reserve_generator._materialize_crossword_lexicon_for_run(lexicon, seed_value=20260311)
        selected_variants = {
            reserve_generator._materialize_crossword_lexicon_for_run(lexicon, seed_value=seed)[0]["clue"]
            for seed in range(20260311, 20260317)
        }

        self.assertEqual(selected_a, selected_b)
        self.assertNotEqual(selected_a[0]["clue"], "")
        self.assertGreater(len(selected_variants), 1)

    def test_connections_pool_builder_accepts_explicit_rule_labels(self):
        rules = [{"id": "gen-i-species", "title": "Gen I species", "labels": ["Bulbasaur", "Charmander", "Squirtle", "Pikachu"]}]
        pools = reserve_generator._build_connections_pool_by_rule(rules, corpus_rows=[])
        self.assertEqual(pools["gen-i-species"], ["BULBASAUR", "CHARMANDER", "PIKACHU", "SQUIRTLE"])

    def test_load_cryptic_lexicon_supports_multiple_clues_and_optional_metadata_from_csv(self):
        with TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "cryptic.csv"
            csv_path.write_text(
                "answer,clue 1,clue 2,clue 3,display_answer,enumeration,mechanism,wordplay_plan,source_ref,source_type\n"
                "ABILITYSHIELD,Blocks Ability tampering,Holder keeps its trait,,ABILITY SHIELD,\"7,6\",manual,No stored breakdown,csv://manual#ABILITYSHIELD,manual-curated\n"
                "EMBARGO,Held-item-locking move,Target cannot use held items,,EMBARGO,7,manual,,csv://manual#EMBARGO,manual-curated\n",
                encoding="utf-8",
            )
            original = reserve_generator.CRYPTIC_CSV_PATH
            reserve_generator.CRYPTIC_CSV_PATH = csv_path
            try:
                lexicon = reserve_generator._load_cryptic_lexicon()
            finally:
                reserve_generator.CRYPTIC_CSV_PATH = original

        by_answer = {row["answer"]: row for row in lexicon}
        self.assertEqual(by_answer["ABILITYSHIELD"]["display_name"], "ABILITY SHIELD")
        self.assertEqual(by_answer["ABILITYSHIELD"]["enumeration"], "7,6")
        self.assertEqual(len(by_answer["ABILITYSHIELD"]["clues"]), 2)
        self.assertEqual(by_answer["ABILITYSHIELD"]["clues"][0]["mechanism"], "manual")

    def test_load_cryptic_lexicon_supports_json_rows_grouped_by_answer(self):
        with TemporaryDirectory() as tmp_dir:
            json_path = Path(tmp_dir) / "cryptic.json"
            json_path.write_text(
                json.dumps(
                    [
                        {"answer": "ABILITY SHIELD", "clue": "Blocks Ability tampering"},
                        {"answer": "ABILITY SHIELD", "clue": "Holder keeps its trait"},
                        {"answer": "EMBARGO", "clue": "Held-item-locking move"},
                    ]
                ),
                encoding="utf-8",
            )
            original = reserve_generator.CRYPTIC_CSV_PATH
            reserve_generator.CRYPTIC_CSV_PATH = json_path
            try:
                lexicon = reserve_generator._load_cryptic_lexicon()
            finally:
                reserve_generator.CRYPTIC_CSV_PATH = original

        by_answer = {row["answer"]: row for row in lexicon}
        self.assertEqual(by_answer["ABILITYSHIELD"]["display_name"], "ABILITY SHIELD")
        self.assertEqual(by_answer["ABILITYSHIELD"]["enumeration"], "7,6")
        self.assertEqual(len(by_answer["ABILITYSHIELD"]["clues"]), 2)
        self.assertEqual(by_answer["ABILITYSHIELD"]["source_ref"], "json://cryptic.json#ABILITYSHIELD")

    def test_load_crossword_csv_lexicon_supports_wide_clue_columns(self):
        with TemporaryDirectory() as tmp_dir:
            csv_path = Path(tmp_dir) / "crossword.csv"
            csv_path.write_text(
                "answer,clue 1,clue 2,clue 3\n"
                "ABANDONED SHIP,Dive-only landmark,Hides the Scanner,Hoenn shipwreck\n",
                encoding="utf-8",
            )
            original = reserve_generator.CROSSWORD_CSV_PATH
            reserve_generator.CROSSWORD_CSV_PATH = csv_path
            try:
                lexicon = reserve_generator._load_crossword_csv_lexicon()
            finally:
                reserve_generator.CROSSWORD_CSV_PATH = original

        self.assertEqual(lexicon[0]["answer"], "ABANDONEDSHIP")
        self.assertEqual(
            lexicon[0]["clues"],
            ["Dive-only landmark", "Hides the Scanner", "Hoenn shipwreck"],
        )

    def test_cryptic_variant_selection_is_deterministic_by_seed(self):
        lexicon = [
            {
                "answer": "ABILITYSHIELD",
                "display_name": "ABILITY SHIELD",
                "enumeration": "7,6",
                "source_ref": "csv://manual#ABILITYSHIELD",
                "source_type": "manual-curated",
                "clues": [
                    {"clue": "Blocks Ability tampering", "mechanism": "manual", "wordplay_plan": "", "wordplay_metadata": {}},
                    {"clue": "Holder keeps its trait", "mechanism": "manual", "wordplay_plan": "", "wordplay_metadata": {}},
                    {"clue": "Suppression-proof held item", "mechanism": "manual", "wordplay_plan": "", "wordplay_metadata": {}},
                ],
            }
        ]

        selected_a = reserve_generator._materialize_cryptic_lexicon_for_run(lexicon, seed_value=20260312)
        selected_b = reserve_generator._materialize_cryptic_lexicon_for_run(lexicon, seed_value=20260312)
        selected_variants = {
            reserve_generator._materialize_cryptic_lexicon_for_run(lexicon, seed_value=seed)[0]["clue"]
            for seed in range(20260312, 20260318)
        }

        self.assertEqual(selected_a, selected_b)
        self.assertGreater(len(selected_variants), 1)


if __name__ == "__main__":
    unittest.main()
