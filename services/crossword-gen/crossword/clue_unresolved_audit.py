from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


ITEM_BUCKETS = (
    ("berries", "family_extractor"),
    ("mints", "family_extractor"),
    ("fossils", "family_extractor"),
    ("plates_memories_drives_orbs", "family_extractor"),
    ("tera_materials_ores_collectibles", "family_extractor"),
    ("keys_plot_event_items", "family_extractor"),
)

ABILITY_BUCKETS = (
    ("thin_prose_abilities", "second_pass_bulbapedia"),
    ("title_only_abilities", "mechanic_normalizer"),
)


def _approved_count(entry: dict[str, Any]) -> int:
    return sum(1 for row in entry.get("standardClues", []) if bool(row.get("approved", False)))


def _source_type(entry: dict[str, Any]) -> str:
    return str(entry.get("sourceType") or "").strip().lower()


def _answer_display(entry: dict[str, Any]) -> str:
    return str(entry.get("answerDisplay") or "").strip().upper()


def _standard_texts(entry: dict[str, Any]) -> list[str]:
    return [str(row.get("text") or "").strip().lower() for row in entry.get("standardClues", []) if str(row.get("text") or "").strip()]


def _fact_nuggets(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [row for row in entry.get("factNuggets", []) if isinstance(row, dict)]


def _item_bucket(entry: dict[str, Any]) -> tuple[str, str]:
    answer = _answer_display(entry)
    texts = " ".join(_standard_texts(entry))
    if "BERRY" in answer or "berry" in texts:
        return ITEM_BUCKETS[0]
    if answer.endswith(" MINT") or "mint" in texts:
        return ITEM_BUCKETS[1]
    if answer.endswith(" FOSSIL") or "fossil" in texts:
        return ITEM_BUCKETS[2]
    if any(token in answer for token in (" PLATE", " MEMORY", " DRIVE", " ORB")):
        return ITEM_BUCKETS[3]
    if any(token in answer for token in (" SHARD", " MATERIAL", " ORE")) or any(token in texts for token in ("collectible", "tm material", "crafting", "ore")):
        return ITEM_BUCKETS[4]
    if any(token in answer for token in (" KEY", " PASS", " TICKET", " FLUTE", " CARD")) or any(token in texts for token in ("key item", "event item", "plot-critical", "story-progress")):
        return ITEM_BUCKETS[5]
    return ("misc_items", "editorial_seed")


def _ability_bucket(entry: dict[str, Any]) -> tuple[str, str]:
    facts = _fact_nuggets(entry)
    texts = _standard_texts(entry)
    title_only = any(str(row.get("evidenceRef") or "").strip().lower() == "title" for row in facts)
    if title_only:
        return ABILITY_BUCKETS[1]
    if len(facts) <= 1 or any(text.startswith("gen ") and text.endswith(" ability") for text in texts):
        return ABILITY_BUCKETS[0]
    return ("misc_abilities", "mechanic_normalizer")


def bucket_unresolved_entry(entry: dict[str, Any]) -> tuple[str, str]:
    source_type = _source_type(entry)
    if source_type == "item":
        return _item_bucket(entry)
    if source_type == "ability":
        return _ability_bucket(entry)
    if source_type == "pokemon-species":
        return ("species_long_tail", "editorial_seed")
    if source_type in {"location", "location-area"}:
        return ("location_long_tail", "second_pass_bulbapedia")
    if source_type == "move":
        return ("move_long_tail", "editorial_seed")
    return ("misc_long_tail", "editorial_seed")


def build_unresolved_audit(entries: list[dict[str, Any]]) -> dict[str, Any]:
    unresolved = [entry for entry in entries if _approved_count(entry) < 3]
    bucket_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    strategy_counts: Counter[str] = Counter()

    for entry in unresolved:
        bucket, strategy = bucket_unresolved_entry(entry)
        strategy_counts[strategy] += 1
        bucket_rows[bucket].append(
            {
                "answerKey": str(entry.get("answerKey") or ""),
                "answerDisplay": _answer_display(entry),
                "sourceType": _source_type(entry),
                "approvedCount": _approved_count(entry),
                "evidenceStatus": str(((entry.get("evidenceSource") or {}).get("status") or "")),
                "suggestedStrategy": strategy,
            }
        )

    buckets: dict[str, Any] = {}
    for bucket, rows in sorted(bucket_rows.items()):
        strategy = rows[0]["suggestedStrategy"] if rows else "editorial_seed"
        with_evidence = sum(1 for row in rows if row["evidenceStatus"] == "ok")
        without_evidence = len(rows) - with_evidence
        buckets[bucket] = {
            "count": len(rows),
            "suggestedStrategy": strategy,
            "representativeAnswers": [row["answerDisplay"] for row in rows[:12]],
            "withEvidence": with_evidence,
            "withoutEvidence": without_evidence,
            "answers": rows,
        }

    return {
        "totalUnresolved": len(unresolved),
        "strategies": dict(sorted(strategy_counts.items())),
        "buckets": buckets,
        "secondPassAnswerKeys": [
            row["answerKey"]
            for bucket in buckets.values()
            if bucket["suggestedStrategy"] in {"family_extractor", "mechanic_normalizer", "second_pass_bulbapedia"}
            for row in bucket["answers"]
        ],
        "editorialSeedAnswerKeys": [
            row["answerKey"]
            for bucket in buckets.values()
            if bucket["suggestedStrategy"] == "editorial_seed"
            for row in bucket["answers"]
        ],
    }
