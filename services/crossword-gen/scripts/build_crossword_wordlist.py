from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
SOURCE_PATH = ROOT_DIR / "data" / "wordlist.json"
OUTPUT_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_REPORT_PATH = ROOT_DIR / "data" / "wordlist_crossword_report.json"

MIN_LEN = 4
MAX_LEN = 13
SOURCE_MAX_LEN = 13
TOKEN_RE = re.compile(r"[^A-Z0-9]")

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
    "ability": 2,
    "type": 3,
    "item": 4,
    "location": 5,
    "location-area": 6,
}

VARIANT_PRIORITY = {
    "name": 0,
    "slug": 1,
    "part": 2,
}
EXCLUDED_VARIANTS = {"part"}

LOCATION_SUFFIXES = {"CITY", "TOWN", "VILLAGE", "AREA"}
NOISY_ITEM_PREFIXES = {("DYNAMAX", "CRYSTAL")}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a crossword-oriented Pokemon-only wordlist")
    parser.add_argument("--weak-ratio", type=float, default=0.55)
    parser.add_argument("--weak-min-count", type=int, default=120)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


def _normalize_token(token: str) -> str:
    return TOKEN_RE.sub("", token.upper())


def _tokens_from_record(record: dict[str, Any]) -> list[str]:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        out = [_normalize_token(str(part)) for part in parts]
        return [token for token in out if token]

    word = record.get("word")
    if isinstance(word, str) and word:
        normalized = _normalize_token(word)
        return [normalized] if normalized else []

    return []


def _contains_digits(tokens: list[str]) -> bool:
    return any(any(ch.isdigit() for ch in token) for token in tokens)


def _canonicalize_record(record: dict[str, Any]) -> dict[str, Any] | None:
    source_type = str(record.get("sourceType", ""))
    if source_type not in ALLOWED_SOURCE_TYPES:
        return None

    source_ref = str(record.get("sourceRef", ""))
    if not source_ref:
        return None

    tokens = _tokens_from_record(record)
    if not tokens:
        return None

    normalization_rule = "identity"
    if source_type in {"location", "location-area"}:
        trimmed = list(tokens)
        while len(trimmed) > 1 and trimmed[-1] in LOCATION_SUFFIXES:
            trimmed.pop()
            normalization_rule = "drop_location_suffix"
        tokens = trimmed

    if source_type == "item" and len(tokens) >= 2:
        if (tokens[0], tokens[1]) in NOISY_ITEM_PREFIXES:
            return None

    if _contains_digits(tokens):
        return None

    answer = "".join(tokens)
    if len(answer) < MIN_LEN or len(answer) > SOURCE_MAX_LEN:
        return None
    if not any(ch.isalpha() for ch in answer):
        return None

    base_variant = str(record.get("variant", ""))
    if base_variant in EXCLUDED_VARIANTS:
        return None
    enumeration = ",".join(str(len(token)) for token in tokens) if len(tokens) > 1 else None

    return {
        "word": answer,
        "length": len(answer),
        "sourceType": source_type,
        "sourceRef": source_ref,
        "enum": enumeration,
        "parts": tokens,
        "normalizationRule": normalization_rule,
        "variant": base_variant,
    }


def _derive_long_variants(entry: dict[str, Any]) -> list[dict[str, Any]]:
    return [entry]


def _score_entry(entry: dict[str, Any]) -> tuple[int, int, int, int]:
    return (
        SOURCE_PRIORITY.get(str(entry.get("sourceType", "")), 99),
        len(entry.get("parts", [])),
        VARIANT_PRIORITY.get(str(entry.get("variant", "")), 99),
        len(str(entry.get("sourceRef", ""))),
    )


def _length_counts(rows: list[dict[str, Any]]) -> dict[int, int]:
    counts = Counter(int(row["length"]) for row in rows)
    return {length: counts.get(length, 0) for length in range(MIN_LEN, MAX_LEN + 1)}


def main() -> None:
    args = parse_args()
    if not SOURCE_PATH.exists():
        raise FileNotFoundError(f"Missing source wordlist: {SOURCE_PATH}")

    data = json.loads(SOURCE_PATH.read_text())
    canonicalized = [_canonicalize_record(item) for item in data]
    canonicalized = [item for item in canonicalized if item is not None]
    expanded: list[dict[str, Any]] = []
    for item in canonicalized:
        expanded.extend(_derive_long_variants(item))

    # Keep one canonical entry per answer key.
    best_by_word: dict[str, dict[str, Any]] = {}
    for item in expanded:
        word = str(item["word"])
        existing = best_by_word.get(word)
        if existing is None:
            best_by_word[word] = item
            continue
        if _score_entry(item) < _score_entry(existing):
            best_by_word[word] = item

    output = sorted(best_by_word.values(), key=lambda item: (int(item["length"]), str(item["word"])))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(output, indent=2))

    counts = _length_counts(output)
    median = sorted(counts.values())[len(counts) // 2] if counts else 0
    weak_cutoff = max(args.weak_min_count, int(round(median * args.weak_ratio)))
    weak_lengths = [length for length, count in counts.items() if count < weak_cutoff]

    report = {
        "sourcePath": str(SOURCE_PATH),
        "outputPath": str(OUTPUT_PATH),
        "totalWords": len(output),
        "allowedSourceTypes": sorted(ALLOWED_SOURCE_TYPES),
        "lengthCounts": counts,
        "weakLengthCutoff": weak_cutoff,
        "weakLengths": weak_lengths,
    }
    args.report_path.parent.mkdir(parents=True, exist_ok=True)
    args.report_path.write_text(json.dumps(report, indent=2))

    print(f"Wrote {OUTPUT_PATH} ({len(output)} words)")
    print(f"Length counts: {counts}")
    print(f"Weak lengths (cutoff<{weak_cutoff}): {weak_lengths}")
    print(f"Report: {args.report_path}")


if __name__ == "__main__":
    main()
