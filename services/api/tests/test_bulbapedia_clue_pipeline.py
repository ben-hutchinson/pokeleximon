from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys


API_ROOT = Path(__file__).resolve().parents[1]
if str(API_ROOT) not in sys.path:
    sys.path.append(str(API_ROOT))

CROSSWORD_GEN_ROOT = Path(__file__).resolve().parents[2] / "crossword-gen"
if str(CROSSWORD_GEN_ROOT) not in sys.path:
    sys.path.append(str(CROSSWORD_GEN_ROOT))

from crossword import bulbapedia_evidence, clue_curator_agent  # noqa: E402
from crossword.clue_bank import build_clue_bank, build_override_candidates, load_editorial_seeds  # noqa: E402
from crossword.clue_candidate_qa import score_candidate  # noqa: E402
from crossword.clue_curator_local import curate_clues_locally  # noqa: E402
from crossword.clue_unresolved_audit import build_unresolved_audit  # noqa: E402


class _FakeResponse:
    def __init__(self, payload: dict[str, object]):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class BulbapediaCluePipelineTests(unittest.TestCase):
    def test_title_candidates_include_mixed_hyphen_variants(self) -> None:
        candidates = bulbapedia_evidence.title_candidates(
            answer_display="NEVER MELT ICE",
            source_type="item",
            canonical_slug="never-melt-ice",
        )
        self.assertIn("Never-Melt Ice", candidates)
        self.assertIn("Never Melt-Ice", candidates)

    def test_fetch_bulbapedia_evidence_resolves_sections_and_uses_cache(self) -> None:
        responses = [
            {
                "query": {
                    "pages": {
                        "1": {
                            "pageid": 1,
                            "title": "Staraptor (Pokemon)",
                            "fullurl": "https://bulbapedia.bulbagarden.net/wiki/Staraptor_(Pok%C3%A9mon)",
                            "lastrevid": 12345,
                        }
                    }
                }
            },
            {"query": {"pages": {"1": {"extract": "Staraptor is an intimidating bird Pokemon from Sinnoh."}}}},
            {
                "parse": {
                    "sections": [
                        {"index": "1", "line": "Biology"},
                        {"index": "2", "line": "Game data"},
                        {"index": "3", "line": "Trivia"},
                    ]
                }
            },
            {"parse": {"text": {"*": "<p>It leaves its flock and lives solitarily.</p>"}}},
            {"parse": {"text": {"*": "<p>It is known for high Attack and Speed.</p>"}}},
            {"parse": {"text": {"*": "<p>Unused because only first matched sections are needed.</p>"}}},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(bulbapedia_evidence, "_get_json", side_effect=responses) as mocked_get_json:
                evidence = bulbapedia_evidence.fetch_bulbapedia_evidence(
                    answer_key="STARAPTOR",
                    answer_display="STARAPTOR",
                    source_type="pokemon-species",
                    canonical_slug="staraptor",
                    structured_facts={},
                    cache_dir=Path(temp_dir),
                )

            self.assertEqual(evidence["status"], "ok")
            self.assertEqual(evidence["pageTitle"], "Staraptor (Pokemon)")
            self.assertEqual(evidence["pageRevisionId"], 12345)
            self.assertEqual([row["title"] for row in evidence["sections"]], ["Biology", "Game data", "Trivia"][: len(evidence["sections"])])
            self.assertGreaterEqual(mocked_get_json.call_count, 5)

            with patch.object(bulbapedia_evidence, "_get_json", side_effect=AssertionError("cache should be used")):
                cached = bulbapedia_evidence.fetch_bulbapedia_evidence(
                    answer_key="STARAPTOR",
                    answer_display="STARAPTOR",
                    source_type="pokemon-species",
                    canonical_slug="staraptor",
                    structured_facts={},
                    cache_dir=Path(temp_dir),
                )
            self.assertEqual(cached["pageRevisionId"], 12345)

    def test_fetch_bulbapedia_evidence_uses_search_fallback_for_title_mismatch(self) -> None:
        def fake_resolve(title: str, _timeout: float) -> dict[str, object] | None:
            if title == "Dragon's Maw (Ability)":
                return {
                    "pageId": 77,
                    "title": "Dragon's Maw (Ability)",
                    "fullUrl": "https://bulbapedia.bulbagarden.net/wiki/Dragon%27s_Maw_(Ability)",
                    "lastRevid": 456,
                }
            return None

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(bulbapedia_evidence, "resolve_page_metadata", side_effect=fake_resolve) as mocked_resolve:
                with patch.object(
                    bulbapedia_evidence,
                    "search_page_titles",
                    return_value=["Dragon's Maw (Ability)"],
                ) as mocked_search:
                    with patch.object(
                        bulbapedia_evidence,
                        "fetch_lead_text",
                        return_value="Dragon's Maw is an Ability introduced in Generation VIII.",
                    ):
                        with patch.object(bulbapedia_evidence, "fetch_sections", return_value=[]):
                            evidence = bulbapedia_evidence.fetch_bulbapedia_evidence(
                                answer_key="DRAGONSMAW",
                                answer_display="DRAGONS MAW",
                                source_type="ability",
                                canonical_slug="dragons-maw",
                                structured_facts={},
                                cache_dir=Path(temp_dir),
                            )

        self.assertEqual(evidence["status"], "ok")
        self.assertEqual(evidence["pageTitle"], "Dragon's Maw (Ability)")
        self.assertEqual(evidence["pageRevisionId"], 456)
        self.assertGreaterEqual(mocked_resolve.call_count, 2)
        mocked_search.assert_called()

    def test_second_pass_item_evidence_uses_family_page_and_cache_mode(self) -> None:
        responses = [
            {
                "query": {
                    "pages": {
                        "1": {
                            "pageid": 10,
                            "title": "Aguav Berry",
                            "fullurl": "https://bulbapedia.bulbagarden.net/wiki/Aguav_Berry",
                            "lastrevid": 222,
                        }
                    }
                }
            },
            {"query": {"pages": {"1": {"extract": "Aguav Berry is a Berry introduced in Generation III."}}}},
            {"parse": {"sections": [{"index": "1", "line": "Description"}]}},
            {"parse": {"text": {"*": "<p>It is a Berry.</p>"}}},
            {
                "query": {
                    "pages": {
                        "2": {
                            "pageid": 11,
                            "title": "Berry",
                            "fullurl": "https://bulbapedia.bulbagarden.net/wiki/Berry",
                            "lastrevid": 333,
                        }
                    }
                }
            },
            {"parse": {"sections": [{"index": "2", "line": "Description"}, {"index": "3", "line": "Acquisition"}]}},
            {"parse": {"text": {"*": "<p>Many Berries restore HP when HP is low and may confuse if disliked.</p>"}}},
            {"parse": {"text": {"*": "<p>Berries are found throughout the core series games.</p>"}}},
        ]

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.object(bulbapedia_evidence, "_get_json", side_effect=responses) as mocked_get_json:
                evidence = bulbapedia_evidence.fetch_bulbapedia_evidence(
                    answer_key="AGUAVBERRY",
                    answer_display="AGUAV BERRY",
                    source_type="item",
                    canonical_slug="aguav-berry",
                    structured_facts={"category": "berries"},
                    cache_dir=Path(temp_dir),
                    second_pass=True,
                )
            self.assertEqual(evidence["passMode"], "second_pass")
            self.assertTrue(evidence["familyPages"])
            self.assertGreaterEqual(len(evidence["sections"]), 2)
            self.assertGreaterEqual(mocked_get_json.call_count, 8)

            with patch.object(bulbapedia_evidence, "_get_json", side_effect=AssertionError("cache should be reused")):
                cached = bulbapedia_evidence.fetch_bulbapedia_evidence(
                    answer_key="AGUAVBERRY",
                    answer_display="AGUAV BERRY",
                    source_type="item",
                    canonical_slug="aguav-berry",
                    structured_facts={"category": "berries"},
                    cache_dir=Path(temp_dir),
                    second_pass=True,
                )
            self.assertEqual(cached["passMode"], "second_pass")

    def test_call_curator_invalid_schema_is_cached(self) -> None:
        payload = {
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"fact_nuggets":[],"crossword_candidates":[],"cryptic_definition_seeds":["raptor"],'
                            '"connections_descriptors":["Sinnoh birds"],"risk_flags":[]}'
                        )
                    }
                }
            ]
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=False):
                with patch.object(clue_curator_agent.requests, "post", return_value=_FakeResponse(payload)) as mocked_post:
                    first = clue_curator_agent.call_curator(
                        answer_row={"answerKey": "STARAPTOR", "answerDisplay": "STARAPTOR"},
                        evidence={"pageRevisionId": 12345},
                        structured_facts={"sourceType": "pokemon-species"},
                        cache_dir=Path(temp_dir),
                        timeout_seconds=1.0,
                    )
                self.assertEqual(first["status"], "invalid_schema")
                self.assertFalse(first["schemaValid"])
                self.assertIn("missing_confidence", first["errors"])
                self.assertEqual(mocked_post.call_count, 1)

                with patch.object(
                    clue_curator_agent.requests,
                    "post",
                    side_effect=AssertionError("cached invalid schema should be reused"),
                ):
                    second = clue_curator_agent.call_curator(
                        answer_row={"answerKey": "STARAPTOR", "answerDisplay": "STARAPTOR"},
                        evidence={"pageRevisionId": 12345},
                        structured_facts={"sourceType": "pokemon-species"},
                        cache_dir=Path(temp_dir),
                        timeout_seconds=1.0,
                    )
                self.assertEqual(second["status"], "invalid_schema")

    def test_score_candidate_rejects_verbatim_and_answer_leaks(self) -> None:
        evidence = {
            "leadText": "It has a savage nature and challenges foes much larger than itself.",
            "sections": [{"title": "Biology", "text": "It leaves its flock to live solitarily."}],
        }

        score, flags, approved = score_candidate(
            text="It has a savage nature and challenges foes much larger than itself.",
            answer_display="STARAPTOR",
            evidence=evidence,
            evidence_ref="lead",
            style="agent_curated",
            agent_confidence=0.9,
            mystery_score=0.7,
            specificity_score=0.7,
        )
        self.assertFalse(approved)
        self.assertIn("near_verbatim_source", flags)
        self.assertLess(score, 60.0)

        _, leak_flags, leak_approved = score_candidate(
            text="Staraptor with brutal Attack",
            answer_display="STARAPTOR",
            evidence=evidence,
            evidence_ref="Biology",
            style="agent_curated",
            agent_confidence=0.9,
            mystery_score=0.7,
            specificity_score=0.7,
        )
        self.assertFalse(leak_approved)
        self.assertIn("answer_fragment_leak", leak_flags)

    def test_score_candidate_allows_generic_answer_fragment_without_hard_reject(self) -> None:
        score, flags, approved = score_candidate(
            text="Blocks Ability tampering",
            answer_display="ABILITY SHIELD",
            evidence={"leadText": "", "sections": []},
            evidence_ref="lead",
            style="agent_curated",
            agent_confidence=0.8,
            mystery_score=0.7,
            specificity_score=0.8,
        )
        self.assertTrue(approved)
        self.assertIn("answer_fragment_leak", flags)
        self.assertGreater(score, 70.0)

    def test_local_curator_generates_species_clues_from_bulbapedia_evidence(self) -> None:
        evidence = {
            "pageRevisionId": 4504986,
            "leadText": (
                "Staraptor is a dual-type Normal/Flying Pokemon introduced in Generation IV. "
                "It evolves from Staravia. Staraptor can Mega Evolve into Mega Staraptor."
            ),
            "sections": [
                {
                    "title": "Biology",
                    "text": (
                        "Staraptor is a grayish-brown, avian Pokemon similar to a large bird of prey. "
                        "After evolving, Staraptor leaves its flock to live alone. "
                        "Its powerful wing and leg muscles allow it to fly effortlessly while carrying other Pokemon. "
                        "It fusses over the shape of its comb."
                    ),
                },
                {
                    "title": "Game data",
                    "text": (
                        "Attack : 120 Defense : 70 Speed : 100 "
                        "Mega Staraptor Staraptor Fighting Flying Evolution data"
                    ),
                },
                {
                    "title": "Pokédex entries",
                    "text": "It has a savage nature. It will courageously challenge foes that are much larger than itself.",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            payload = curate_clues_locally(
                answer_row={
                    "answerKey": "STARAPTOR",
                    "answerDisplay": "STARAPTOR",
                    "sourceType": "pokemon-species",
                    "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/398/",
                },
                evidence=evidence,
                structured_facts={"sourceType": "pokemon-species", "genus": "Predator Pokemon"},
                cache_dir=Path(temp_dir),
            )

        self.assertEqual(payload["status"], "ok")
        response = payload["response"]
        candidate_texts = [row["text"] for row in response["crossword_candidates"]]
        self.assertIn("Gray-Brown bird of prey", candidate_texts)
        self.assertIn("Leaves its flock behind", candidate_texts)
        self.assertIn("Mega form turns Fighting/Flying", candidate_texts)
        self.assertIn("bird of prey", response["cryptic_definition_seeds"])
        self.assertIn("Gen IV Normal/Flying species", response["connections_descriptors"])

    def test_local_curator_generates_item_and_location_surfaces_from_evidence(self) -> None:
        item_evidence = {
            "pageRevisionId": 1,
            "leadText": "The Ability Patch is a type of item introduced in Generation VIII. It changes a Pokemon's Ability.",
            "sections": [
                {
                    "title": "Description",
                    "text": "A patch that can be used to change the regular Ability of a Pokemon to a rarer Ability.",
                },
                {
                    "title": "In the core series games",
                    "text": (
                        "If used from the Bag, it changes the Ability slot of a Pokemon from one of its standard "
                        "Abilities to its Hidden Ability. The Ability Patch can only be used on a Pokemon that "
                        "belongs to a species with a Hidden Ability."
                    ),
                },
            ],
        }
        location_evidence = {
            "pageRevisionId": 2,
            "leadText": (
                "The Abandoned Ship is a wrecked ship located on Route 108 in Hoenn. "
                "The second part can only be accessed by using Dive and contains the Scanner. "
                "Sea Mauville takes the place of the Abandoned Ship."
            ),
            "sections": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            item_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "ABILITYPATCH",
                    "answerDisplay": "ABILITY PATCH",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/1657/",
                },
                evidence=item_evidence,
                structured_facts={"sourceType": "item", "category": "medicine"},
                cache_dir=Path(temp_dir),
            )
            location_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "ABANDONEDSHIP",
                    "answerDisplay": "ABANDONED SHIP",
                    "sourceType": "location",
                    "sourceRef": "https://pokeapi.co/api/v2/location/447/",
                },
                evidence=location_evidence,
                structured_facts={"sourceType": "location", "regionDisplay": "Hoenn"},
                cache_dir=Path(temp_dir),
            )

        item_clues = [row["text"] for row in item_payload["response"]["crossword_candidates"]]
        location_clues = [row["text"] for row in location_payload["response"]["crossword_candidates"]]

        self.assertIn("Unlocks a hidden trait", item_clues)
        self.assertIn("Turns a standard trait rare", item_clues)
        self.assertIn("Hoenn shipwreck", location_clues)
        self.assertIn("Hides the Scanner", location_clues)

    def test_local_curator_generates_ability_surfaces_from_effect_text(self) -> None:
        ability_evidence = {
            "pageRevisionId": 3,
            "leadText": (
                "Battle Armor is an Ability introduced in Generation III. "
                "Moves are never critical hits against this Pokemon."
            ),
            "sections": [
                {
                    "title": "Description",
                    "text": "Blocks critical hits. The Pokemon is protected against critical hits.",
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            ability_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "BATTLEARMOR",
                    "answerDisplay": "BATTLE ARMOR",
                    "sourceType": "ability",
                    "sourceRef": "https://pokeapi.co/api/v2/ability/4/",
                },
                evidence=ability_evidence,
                structured_facts={"sourceType": "ability", "generationLabel": "Gen III"},
                cache_dir=Path(temp_dir),
            )

        ability_clues = [row["text"] for row in ability_payload["response"]["crossword_candidates"]]
        self.assertIn("Blocks critical hits", ability_clues)
        self.assertIn("Critical-hit proof trait", ability_clues)
        self.assertIn("No-crit armor trait", ability_clues)

    def test_local_curator_generates_family_item_and_mechanic_ability_surfaces(self) -> None:
        item_evidence = {
            "pageRevisionId": 4,
            "passMode": "second_pass",
            "leadText": "The Aguav Berry is a Berry introduced in Generation III.",
            "sections": [
                {
                    "title": "Description",
                    "text": (
                        "When held, it restores HP in a pinch. If the Pokemon dislikes the taste, it may become confused."
                    ),
                }
            ],
        }
        ability_evidence = {
            "pageRevisionId": 5,
            "passMode": "second_pass",
            "leadText": "Costar is an Ability introduced in Generation IX.",
            "sections": [
                {
                    "title": "Effect",
                    "text": "When the Pokemon enters battle, it copies an ally's stat changes."
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            berry_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "AGUAVBERRY",
                    "answerDisplay": "AGUAV BERRY",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/149/",
                },
                evidence=item_evidence,
                structured_facts={"sourceType": "item", "category": "berries"},
                cache_dir=Path(temp_dir),
            )
            costar_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "COSTAR",
                    "answerDisplay": "COSTAR",
                    "sourceType": "ability",
                    "sourceRef": "https://pokeapi.co/api/v2/ability/305/",
                },
                evidence=ability_evidence,
                structured_facts={"sourceType": "ability", "generationLabel": "Gen IX"},
                cache_dir=Path(temp_dir),
            )

        berry_clues = [row["text"] for row in berry_payload["response"]["crossword_candidates"]]
        ability_clues = [row["text"] for row in costar_payload["response"]["crossword_candidates"]]
        self.assertIn("Pinch-healing berry", berry_clues)
        self.assertIn("Berry that may confuse", berry_clues)
        self.assertIn("Copies an ally's stat changes", ability_clues)
        self.assertIn("Inherits teammate stat boosts", ability_clues)

    def test_local_curator_generates_move_item_and_location_specific_surfaces(self) -> None:
        move_evidence = {
            "pageRevisionId": 6,
            "leadText": "Embargo is a non-damaging Dark-type move introduced in Generation IV.",
            "sections": [
                {
                    "title": "Effect",
                    "text": "The target cannot use its held item for five turns."
                }
            ],
        }
        z_item_evidence = {
            "pageRevisionId": 7,
            "leadText": "Pikanium Z is a held item that allows Pikachu to upgrade Volt Tackle into Catastropika.",
            "sections": [],
        }
        tower_evidence = {
            "pageRevisionId": 8,
            "leadText": (
                "The Embedded Tower is an area located on Route 47 in Pokemon HeartGold and SoulSilver. "
                "It is where Groudon/Kyogre and Rayquaza rest."
            ),
            "pageTitle": "Embedded Tower",
            "sections": [],
        }
        house_evidence = {
            "pageRevisionId": 9,
            "leadText": (
                "Dr. Footstep lives on the southwest side of Route 213 in a small house on the beach. "
                "He gives the Footprint Ribbon to Trainers who have friendly Pokemon."
            ),
            "pageTitle": "Dr. Footstep",
            "sections": [],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            embargo_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "EMBARGO",
                    "answerDisplay": "EMBARGO",
                    "sourceType": "move",
                    "sourceRef": "https://pokeapi.co/api/v2/move/373/",
                },
                evidence=move_evidence,
                structured_facts={"sourceType": "move", "generationLabel": "Gen IV", "moveType": "Dark", "damageClass": "Status", "effect": "The target cannot use held items."},
                cache_dir=Path(temp_dir),
            )
            pikanium_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "PIKANIUMZHELD",
                    "answerDisplay": "PIKANIUM Z HELD",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/835/",
                },
                evidence=z_item_evidence,
                structured_facts={"sourceType": "item", "category": "z crystals", "effect": "Allows Pikachu to upgrade Volt Tackle into Catastropika."},
                cache_dir=Path(temp_dir),
            )
            tower_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "EMBEDDEDTOWER",
                    "answerDisplay": "EMBEDDED TOWER",
                    "sourceType": "location",
                    "sourceRef": "https://pokeapi.co/api/v2/location/248/",
                },
                evidence=tower_evidence,
                structured_facts={"sourceType": "location", "regionDisplay": "Johto"},
                cache_dir=Path(temp_dir),
            )
            house_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "FOOTSTEPHOUSE",
                    "answerDisplay": "FOOTSTEP HOUSE",
                    "sourceType": "location",
                    "sourceRef": "https://pokeapi.co/api/v2/location/189/",
                },
                evidence=house_evidence,
                structured_facts={"sourceType": "location", "regionDisplay": "Sinnoh"},
                cache_dir=Path(temp_dir),
            )

        embargo_clues = [row["text"] for row in embargo_payload["response"]["crossword_candidates"]]
        pikanium_clues = [row["text"] for row in pikanium_payload["response"]["crossword_candidates"]]
        tower_clues = [row["text"] for row in tower_payload["response"]["crossword_candidates"]]
        house_clues = [row["text"] for row in house_payload["response"]["crossword_candidates"]]

        self.assertIn("Target cannot use held items", embargo_clues)
        self.assertIn("Held-item-locking move", embargo_clues)
        self.assertIn("Pikachu-exclusive Z crystal", pikanium_clues)
        self.assertIn("Volt Tackle upgrade crystal", pikanium_clues)
        self.assertIn("Route 47 tower", tower_clues)
        self.assertIn("Tower where weather legends rest", tower_clues)
        self.assertIn("Route 213 beach house", house_clues)
        self.assertIn("Home of the Footprint Ribbon", house_clues)

    def test_local_curator_generates_item_family_specific_third_angles(self) -> None:
        belue_evidence = {
            "pageRevisionId": 10,
            "leadText": "A Belue Berry is a type of Berry introduced in Generation III.",
            "sections": [
                {
                    "title": "Effect",
                    "text": "Belue Berries can only be used for creating PokBlocks and Poffins."
                },
                {
                    "title": "Acquisition",
                    "text": "Belue Berries can be traded for exchange rewards."
                },
            ],
        }
        mint_evidence = {
            "pageRevisionId": 11,
            "leadText": "The Adamant Mint is an item introduced in Generation VIII. It changes the effect of a Pokemon's Nature.",
            "sections": [
                {
                    "title": "Effect",
                    "text": "If used from the Bag, it changes the effect of a Pokemon's Nature to that of the Adamant Nature, increasing its Attack stat and decreasing its Sp. Atk stat."
                }
            ],
        }
        blue_petal_evidence = {
            "pageRevisionId": 12,
            "leadText": "The Blue Petal is a Key Item introduced in Generation VII. It is one of the items the player collects during Mina's trial.",
            "sections": [
                {
                    "title": "Effect",
                    "text": "When all seven petals are collected, Mina will combine them and make a Rainbow Flower."
                },
                {
                    "title": "Description",
                    "text": "A pressed flower piece you receive from Lana during Mina's trial."
                },
            ],
        }
        light_ball_evidence = {
            "pageRevisionId": 13,
            "leadText": "The Light Ball is a held item introduced in Generation II. It boosts the stats of a Pikachu that holds it.",
            "sections": [
                {
                    "title": "Description",
                    "text": "An orb to be held by Pikachu. It raises the Attack and Sp. Atk of Pikachu."
                }
            ],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            belue_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "BELUEBERRY",
                    "answerDisplay": "BELUE BERRY",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/149/",
                },
                evidence=belue_evidence,
                structured_facts={"sourceType": "item", "category": "berries"},
                cache_dir=Path(temp_dir),
            )
            mint_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "ADAMANTMINT",
                    "answerDisplay": "ADAMANT MINT",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/1234/",
                },
                evidence=mint_evidence,
                structured_facts={"sourceType": "item", "category": "nature mints"},
                cache_dir=Path(temp_dir),
            )
            blue_petal_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "BLUEPETAL",
                    "answerDisplay": "BLUE PETAL",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/4321/",
                },
                evidence=blue_petal_evidence,
                structured_facts={"sourceType": "item", "category": "plot advancement", "effect": "XXX new effect for blue-petal"},
                cache_dir=Path(temp_dir),
            )
            light_ball_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "LIGHTBALL",
                    "answerDisplay": "LIGHT BALL",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/123/",
                },
                evidence=light_ball_evidence,
                structured_facts={"sourceType": "item", "category": "species specific item"},
                cache_dir=Path(temp_dir),
            )

        belue_clues = [row["text"] for row in belue_payload["response"]["crossword_candidates"]]
        mint_clues = [row["text"] for row in mint_payload["response"]["crossword_candidates"]]
        blue_petal_clues = [row["text"] for row in blue_petal_payload["response"]["crossword_candidates"]]
        light_ball_clues = [row["text"] for row in light_ball_payload["response"]["crossword_candidates"]]

        self.assertIn("Berry-blending ingredient", belue_clues)
        self.assertIn("Tradable exchange item", belue_clues)
        self.assertIn("Attack-up, Sp. Atk-down item", mint_clues)
        self.assertIn("Attack-favoring nature changer", mint_clues)
        self.assertIn("One of seven trial finds", blue_petal_clues)
        self.assertIn("Part of the Rainbow Flower", blue_petal_clues)
        self.assertIn("Power item for Pikachu", light_ball_clues)
        self.assertIn("Pikachu-only held item", light_ball_clues)

    def test_local_curator_uses_answer_corpus_detail_for_zero_clue_families(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            abra_candy_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "ABRACANDY",
                    "answerDisplay": "ABRA CANDY",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/1084/",
                    "clueText": "A candy that is packed with energy. When given to certain Pokemon, it will increase all their stats at once.",
                },
                evidence=None,
                structured_facts={"sourceType": "item", "category": "species candies item"},
                cache_dir=Path(temp_dir),
            )
            black_apricorn_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "BLACKAPRICORN",
                    "answerDisplay": "BLACK APRICORN",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/464/",
                    "clueText": "Used to make a Heavy Ball.",
                },
                evidence=None,
                structured_facts={"sourceType": "item", "category": "apricorn box item"},
                cache_dir=Path(temp_dir),
            )
            boost_mulch_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "BOOSTMULCH",
                    "answerDisplay": "BOOST MULCH",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/693/",
                    "clueText": "Causes soil to dry out in 4 hours.",
                },
                evidence=None,
                structured_facts={"sourceType": "item", "category": "field item"},
                cache_dir=Path(temp_dir),
            )
            dream_ball_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "DREAMBALL",
                    "answerDisplay": "DREAM BALL",
                    "sourceType": "item",
                    "sourceRef": "https://pokeapi.co/api/v2/item/617/",
                    "clueText": "Catches Pokemon found in the Dream World.",
                },
                evidence=None,
                structured_facts={"sourceType": "item", "category": "special balls item"},
                cache_dir=Path(temp_dir),
            )
            dark_void_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "DARKVOID",
                    "answerDisplay": "DARK VOID",
                    "sourceType": "move",
                    "sourceRef": "https://pokeapi.co/api/v2/move/464/",
                    "clueText": "Puts the target to sleep.",
                },
                evidence=None,
                structured_facts={"sourceType": "move", "generationLabel": "Gen IV", "moveType": "Dark", "damageClass": "Status"},
                cache_dir=Path(temp_dir),
            )
            sinnoh_villa_payload = curate_clues_locally(
                answer_row={
                    "answerKey": "SINNOHVILLA",
                    "answerDisplay": "SINNOH VILLA",
                    "sourceDisplayName": "Villa",
                    "sourceType": "location",
                    "sourceRef": "https://pokeapi.co/api/v2/location/221/",
                    "clueText": "Pokemon location in Sinnoh.",
                },
                evidence=None,
                structured_facts={"sourceType": "location", "regionDisplay": "Sinnoh"},
                cache_dir=Path(temp_dir),
            )

        abra_candy_clues = [row["text"] for row in abra_candy_payload["response"]["crossword_candidates"]]
        black_apricorn_clues = [row["text"] for row in black_apricorn_payload["response"]["crossword_candidates"]]
        boost_mulch_clues = [row["text"] for row in boost_mulch_payload["response"]["crossword_candidates"]]
        dream_ball_clues = [row["text"] for row in dream_ball_payload["response"]["crossword_candidates"]]
        dark_void_clues = [row["text"] for row in dark_void_payload["response"]["crossword_candidates"]]
        sinnoh_villa_clues = [row["text"] for row in sinnoh_villa_payload["response"]["crossword_candidates"]]

        self.assertIn("Packed-energy stat booster", abra_candy_clues)
        self.assertIn("Heavy Ball ingredient", black_apricorn_clues)
        self.assertIn("Dries soil in 4 hours", boost_mulch_clues)
        self.assertIn("Dream World catcher", dream_ball_clues)
        self.assertIn("Sleep-inducing move", dark_void_clues)
        self.assertIn("Regional villa", sinnoh_villa_clues)

    def test_score_candidate_allows_generic_location_kind_fragments(self) -> None:
        score, flags, approved = score_candidate(
            text="Regional mine",
            answer_display="GALAR MINE",
            evidence=None,
            evidence_ref="title",
            style="taxonomy",
            agent_confidence=0.8,
            mystery_score=0.5,
            specificity_score=0.7,
        )

        self.assertIn("answer_fragment_leak", flags)
        self.assertGreater(score, 0.0)
        self.assertTrue(approved)

    def test_build_clue_bank_merges_curated_fields_and_review_metadata(self) -> None:
        answer_rows = [
            {
                "answerKey": "STARAPTOR",
                "answerDisplay": "STARAPTOR",
                "sourceType": "pokemon-species",
                "sourceRef": "https://pokeapi.co/api/v2/pokemon-species/398/",
            }
        ]
        evidence = {
            "status": "ok",
            "pageTitle": "Staraptor (Pokemon)",
            "pageUrl": "https://bulbapedia.bulbagarden.net/wiki/Staraptor_(Pok%C3%A9mon)",
            "pageRevisionId": 12345,
            "leadText": "Staraptor is an intimidating Sinnoh bird Pokemon.",
            "sections": [
                {"title": "Biology", "text": "It leaves its flock and lives solitarily."},
                {"title": "Game data", "text": "It is known for high Attack and good Speed."},
            ],
        }
        curated = {
            "status": "ok",
            "schemaValid": True,
            "response": {
                "fact_nuggets": [
                    {"text": "Leaves its flock after evolving", "evidence_ref": "Biology", "specificity": 0.91},
                    {"text": "Known for high Attack and Speed", "evidence_ref": "Game data", "specificity": 0.82},
                ],
                "crossword_candidates": [
                    {
                        "text": "Sinnoh bird of prey",
                        "evidence_ref": "lead",
                        "mystery_score": 0.8,
                        "specificity_score": 0.7,
                        "style": "lore",
                    },
                    {
                        "text": "Gray-brown flock loner",
                        "evidence_ref": "Biology",
                        "mystery_score": 0.84,
                        "specificity_score": 0.86,
                        "style": "visual",
                    },
                    {
                        "text": "Staraptor with huge Attack",
                        "evidence_ref": "Game data",
                        "mystery_score": 0.4,
                        "specificity_score": 0.9,
                        "style": "stats",
                    },
                ],
                "cryptic_definition_seeds": ["intimidating raptor", "Sinnoh ace bird"],
                "connections_descriptors": ["Sinnoh flying species", "Intimidating birds"],
                "risk_flags": ["stat_specific"],
                "confidence": 0.88,
            },
        }

        entries, report = build_clue_bank(
            answer_rows,
            payload_index={},
            overrides={},
            evidence_by_answer={"STARAPTOR": evidence},
            curated_by_answer={"STARAPTOR": curated},
        )

        self.assertEqual(report["totalAnswers"], 1)
        self.assertEqual(report["approvedCoveragePct"], 0.0)
        entry = entries[0]
        self.assertEqual(entry["evidenceSource"]["pageUrl"], evidence["pageUrl"])
        self.assertEqual(len(entry["factNuggets"]), 2)
        self.assertEqual(entry["provenance"]["agentStatus"], "ok")
        self.assertEqual(entry["riskFlags"], ["stat_specific"])
        self.assertEqual(entry["crypticDefinitionSeeds"], ["intimidating raptor", "sinnoh ace bird"])
        self.assertEqual(sum(1 for row in entry["crosswordCandidates"] if row["approved"]), 2)
        self.assertIn("needs_more_crossword_clues", entry["qualityFlags"])

        override_rows = build_override_candidates(entries)
        self.assertEqual(len(override_rows), 1)
        self.assertEqual(override_rows[0]["evidence_page_url"], evidence["pageUrl"])
        self.assertEqual(override_rows[0]["approved_count"], "2")
        self.assertIn("answer_fragment_leak", override_rows[0]["rejected_reason_codes"])

    def test_editorial_seed_precedence_and_unresolved_audit(self) -> None:
        answer_rows = [
            {
                "answerKey": "AGUAVBERRY",
                "answerDisplay": "AGUAV BERRY",
                "sourceType": "item",
                "sourceRef": "https://pokeapi.co/api/v2/item/149/",
            },
            {
                "answerKey": "COSTAR",
                "answerDisplay": "COSTAR",
                "sourceType": "ability",
                "sourceRef": "https://pokeapi.co/api/v2/ability/305/",
            },
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            seeds_path = Path(temp_dir) / "seeds.json"
            seeds_path.write_text(
                (
                    '{"AGUAVBERRY":{"standard_clue_stems":["Pinch-healing berry","Berry that may confuse","Half-HP recovery berry"]}}'
                ),
                encoding="utf-8",
            )
            entries, _ = build_clue_bank(
                answer_rows,
                payload_index={},
                overrides={},
                editorial_seeds=load_editorial_seeds(seeds_path),
                evidence_by_answer={
                    "AGUAVBERRY": {"status": "ok", "pageUrl": "https://example.com/berry"},
                    "COSTAR": {"status": "ok", "pageUrl": "https://example.com/costar"},
                },
                curated_by_answer={
                    "COSTAR": {
                        "status": "ok",
                        "schemaValid": True,
                        "mode": "local",
                        "response": {
                            "fact_nuggets": [{"text": "Ally-copying trait", "evidence_ref": "title", "specificity": 0.62}],
                            "crossword_candidates": [{"text": "Gen IX ability", "evidence_ref": "lead", "mystery_score": 0.3, "specificity_score": 0.3}],
                            "cryptic_definition_seeds": [],
                            "connections_descriptors": [],
                            "risk_flags": [],
                            "confidence": 0.5,
                        },
                    }
                },
            )
        by_answer = {entry["answerKey"]: entry for entry in entries}
        berry_clues = [row["text"] for row in by_answer["AGUAVBERRY"]["standardClues"] if row["approved"]]
        self.assertIn("Pinch-healing berry", berry_clues)
        self.assertTrue(by_answer["AGUAVBERRY"]["provenance"]["editorialSeedApplied"])

        audit = build_unresolved_audit(entries)
        self.assertIn("title_only_abilities", audit["buckets"])
        self.assertIn("COSTAR", audit["buckets"]["title_only_abilities"]["representativeAnswers"])


if __name__ == "__main__":
    unittest.main()
