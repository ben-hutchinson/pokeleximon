from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")
TOKEN_RE = re.compile(r"[^A-Z0-9]")

VARIANT_PRIORITY = {
    "name": 0,
    "slug": 1,
    "part": 2,
}


def normalize_answer(value: str) -> str:
    return TOKEN_RE.sub("", str(value or "").upper())


def display_answer(record: dict[str, Any]) -> str:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        tokens = [str(part).strip().upper() for part in parts if str(part).strip()]
        if tokens:
            return " ".join(tokens)
    return str(record.get("word", "")).strip().upper()


def record_score(record: dict[str, Any]) -> tuple[int, int, int]:
    variant = str(record.get("variant", ""))
    parts = record.get("parts")
    part_count = len(parts) if isinstance(parts, list) else 1
    return (VARIANT_PRIORITY.get(variant, 99), part_count, len(str(record.get("word", ""))))


def parse_source_ref(source_ref: str) -> tuple[str | None, int | None]:
    match = SOURCE_REF_RE.search(str(source_ref or "").strip())
    if not match:
        return None, None
    source_type = match.group(1)
    try:
        source_id = int(match.group(2))
    except ValueError:
        return source_type, None
    return source_type, source_id


def load_payload_name_index(cache_dir: Path) -> dict[tuple[str, int], str]:
    index: dict[tuple[str, int], str] = {}
    for path in sorted(cache_dir.glob("*.json")):
        resource = path.name.split("_", 1)[0]
        if resource not in {"pokemon-species", "move", "item", "location", "location-area", "ability", "type"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        resource_id = payload.get("id")
        name = payload.get("name")
        if isinstance(resource_id, int) and isinstance(name, str) and name.strip():
            index[(resource, resource_id)] = name.strip()
    return index


def load_word_metadata(
    wordlist_path: Path,
    payload_name_index: dict[tuple[str, int], str] | None = None,
) -> dict[str, dict[str, Any]]:
    rows = json.loads(wordlist_path.read_text(encoding="utf-8"))
    best_by_answer: dict[str, dict[str, Any]] = {}

    for row in rows:
        if not isinstance(row, dict):
            continue
        answer_display = display_answer(row)
        if not answer_display:
            continue
        existing = best_by_answer.get(answer_display)
        if existing is None or record_score(row) < record_score(existing):
            best_by_answer[answer_display] = row

    metadata: dict[str, dict[str, Any]] = {}
    for answer_display, row in best_by_answer.items():
        metadata[normalize_answer(answer_display)] = build_answer_metadata(
            row,
            payload_name_index=payload_name_index,
        )
    return metadata


def build_answer_metadata(
    answer_row: dict[str, Any],
    *,
    payload_name_index: dict[tuple[str, int], str] | None = None,
) -> dict[str, Any]:
    source_type = str(answer_row.get("sourceType") or "").strip()
    source_ref = str(answer_row.get("sourceRef") or "").strip()
    parsed_type, source_id = parse_source_ref(source_ref)
    final_type = parsed_type or source_type
    canonical_slug = str(answer_row.get("sourceSlug") or "").strip()
    if not canonical_slug and parsed_type and isinstance(source_id, int) and payload_name_index:
        canonical_slug = str(payload_name_index.get((parsed_type, source_id)) or "").strip()
    return {
        "sourceType": final_type,
        "sourceRef": source_ref,
        "sourceId": source_id,
        "canonicalSlug": canonical_slug,
    }
