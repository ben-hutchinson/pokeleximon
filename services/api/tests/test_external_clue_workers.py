from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

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

from crossword.clue_bank import build_clue_bank, project_crossword_wide_rows  # noqa: E402
from crossword.clue_product_owner import evaluate_generator_candidates  # noqa: E402
from crossword import external_clue_sources  # noqa: E402
from crossword.external_clue_sources import FetchResult, sanitize_external_candidate, serebii_url_candidates  # noqa: E402
from crossword.provider_clue_workers import (  # noqa: E402
    HTML_PROVIDER_FETCHERS,
    build_bulbapedia_candidate_pool,
    generate_bulbapedia_clue,
    generate_html_provider_clue,
    load_answer_queue,
    select_next_answer,
)


class ExternalClueWorkerTests(unittest.TestCase):
    def test_load_answer_queue_and_select_next_answer_follow_csv_order(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "crossword.csv"
            csv_path.write_text(
                "answer,clue 1,clue 2,clue 3\n"
                "ABRA,Psi Pokemon,,\n"
                "ABRA,Psychic species,,\n"
                "ABSOL,Disaster Pokemon,,\n",
                encoding="utf-8",
            )

            queue = load_answer_queue(csv_path)
            self.assertEqual([row["answerKey"] for row in queue], ["ABRA", "ABSOL"])

            next_row = select_next_answer(csv_path, {"ABRA"})
            self.assertIsNotNone(next_row)
            self.assertEqual(next_row["answerKey"], "ABSOL")

    def test_generate_html_provider_clue_uses_first_sanitized_sentence(self) -> None:
        answer_row = {
            "answerKey": "ABSOL",
            "answerDisplay": "ABSOL",
            "sourceType": "pokemon-species",
            "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/359/",
            "sourceSlug": "absol",
        }
        fetch_result = FetchResult(
            status="ok",
            provider="serebii",
            url="https://www.serebii.net/pokedex-sv/absol",
            extract="Absol is a Dark-type Pokemon said to warn people of disasters.",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(HTML_PROVIDER_FETCHERS, {"serebii": lambda url, timeout_seconds: fetch_result}):
                result = generate_html_provider_clue(
                    provider="serebii",
                    answer_row=answer_row,
                    cache_dir=Path(temp_dir),
                    timeout_seconds=1.0,
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["provider"], "serebii")
        self.assertNotEqual(result["clue"], "")
        self.assertNotIn("ABSOL", result["clue"])

    def test_generate_html_provider_clue_trims_page_chrome_before_answer_sentence(self) -> None:
        answer_row = {
            "answerKey": "ABSOL",
            "answerDisplay": "ABSOL",
            "sourceType": "pokemon-species",
            "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/359/",
            "sourceSlug": "absol",
        }
        fetch_result = FetchResult(
            status="ok",
            provider="pokemondb",
            url="https://pokemondb.net/pokedex/absol",
            extract=(
                "Quick links National Pokédex Pokémon list Search Absol #0358 Chimecho "
                "#0360 Wynaut Contents Info Language Absol is a Dark type Pokémon introduced in Generation 3. "
                "Disaster Pokémon."
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(HTML_PROVIDER_FETCHERS, {"pokemondb": lambda url, timeout_seconds: fetch_result}):
                result = generate_html_provider_clue(
                    provider="pokemondb",
                    answer_row=answer_row,
                    cache_dir=Path(temp_dir),
                    timeout_seconds=1.0,
                )

        self.assertEqual(result["status"], "ok")
        self.assertIn("Generation 3", result["extract"])
        self.assertNotIn("Quick links", result["extract"])
        self.assertEqual(result["clue"], "Disaster Pokémon.")

    def test_fetch_pokemondb_description_falls_back_from_generic_meta_to_paragraph(self) -> None:
        class _FakeResponse:
            text = (
                '<html><head><meta name="description" '
                'content="Pokédex entry for #359 Absol containing stats, moves learned, evolution chain, location and more!">'
                "</head><body><p>Absol senses trouble and appears before disasters strike.</p></body></html>"
            )

            def raise_for_status(self) -> None:
                return None

        with patch.object(external_clue_sources.requests, "get", return_value=_FakeResponse()):
            result = external_clue_sources.fetch_pokemondb_description(
                "https://pokemondb.net/pokedex/absol",
                timeout_seconds=1.0,
            )

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.extract, "Absol senses trouble and appears before disasters strike.")

    def test_fetch_serebii_description_extracts_classification_and_flavor_text(self) -> None:
        class _FakeResponse:
            text = (
                "<html><body><table>"
                "<tr><th>Classification</th></tr><tr><td>Disaster Pokémon</td></tr>"
                "<tr><th>Flavor Text</th></tr><tr><td>It senses coming disasters and appears before people only to warn them.</td></tr>"
                "</table></body></html>"
            )

            def raise_for_status(self) -> None:
                return None

        with patch.object(external_clue_sources.requests, "get", return_value=_FakeResponse()):
            result = external_clue_sources.fetch_serebii_description(
                "https://www.serebii.net/pokedex-sv/absol",
                timeout_seconds=1.0,
            )

        self.assertEqual(result.status, "ok")
        self.assertIn("Disaster Pokémon.", result.extract)
        self.assertIn("warn them", result.extract)

    def test_sanitize_external_candidate_allows_concise_crossword_classification(self) -> None:
        clue = sanitize_external_candidate("Disaster Pokémon.", "ABSOL", "pokemon-species")
        self.assertEqual(clue, "Disaster Pokémon.")

    def test_sanitize_external_candidate_rejects_provider_boilerplate(self) -> None:
        self.assertIsNone(
            sanitize_external_candidate(
                "this item, including added effects and where to find it.",
                "ABILITY PATCH",
                "item",
            )
        )
        self.assertIsNone(
            sanitize_external_candidate(
                "this Pokémon is a Dark type Pokémon introduced in Generation 3.",
                "ABSOL",
                "pokemon-species",
            )
        )

    def test_serebii_url_candidates_follow_real_site_formats(self) -> None:
        self.assertIn(
            "https://www.serebii.net/pokedex-sv/absol",
            serebii_url_candidates("ABSOL", "pokemon-species", "absol"),
        )
        self.assertIn(
            "https://www.serebii.net/itemdex/abilitypatch.shtml",
            serebii_url_candidates("ABILITY PATCH", "item", "ability-patch"),
        )
        self.assertIn(
            "https://www.serebii.net/attackdex-sv/waterpulse.shtml",
            serebii_url_candidates("WATER PULSE", "move", "water-pulse"),
        )

    def test_generate_bulbapedia_clue_selects_best_scored_candidate(self) -> None:
        answer_row = {
            "answerKey": "STARAPTOR",
            "answerDisplay": "STARAPTOR",
            "sourceType": "pokemon-species",
            "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/398/",
            "sourceSlug": "staraptor",
        }
        evidence = {
            "pageUrl": "https://bulbapedia.bulbagarden.net/wiki/Staraptor_(Pokemon)",
            "leadText": "Staraptor is an intimidating bird Pokemon from Sinnoh.",
            "sections": [{"title": "Biology", "text": "It leaves its flock and lives solitarily."}],
        }
        curated = {
            "status": "ok",
            "schemaValid": True,
            "response": {
                "confidence": 0.9,
                "crossword_candidates": [
                    {
                        "text": "Staraptor flock loner",
                        "evidence_ref": "Biology",
                        "mystery_score": 0.3,
                        "specificity_score": 0.8,
                    },
                    {
                        "text": "Sinnoh flock loner",
                        "evidence_ref": "Biology",
                        "mystery_score": 0.7,
                        "specificity_score": 0.7,
                    },
                ],
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            result = generate_bulbapedia_clue(
                answer_row=answer_row,
                structured_facts={},
                cache_dir=Path(temp_dir) / "provider",
                evidence_cache_dir=Path(temp_dir) / "evidence",
                curator_cache_dir=Path(temp_dir) / "curator",
                evidence=evidence,
                curated=curated,
            )["result"]

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["clue"], "Sinnoh flock loner")
        self.assertTrue(result["approved"])

    def test_build_bulbapedia_candidate_pool_preserves_multiple_curated_clues(self) -> None:
        evidence = {
            "pageUrl": "https://bulbapedia.bulbagarden.net/wiki/Absol_(Pokemon)",
            "leadText": "Absol is known as the Disaster Pokémon.",
            "sections": [{"title": "Biology", "text": "It appears before disasters to warn people."}],
        }
        curated = {
            "response": {
                "confidence": 0.85,
                "crossword_candidates": [
                    {"text": "Disaster Pokemon", "evidence_ref": "lead", "mystery_score": 0.48, "specificity_score": 0.72, "style": "signature"},
                    {"text": "Warns people of calamity", "evidence_ref": "Biology", "mystery_score": 0.74, "specificity_score": 0.8, "style": "effect"},
                    {"text": "Gen III Dark species", "evidence_ref": "lead", "mystery_score": 0.54, "specificity_score": 0.66, "style": "taxonomy"},
                ],
            }
        }

        candidates = build_bulbapedia_candidate_pool(
            answer_display="ABSOL",
            evidence=evidence,
            curated=curated,
        )

        self.assertEqual(len(candidates), 3)
        self.assertTrue(all(row["provider"] == "bulbapedia" for row in candidates))
        self.assertEqual({row["clue"] for row in candidates}, {"Disaster Pokemon", "Warns people of calamity", "Gen III Dark species"})

    def test_product_owner_flags_duplicate_surface(self) -> None:
        answer_row = {
            "answerKey": "STARAPTOR",
            "answerDisplay": "STARAPTOR",
            "sourceType": "pokemon-species",
            "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/398/",
        }
        provider_candidates = [
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": "Sinnoh bird ace",
                "score": 92.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
            },
            {
                "provider": "serebii",
                "status": "ok",
                "clue": "Sinnoh bird ace",
                "score": 90.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
            },
            {
                "provider": "pokemondb",
                "status": "ok",
                "clue": "Sinnoh raptor threat",
                "score": 89.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
            },
        ]

        evaluation = evaluate_generator_candidates(
            answer_row=answer_row,
            provider_candidates=provider_candidates,
        )

        self.assertEqual(len(evaluation["selectedCandidates"]), 3)
        duplicate_rows = [row for row in evaluation["selectedCandidates"] if "duplicate_surface" in row["qualityFlags"]]
        self.assertTrue(duplicate_rows)
        self.assertEqual(evaluation["reviewStatus"], "needs_review")

    def test_product_owner_can_approve_three_unique_bulbapedia_clues(self) -> None:
        answer_row = {
            "answerKey": "ABSOL",
            "answerDisplay": "ABSOL",
            "sourceType": "pokemon-species",
            "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/359/",
        }
        provider_candidates = [
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": "Disaster Pokemon",
                "score": 91.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
                "style": "signature",
            },
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": "Warns people of calamity",
                "score": 93.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "Biology",
                "style": "effect",
            },
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": "Gen III Dark species",
                "score": 86.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
                "style": "taxonomy",
            },
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": "Gen III Disaster Pokemon",
                "score": 85.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
                "style": "signature",
            },
        ]

        evaluation = evaluate_generator_candidates(
            answer_row=answer_row,
            provider_candidates=provider_candidates,
        )

        self.assertEqual(evaluation["reviewStatus"], "approved")
        self.assertEqual(len(evaluation["selectedCandidates"]), 3)
        self.assertFalse(any("single_source_claim" in row["qualityFlags"] for row in evaluation["selectedCandidates"]))
        self.assertTrue(all(row["approved"] for row in evaluation["selectedCandidates"]))

    def test_product_owner_rejects_boilerplate_taxonomy_candidate(self) -> None:
        answer_row = {
            "answerKey": "ABSOL",
            "answerDisplay": "ABSOL",
            "sourceType": "pokemon-species",
            "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/359/",
        }
        provider_candidates = [
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": "Disaster Pokémon",
                "score": 92.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
            },
            {
                "provider": "pokemondb",
                "status": "ok",
                "clue": "this Pokémon is a Dark type Pokémon introduced in Generation 3.",
                "score": 98.0,
                "approved": True,
                "qualityFlags": [],
                "evidenceRef": "lead",
            },
        ]

        evaluation = evaluate_generator_candidates(
            answer_row=answer_row,
            provider_candidates=provider_candidates,
        )

        approved_texts = {row["text"] for row in evaluation["selectedCandidates"] if row["approved"]}
        rejected = [row for row in evaluation["selectedCandidates"] if not row["approved"]]
        self.assertIn("Disaster Pokémon", approved_texts)
        self.assertTrue(any("boilerplate_surface" in row["qualityFlags"] for row in rejected))

    def test_build_clue_bank_uses_product_owner_candidates_and_projects_three_columns(self) -> None:
        answer_rows = [
            {
                "answerKey": "ABSOL",
                "answerDisplay": "ABSOL",
                "sourceType": "pokemon-species",
                "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/359/",
            }
        ]
        product_owner_by_answer = {
            "ABSOL": {
                "selectedCandidates": [
                    {
                        "text": "Disaster omen",
                        "qualityScore": 96.0,
                        "qualityFlags": [],
                        "approved": True,
                        "evidenceRef": "lead",
                        "provider": "bulbapedia",
                    },
                    {
                        "text": "Dark calamity warning",
                        "qualityScore": 92.0,
                        "qualityFlags": [],
                        "approved": True,
                        "evidenceRef": "lead",
                        "provider": "serebii",
                    },
                    {
                        "text": "Sinister disaster herald",
                        "qualityScore": 90.0,
                        "qualityFlags": [],
                        "approved": True,
                        "evidenceRef": "lead",
                        "provider": "pokemondb",
                    },
                ],
                "reviewStatus": "approved",
                "entryFlags": [],
                "checklistScores": {"accuracy": 1.0},
                "selectionRationale": "all three providers supplied approved clues",
            }
        }

        entries, report = build_clue_bank(
            answer_rows=answer_rows,
            payload_index={},
            overrides={},
            product_owner_by_answer=product_owner_by_answer,
        )

        self.assertEqual(report["approvedCoveragePct"], 100.0)
        self.assertEqual(entries[0]["reviewStatus"], "approved")
        self.assertEqual(sum(1 for row in entries[0]["standardClues"] if row["approved"]), 3)

        csv_rows = project_crossword_wide_rows(entries)
        self.assertEqual(csv_rows[0], ("answer", "clue 1", "clue 2", "clue 3"))
        self.assertEqual(csv_rows[1][0], "ABSOL")
        self.assertEqual(csv_rows[1][1:], ("Disaster omen", "Dark calamity warning", "Sinister disaster herald"))


if __name__ == "__main__":
    unittest.main()
