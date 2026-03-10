from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import re
import time
from typing import Any, Callable
from urllib.parse import urlparse

import requests


POKEAPI_BASE = "https://pokeapi.co/api/v2"
FILE_SAFE_RE = re.compile(r"[^A-Z0-9_-]")
SOURCE_REF_RE = re.compile(r"/api/v2/([a-z0-9-]+)/([^/]+)/?$")
WHITESPACE_RE = re.compile(r"\s+")
TEMPLATE_VAR_RE = re.compile(r"\$[a-z_]+", flags=re.IGNORECASE)
TOKEN_CLEAN_RE = re.compile(r"[^A-Z0-9]")

CLUE_FALLBACK_BY_SOURCE: dict[str, str] = {
    "pokemon-species": "Pokemon species in the core games.",
    "ability": "Pokemon battle ability.",
    "move": "Pokemon battle move.",
    "item": "Pokemon item from the main series games.",
    "location": "Pokemon location in the game world.",
    "location-area": "Pokemon encounter area in the game world.",
    "berry": "Pokemon berry item.",
    "type": "Pokemon elemental type.",
}

VARIANT_PRIORITY = {
    "name": 0,
    "slug": 1,
    "part": 2,
}


@dataclass(frozen=True)
class ClueChoice:
    clue_text: str
    clue_rule: str


def _safe_filename(value: str) -> str:
    cleaned = FILE_SAFE_RE.sub("_", value.upper())
    return cleaned[:120] if cleaned else "UNKNOWN"


def _clean_text(value: str) -> str:
    normalized = value.replace("\n", " ").replace("\f", " ")
    normalized = TEMPLATE_VAR_RE.sub("X", normalized)
    normalized = WHITESPACE_RE.sub(" ", normalized).strip()
    return normalized


def _source_type_and_id(source_ref: str) -> tuple[str | None, str | None]:
    text = str(source_ref or "").strip()
    if not text:
        return None, None

    match = SOURCE_REF_RE.search(text)
    if match:
        return match.group(1), match.group(2)

    parsed = urlparse(text)
    path = parsed.path if parsed.path else text
    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) >= 2:
        if parts[0] == "api" and len(parts) >= 4 and parts[1] == "v2":
            return parts[2], parts[3]
        return parts[0], parts[1]
    return None, None


def _slug_to_display(slug: str) -> str:
    parts = [part for part in re.split(r"[-_]+", slug.strip()) if part]
    if not parts:
        return slug
    return " ".join(part.capitalize() for part in parts)


def _first_en_text(rows: list[Any], text_key: str) -> str | None:
    for item in rows:
        if not isinstance(item, dict):
            continue
        if item.get("language", {}).get("name") != "en":
            continue
        raw = item.get(text_key, "")
        if not isinstance(raw, str):
            continue
        cleaned = _clean_text(raw)
        if cleaned:
            return cleaned
    return None


def _english_name(detail: dict[str, Any] | None) -> str | None:
    if not detail:
        return None
    names = detail.get("names")
    if isinstance(names, list):
        for item in names:
            if not isinstance(item, dict):
                continue
            if item.get("language", {}).get("name") != "en":
                continue
            value = item.get("name", "")
            if isinstance(value, str):
                cleaned = _clean_text(value)
                if cleaned:
                    return cleaned
    return None


def _display_name(source_slug: str | None, detail: dict[str, Any] | None) -> str:
    name = _english_name(detail)
    if name:
        return name
    if source_slug:
        return _slug_to_display(source_slug)
    return "Pokemon term"


def _fallback_clue(source_type: str) -> ClueChoice:
    text = CLUE_FALLBACK_BY_SOURCE.get(source_type, "Pokemon term from PokeAPI data.")
    return ClueChoice(clue_text=text, clue_rule=f"{source_type}:fallback")


def _species_clue(detail: dict[str, Any]) -> ClueChoice | None:
    genera = detail.get("genera")
    if isinstance(genera, list):
        genus = _first_en_text(genera, "genus")
        if genus:
            genus = genus.replace("Pokémon", "Pokemon")
            return ClueChoice(clue_text=genus, clue_rule="species_genus")

    entries = detail.get("flavor_text_entries")
    if isinstance(entries, list):
        flavor = _first_en_text(entries, "flavor_text")
        if flavor:
            return ClueChoice(clue_text=flavor, clue_rule="species_flavor_text")
    return None


