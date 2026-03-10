from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests


BASE_URL = "https://pokeapi.co/api/v2"
SOURCES = [
    "pokemon",
    "pokemon-species",
    "pokemon-form",
    "pokemon-color",
    "pokemon-habitat",
    "pokemon-shape",
    "egg-group",
    "growth-rate",
    "pokedex",
    "region",
    "move",
    "move-ailment",
    "move-battle-style",
    "move-category",
    "move-damage-class",
    "move-learn-method",
    "move-target",
    "ability",
    "type",
    "item",
    "item-attribute",
    "item-category",
    "item-fling-effect",
    "item-pocket",
    "location",
    "location-area",
    "pal-park-area",
    "berry",
    "berry-firmness",
    "berry-flavor",
    "stat",
    "nature",
    "encounter-method",
    "encounter-condition",
    "encounter-condition-value",
    "evolution-trigger",
    "gender",
    "generation",
    "growth-rate",
    "machine",
    "super-contest-effect",
    "contest-type",
    "contest-effect",
    "pokeathlon-stat",
    "characteristic",
    "language",
    "version",
    "version-group",
]

MIN_LEN = 4
MAX_LEN = 15
ALLOW_DIGITS = True
INCLUDE_DETAIL_NAMES = True
REQUEST_DELAY_SECONDS = 0.0

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "pokeapi"
OUTPUT_PATH = Path(__file__).resolve().parents[3] / "data" / "wordlist.json"

NAME_CLEAN_RE = re.compile(r"[^A-Z0-9]")
FILE_SAFE_RE = re.compile(r"[^A-Z0-9_-]")


@dataclass(frozen=True)
class WordEntry:
    word: str
    length: int
    source_type: str
    source_ref: str
    enum: str | None = None
    parts: list[str] | None = None
    variant: str | None = None


def normalize_name(name: str) -> str:
    upper = name.upper()
    cleaned = NAME_CLEAN_RE.sub("", upper)
    if not ALLOW_DIGITS:
        cleaned = "".join(ch for ch in cleaned if ch.isalpha())
    return cleaned


def tokenize_name(name: str) -> list[str]:
    # Split on hyphen/underscore/whitespace. Keep this in sync with cryptic normalizer behavior.
    tokens = re.split(r"[-_\s]+", name.strip())
    normalized = []
    for token in tokens:
        if not token:
            continue
        normalized.append(normalize_name(token))
    return [t for t in normalized if t]


def fetch_json(url: str, cache_path: Path) -> dict | None:
    if cache_path.exists():
        return json.loads(cache_path.read_text())

    try:
        resp = requests.get(
            url,
            timeout=30,
            headers={"User-Agent": "pokeleximon-wordlist/0.1 (+https://example.com)"},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException:
        return None

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(data))
    if REQUEST_DELAY_SECONDS:
        time.sleep(REQUEST_DELAY_SECONDS)
    return data


def list_endpoint(resource: str, limit: int = 200) -> Iterable[dict]:
    url = f"{BASE_URL}/{resource}?limit={limit}"
    cache_path = CACHE_DIR / f"{resource}_list.json"
    results: list[dict] = []

    while url:
        data = fetch_json(url, cache_path)
        if data is None:
            # If we have no cached data for this page, stop gracefully.
            break
        results.extend(data.get("results", []))
        url = data.get("next")
        if url:
            cache_path = CACHE_DIR / f"{resource}_page_{len(results)}.json"
    return results


def safe_filename(value: str) -> str:
    cleaned = FILE_SAFE_RE.sub("_", value.upper())
    return cleaned[:120] if cleaned else "UNKNOWN"


def fetch_detail(resource: str, item: dict) -> dict | None:
    url = item.get("url")
    if not url:
        return None
    name = item.get("name", "unknown")
    cache_path = CACHE_DIR / f"{resource}_{safe_filename(name)}.json"
    return fetch_json(url, cache_path)


def build_word_entries(sources: list[str]) -> list[WordEntry]:
    entries: list[WordEntry] = []
    for source in sources:
        for item in list_endpoint(source):
            raw_name = item.get("name", "")
            detail = fetch_detail(source, item) if INCLUDE_DETAIL_NAMES else None

            candidates: list[tuple[str, str]] = []
            if raw_name:
                candidates.append((raw_name, "slug"))
            if detail and isinstance(detail, dict):
                for name_entry in detail.get("names", []):
                    lang = name_entry.get("language", {}).get("name")
                    if lang != "en":
                        continue
                    name_value = name_entry.get("name", "")
                    if name_value:
                        candidates.append((name_value, "name"))

            for candidate, variant in candidates:
                normalized = normalize_name(candidate)
                if not normalized:
                    continue
                if not any(ch.isalpha() for ch in normalized):
                    continue
                if len(normalized) < MIN_LEN or len(normalized) > MAX_LEN:
                    continue
                parts = tokenize_name(candidate)
                enum = None
                if len(parts) > 1:
                    enum = ",".join(str(len(p)) for p in parts)
                entries.append(
                    WordEntry(
                        word=normalized,
                        length=len(normalized),
                        source_type=source,
                        source_ref=item.get("url", ""),
                        enum=enum,
                        parts=parts,
                        variant=variant,
                    )
                )
                for part in parts:
                    if len(part) >= MIN_LEN:
                        entries.append(
                            WordEntry(
                                word=part,
                                length=len(part),
                                source_type=source,
                                source_ref=item.get("url", ""),
                                enum=None,
                                parts=[part],
                                variant="part",
                            )
                        )
    return entries


def dedupe_entries(entries: list[WordEntry]) -> list[WordEntry]:
    seen: set[tuple[str, str]] = set()
    deduped: list[WordEntry] = []
    for entry in entries:
        key = (entry.word, entry.source_type)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(entry)
    return deduped


def write_output(entries: list[WordEntry]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "word": entry.word,
            "length": entry.length,
            "sourceType": entry.source_type,
            "sourceRef": entry.source_ref,
            "enum": entry.enum,
            "parts": entry.parts,
            "variant": entry.variant,
        }
        for entry in entries
    ]
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2))


def main() -> None:
    entries = build_word_entries(SOURCES)
    entries = dedupe_entries(entries)
    entries.sort(key=lambda e: (e.length, e.word))
    write_output(entries)
    print(f"Wrote {OUTPUT_PATH} ({len(entries)} words)")


if __name__ == "__main__":
    main()
