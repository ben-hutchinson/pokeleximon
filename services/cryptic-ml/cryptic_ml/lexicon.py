from __future__ import annotations

import json
from pathlib import Path

from cryptic_ml.models import LexiconEntry
from cryptic_ml.normalizer import canonicalize

ALLOWED_SOURCE_TYPES = {
    "pokemon-species",
    "move",
    "item",
    "location",
    "location-area",
    "ability",
    "type",
}

SOURCE_PRIORITY = {
    "pokemon-species": 0,
    "move": 1,
    "item": 2,
    "location": 3,
    "location-area": 4,
    "ability": 5,
    "type": 6,
}


def load_wordlist(path: Path) -> list[dict]:
    return json.loads(path.read_text())


def build_slug_index(pokeapi_cache_dir: Path) -> dict[str, str]:
    slug_by_ref: dict[str, str] = {}
    for path in sorted(pokeapi_cache_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        results = payload.get("results")
        if not isinstance(results, list):
            continue
        for item in results:
            url = item.get("url")
            name = item.get("name")
            if not isinstance(url, str) or not isinstance(name, str):
                continue
            slug_by_ref[url] = name
    return slug_by_ref


def _score_candidate(entry: LexiconEntry) -> tuple[int, int, int]:
    return (
        SOURCE_PRIORITY.get(entry.source_type, 99),
        len(entry.answer_tokens),
        len(entry.answer_key),
    )


def _fallback_slug(record: dict) -> str | None:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        return "-".join(p.lower() for p in parts if isinstance(p, str) and p)

    word = record.get("word")
    if isinstance(word, str) and word:
        return word.lower()

    return None


def build_lexicon(wordlist_path: Path, pokeapi_cache_dir: Path) -> list[LexiconEntry]:
    wordlist = load_wordlist(wordlist_path)
    slug_index = build_slug_index(pokeapi_cache_dir)

    best_by_answer: dict[str, LexiconEntry] = {}

    for record in wordlist:
        source_type = record.get("sourceType")
        if source_type not in ALLOWED_SOURCE_TYPES:
            continue

        source_ref = record.get("sourceRef")
        if not isinstance(source_ref, str) or not source_ref:
            continue

        source_slug = slug_index.get(source_ref) or _fallback_slug(record)
        if not source_slug:
            continue

        canonical = canonicalize(source_type=source_type, source_slug=source_slug)
        if not canonical:
            continue

        candidate = LexiconEntry(
            answer=canonical.answer,
            answer_key=canonical.answer_key,
            enumeration=canonical.enumeration,
            answer_tokens=canonical.answer_tokens,
            source_type=source_type,
            source_ref=source_ref,
            source_slug=source_slug,
            normalization_rule=canonical.normalization_rule,
            is_multiword=len(canonical.answer_tokens) > 1,
            metadata={
                "variant": str(record.get("variant", "")),
            },
        )

        existing = best_by_answer.get(candidate.answer_key)
        if not existing or _score_candidate(candidate) < _score_candidate(existing):
            best_by_answer[candidate.answer_key] = candidate

    entries = sorted(best_by_answer.values(), key=lambda e: (len(e.answer_key), e.answer))
    return entries


def write_lexicon(path: Path, entries: list[LexiconEntry]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "answer": e.answer,
            "answerKey": e.answer_key,
            "enumeration": e.enumeration,
            "answerTokens": list(e.answer_tokens),
            "sourceType": e.source_type,
            "sourceRef": e.source_ref,
            "sourceSlug": e.source_slug,
            "normalizationRule": e.normalization_rule,
            "isMultiword": e.is_multiword,
            "metadata": e.metadata,
        }
        for e in entries
    ]
    path.write_text(json.dumps(payload, indent=2))