def _ability_clue(detail: dict[str, Any]) -> ClueChoice | None:
    effects = detail.get("effect_entries")
    if isinstance(effects, list):
        short = _first_en_text(effects, "short_effect")
        if short:
            return ClueChoice(clue_text=short, clue_rule="ability_short_effect")
        full = _first_en_text(effects, "effect")
        if full:
            return ClueChoice(clue_text=full, clue_rule="ability_effect")

    flavors = detail.get("flavor_text_entries")
    if isinstance(flavors, list):
        flavor = _first_en_text(flavors, "flavor_text")
        if flavor:
            return ClueChoice(clue_text=flavor, clue_rule="ability_flavor_text")
    return None


def _move_clue(detail: dict[str, Any]) -> ClueChoice | None:
    effects = detail.get("effect_entries")
    if isinstance(effects, list):
        short = _first_en_text(effects, "short_effect")
        if short:
            return ClueChoice(clue_text=short, clue_rule="move_short_effect")
        full = _first_en_text(effects, "effect")
        if full:
            return ClueChoice(clue_text=full, clue_rule="move_effect")

    flavors = detail.get("flavor_text_entries")
    if isinstance(flavors, list):
        flavor = _first_en_text(flavors, "flavor_text")
        if flavor:
            return ClueChoice(clue_text=flavor, clue_rule="move_flavor_text")
    return None


def _item_clue(detail: dict[str, Any]) -> ClueChoice | None:
    effects = detail.get("effect_entries")
    if isinstance(effects, list):
        short = _first_en_text(effects, "short_effect")
        if short:
            return ClueChoice(clue_text=short, clue_rule="item_short_effect")
        full = _first_en_text(effects, "effect")
        if full:
            return ClueChoice(clue_text=full, clue_rule="item_effect")

    flavors = detail.get("flavor_text_entries")
    if isinstance(flavors, list):
        flavor = _first_en_text(flavors, "text")
        if flavor:
            return ClueChoice(clue_text=flavor, clue_rule="item_flavor_text")
    return None


def _location_clue(detail: dict[str, Any], source_type: str) -> ClueChoice | None:
    region_name = None
    region = detail.get("region")
    if isinstance(region, dict):
        name = region.get("name")
        if isinstance(name, str) and name:
            region_name = _slug_to_display(name)

    if source_type == "location-area":
        location = detail.get("location")
        if isinstance(location, dict):
            raw = location.get("name")
            if isinstance(raw, str) and raw:
                label = _slug_to_display(raw)
                return ClueChoice(
                    clue_text=f"Pokemon encounter area in {label}.",
                    clue_rule="location_area_parent_location",
                )

    if region_name:
        return ClueChoice(
            clue_text=f"Pokemon location in {region_name}.",
            clue_rule="location_region_hint",
        )
    return None


def _berry_clue(detail: dict[str, Any]) -> ClueChoice | None:
    firmness = detail.get("firmness")
    if isinstance(firmness, dict):
        name = firmness.get("name")
        if isinstance(name, str) and name:
            label = _slug_to_display(name)
            return ClueChoice(
                clue_text=f"{label} berry from Pokemon games.",
                clue_rule="berry_firmness_hint",
            )
    return None


def select_clue(source_type: str, detail: dict[str, Any] | None) -> ClueChoice:
    if not detail:
        return _fallback_clue(source_type)

    chooser = {
        "pokemon-species": _species_clue,
        "ability": _ability_clue,
        "move": _move_clue,
        "item": _item_clue,
        "location": lambda payload: _location_clue(payload, "location"),
        "location-area": lambda payload: _location_clue(payload, "location-area"),
        "berry": _berry_clue,
    }.get(source_type)

    if chooser:
        picked = chooser(detail)
        if picked and picked.clue_text:
            return picked
    return _fallback_clue(source_type)


def build_slug_index(cache_dir: Path) -> dict[str, str]:
    slug_by_ref: dict[str, str] = {}
    for path in sorted(cache_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        results = payload.get("results")
        if not isinstance(results, list):
            continue
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            name = item.get("name")
            if isinstance(url, str) and isinstance(name, str) and url and name:
                slug_by_ref[url] = name
    return slug_by_ref


def _detail_cache_path(cache_dir: Path, source_type: str, source_slug: str) -> Path:
    return cache_dir / f"{source_type}_{_safe_filename(source_slug)}.json"


def _fetch_detail(source_ref: str, timeout_seconds: float) -> tuple[dict[str, Any] | None, str]:
    try:
        response = requests.get(
            source_ref,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-detail-corpus/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict):
            return payload, "ok"
        return None, "non_dict_json"
    except requests.Timeout:
        return None, "timeout"
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return None, f"http_{code}"
    except requests.ConnectionError:
        return None, "connection_error"
    except requests.RequestException:
        return None, "request_error"


def _tokenize_answer(value: str) -> list[str]:
    parts = re.split(r"[-_\s]+", value.strip())
    out: list[str] = []
    for part in parts:
        token = TOKEN_CLEAN_RE.sub("", part.upper())
        if token:
            out.append(token)
    return out


def _normalize_for_match(value: str) -> str:
    return TOKEN_CLEAN_RE.sub("", str(value or "").upper())


def _record_score(record: dict[str, Any]) -> tuple[int, int, int]:
    variant = str(record.get("variant", ""))
    parts = record.get("parts")
    if not isinstance(parts, list) or not parts:
        parts = _tokenize_answer(str(record.get("word", "")))
    return (
        VARIANT_PRIORITY.get(variant, 99),
        len(parts),
        len(str(record.get("word", ""))),
    )


def _answer_display(record: dict[str, Any]) -> str:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        cleaned: list[str] = []
        for item in parts:
            if not isinstance(item, str):
                continue
            text = _clean_text(item)
            if text:
                cleaned.append(text.upper())
        if cleaned:
            return " ".join(cleaned)
    word = str(record.get("word", "")).strip()
    return word.upper()


def build_word_metadata_index(wordlist_rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    best_by_word: dict[str, dict[str, Any]] = {}
    for row in wordlist_rows:
        word = str(row.get("word", "")).strip().upper()
        if not word:
            continue
        existing = best_by_word.get(word)
        if existing is None or _record_score(row) < _record_score(existing):
            best_by_word[word] = row

    metadata: dict[str, dict[str, str]] = {}
    for word, row in best_by_word.items():
        metadata[word] = {
            "sourceRef": str(row.get("sourceRef", "")),
            "sourceType": str(row.get("sourceType", "")),
            "displayAnswer": _answer_display(row),
        }
    return metadata


def build_detail_corpus(
    *,
    wordlist_rows: list[dict[str, Any]],
    cache_dir: Path,
    fetch_missing: bool = False,
    fetch_timeout_seconds: float = 20.0,
    request_delay_seconds: float = 0.0,
    max_fetch: int = 0,
    progress_every: int = 0,
    progress_callback: Callable[[str], None] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    slug_by_ref = build_slug_index(cache_dir)
    by_ref: dict[str, dict[str, Any]] = {}
    answers_by_ref: dict[str, set[str]] = defaultdict(set)

    for row in wordlist_rows:
        source_ref = str(row.get("sourceRef", "")).strip()
        source_type = str(row.get("sourceType", "")).strip()
        word = str(row.get("word", "")).strip().upper()
        if not source_ref or not source_type or not word:
            continue
        answers_by_ref[source_ref].add(word)
        existing = by_ref.get(source_ref)
        if existing is None or _record_score(row) < _record_score(existing):
            by_ref[source_ref] = row

    rows: list[dict[str, Any]] = []
    by_source_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    missing_refs: list[str] = []
    fetch_attempts = 0
    fetch_successes = 0
    fetch_failures = 0
    fetch_skipped_by_limit = 0
    fetch_candidates_processed = 0
    fetch_error_counts: dict[str, int] = defaultdict(int)
    total_refs = len(by_ref)
    missing_fetch_candidates = 0
    if fetch_missing:
        for source_ref in sorted(by_ref):
            row = by_ref[source_ref]
            source_type = str(row.get("sourceType", "")).strip()
            parsed_source_type, _ = _source_type_and_id(source_ref)
            if parsed_source_type:
                source_type = parsed_source_type
            source_slug = slug_by_ref.get(source_ref)
            if not source_slug:
                missing_fetch_candidates += 1
                continue
            detail_path = _detail_cache_path(cache_dir, source_type, source_slug)
            if not detail_path.exists():
                missing_fetch_candidates += 1

    for idx, source_ref in enumerate(sorted(by_ref), start=1):
        canonical = by_ref[source_ref]
        source_type = str(canonical.get("sourceType", "")).strip()
        parsed_source_type, _ = _source_type_and_id(source_ref)
        if parsed_source_type:
            source_type = parsed_source_type

        source_slug = slug_by_ref.get(source_ref)
        detail = None
        detail_path = None
        if source_slug:
            detail_path = _detail_cache_path(cache_dir, source_type, source_slug)
            if detail_path.exists():
                detail = json.loads(detail_path.read_text())
        if detail is None and fetch_missing:
            fetch_candidates_processed += 1
            if max_fetch > 0 and fetch_attempts >= max_fetch:
                fetch_skipped_by_limit += 1
            else:
                fetch_attempts += 1
                fetched, fetch_status = _fetch_detail(source_ref, timeout_seconds=fetch_timeout_seconds)
                if fetched is not None:
                    detail = fetched
                    fetch_successes += 1
                    if source_slug and detail_path:
                        detail_path.parent.mkdir(parents=True, exist_ok=True)
                        detail_path.write_text(json.dumps(detail))
                    if request_delay_seconds > 0:
                        time.sleep(request_delay_seconds)
                else:
                    fetch_failures += 1
                    fetch_error_counts[fetch_status] += 1

        clue = select_clue(source_type, detail if isinstance(detail, dict) else None)
        display_name = _display_name(source_slug, detail if isinstance(detail, dict) else None)
        answer_words = sorted(answers_by_ref[source_ref])

        if not source_slug:
            missing_refs.append(source_ref)

        row = {
            "sourceRef": source_ref,
            "sourceType": source_type,
            "sourceSlug": source_slug,
            "displayName": display_name,
            "clueText": clue.clue_text,
            "clueRule": clue.clue_rule,
            "hasDetail": isinstance(detail, dict),
            "answerCount": len(answer_words),
            "sampleAnswers": answer_words[:8],
        }
        rows.append(row)

        by_source_counts[source_type]["total"] += 1
        if row["hasDetail"]:
            by_source_counts[source_type]["withDetail"] += 1
        if row["clueText"]:
            by_source_counts[source_type]["withClue"] += 1

        if progress_callback is not None and progress_every > 0:
            if fetch_missing:
                if fetch_candidates_processed and (
                    fetch_candidates_processed % progress_every == 0
                    or fetch_candidates_processed == missing_fetch_candidates
                ):
                    progress_callback(
                        (
                            f"fetchProcessed={fetch_candidates_processed}/{missing_fetch_candidates} "
                            f"fetchAttempts={fetch_attempts} fetchSuccesses={fetch_successes} "
                            f"fetchFailures={fetch_failures} skippedByLimit={fetch_skipped_by_limit}"
                        )
                    )
            elif idx % progress_every == 0 or idx == total_refs:
                progress_callback(f"processed={idx}/{total_refs}")

    report = {
        "totalSourceRefs": len(rows),
        "withDetail": sum(1 for row in rows if row["hasDetail"]),
        "withClue": sum(1 for row in rows if row["clueText"]),
        "fetchMissingEnabled": fetch_missing,
        "missingFetchCandidates": missing_fetch_candidates,
        "fetchAttempts": fetch_attempts,
        "fetchSuccesses": fetch_successes,
        "fetchFailures": fetch_failures,
        "fetchSkippedByLimit": fetch_skipped_by_limit,
        "fetchErrorCounts": {key: int(value) for key, value in sorted(fetch_error_counts.items())},
        "missingSlugRefs": len(missing_refs),
        "missingSlugRefSample": missing_refs[:20],
        "bySourceType": {
            source: {
                "total": int(counts.get("total", 0)),
                "withDetail": int(counts.get("withDetail", 0)),
                "withClue": int(counts.get("withClue", 0)),
            }
            for source, counts in sorted(by_source_counts.items())
        },
    }
    return rows, report


def load_detail_corpus_index(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    rows = json.loads(path.read_text())
    index: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        source_ref = str(row.get("sourceRef", "")).strip()
        if source_ref:
            index[source_ref] = row
    return index


def clue_for_answer(
    *,
    answer: str,
    word_metadata_by_word: dict[str, dict[str, str]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
) -> tuple[str, str | None]:
    key = str(answer or "").strip().upper()
    if not key:
        return "Pokemon term from PokeAPI data.", None

    metadata = word_metadata_by_word.get(key)
    if not metadata:
        return "Pokemon term from PokeAPI data.", None

    source_ref = metadata.get("sourceRef") or None
    source_type = metadata.get("sourceType", "")
    if source_ref:
        detail_row = detail_corpus_by_ref.get(source_ref)
        if detail_row:
            clue = _clean_text(str(detail_row.get("clueText", "")))
            if clue:
                answer_norm = _normalize_for_match(key)
                clue_norm = _normalize_for_match(clue)
                if clue_norm and answer_norm and answer_norm not in clue_norm:
                    return clue, source_ref

    fallback = _fallback_clue(source_type).clue_text
    return fallback, source_ref


def build_answer_corpus(
    *,
    wordlist_rows: list[dict[str, Any]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    best_by_answer: dict[str, dict[str, Any]] = {}
    for row in wordlist_rows:
        answer = str(row.get("word", "")).strip().upper()
        if not answer:
            continue
        existing = best_by_answer.get(answer)
        if existing is None or _record_score(row) < _record_score(existing):
            best_by_answer[answer] = row

    rows: list[dict[str, Any]] = []
    by_source = Counter()
    by_variant = Counter()
    with_detail = 0
    with_clue = 0

    for answer in sorted(best_by_answer):
        row = best_by_answer[answer]
        source_ref = str(row.get("sourceRef", "")).strip()
        source_type = str(row.get("sourceType", "")).strip()
        detail_row = detail_corpus_by_ref.get(source_ref, {})

        clue_text = ""
        clue_rule = ""
        if isinstance(detail_row, dict):
            clue_text = _clean_text(str(detail_row.get("clueText", "")))
            clue_rule = str(detail_row.get("clueRule", ""))

        answer_norm = _normalize_for_match(answer)
        clue_norm = _normalize_for_match(clue_text)
        if not clue_text or not clue_norm or (answer_norm and answer_norm in clue_norm):
            fallback = _fallback_clue(source_type)
            clue_text = fallback.clue_text
            clue_rule = fallback.clue_rule

        has_detail = bool(isinstance(detail_row, dict) and detail_row.get("hasDetail"))
        if has_detail:
            with_detail += 1
        if clue_text:
            with_clue += 1

        variant = str(row.get("variant", ""))
        by_source[source_type] += 1
        by_variant[variant] += 1

        parts = row.get("parts")
        if not isinstance(parts, list):
            parts = _tokenize_answer(answer)

        rows.append(
            {
                "answerKey": answer,
                "answerDisplay": _answer_display(row),
                "length": int(row.get("length", len(answer))),
                "sourceRef": source_ref,
                "sourceType": source_type,
                "sourceSlug": detail_row.get("sourceSlug") if isinstance(detail_row, dict) else None,
                "sourceDisplayName": detail_row.get("displayName") if isinstance(detail_row, dict) else None,
                "clueText": clue_text,
                "clueRule": clue_rule,
                "hasDetail": has_detail,
                "enum": row.get("enum"),
                "parts": parts,
                "variant": variant,
                "normalizationRule": str(row.get("normalizationRule", "")),
            }
        )

    report = {
        "totalAnswers": len(rows),
        "withDetail": with_detail,
        "withClue": with_clue,
        "bySourceType": {
            source: {
                "total": count,
                "withDetail": sum(
                    1
                    for row in rows
                    if row["sourceType"] == source and bool(row.get("hasDetail"))
                ),
            }
            for source, count in sorted(by_source.items())
        },
        "byVariant": {variant: int(count) for variant, count in sorted(by_variant.items())},
    }
    return rows, report
