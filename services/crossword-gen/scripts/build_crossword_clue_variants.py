from __future__ import annotations

import argparse
import csv
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
DEFAULT_OUTPUT_CSV = DEFAULT_INPUT_CSV
DEFAULT_WORDLIST_JSON = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_VARIANT_CACHE_JSON = ROOT_DIR / "data" / "crossword_external_variant_cache.json"
DEFAULT_LEGACY_CACHE_JSON = ROOT_DIR / "data" / "crossword_external_clue_cache.json"

MEDIAWIKI_API_URL = "https://bulbapedia.bulbagarden.net/w/api.php"
TOKEN_RE = re.compile(r"[^A-Z0-9]")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")
JAPANESE_PAREN_RE = re.compile(r"\([^)]*\bJapanese:\s*[^)]*\)", re.IGNORECASE)
JAPANESE_LABEL_RE = re.compile(r"(?i)\bJapanese:\s*[^.;:!?)]*")
POKEAPI_REF_RE = re.compile(r"(?i)\bPok[eé]?API\b[^.;:!?)]*")

SOURCE_REPLACEMENT = {
    "pokemon-species": "this Pokemon",
    "move": "this move",
    "ability": "this ability",
    "item": "this item",
    "location": "this location",
    "location-area": "this location",
    "type": "this type",
}

LOW_QUALITY_PATTERNS = (
    re.compile(r"(?i)redirects here"),
    re.compile(r"(?i)this article is about"),
    re.compile(r"(?i)may refer to"),
    re.compile(r"(?i)disambiguation"),
    re.compile(r"(?i)^for the"),
    re.compile(r"(?i)if you were looking for"),
    re.compile(r"(?i)for a list of"),
    re.compile(r"(?i)has several referrals"),
)

GENERIC_CLUE_PATTERNS = (
    re.compile(r"(?i)^location:\s*region\s"),
    re.compile(r"(?i)^type entry"),
    re.compile(r"(?i)^ability entry"),
    re.compile(r"(?i)^location entry"),
    re.compile(r"(?i)^.* item \(.*#\d+\)\.?$"),
    re.compile(r"(?i)^pok[eé]mon term from the csv lexicon\.?$"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
)

VARIANT_PRIORITY = {
    "name": 0,
    "slug": 1,
    "part": 2,
}

MOJIBAKE_REPLACEMENTS = {
    "Pok√©mon": "Pokémon",
    "PokÃ©mon": "Pokémon",
    "‚Äô": "’",
    "‚Äú": "“",
    "‚Äù": "”",
    "‚Äì": "–",
    "‚Äî": "—",
    "Ã—": "×",
    "√ó": "ó",
    "√©": "é",
}


def _clean_text(value: str) -> str:
    text = str(value).replace("\n", " ").replace("\f", " ")
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = re.sub(r"(?i)pok[ée]mon", "Pokémon", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def _as_sentence(value: str) -> str:
    text = _clean_text(value)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def _normalize_answer(value: str) -> str:
    return TOKEN_RE.sub("", str(value).upper())


def _source_label(source_type: str) -> str:
    mapping = {
        "pokemon-species": "species",
        "move": "move",
        "ability": "ability",
        "item": "item",
        "location": "location",
        "location-area": "location area",
        "type": "type",
    }
    return mapping.get(str(source_type or "").strip().lower(), "entry")


def _safe_source_label_for_answer(source_type: str, display_answer: str) -> str:
    label = _source_label(source_type)
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(label):
            return "entry"
    return label


def _answer_parts(display_answer: str) -> list[str]:
    return [part for part in str(display_answer).upper().split(" ") if part]


def _answer_fragments(display_answer: str) -> list[str]:
    parts = _answer_parts(display_answer)
    fragments: set[str] = set()
    for part in parts:
        if len(part) >= 2:
            fragments.add(part)
    joined = "".join(parts)
    spaced = " ".join(parts)
    hyphened = "-".join(parts)
    for value in (joined, spaced, hyphened):
        if len(value.replace(" ", "").replace("-", "")) >= 2:
            fragments.add(value)
    return sorted(fragments, key=len, reverse=True)


def _answer_lengths_signature(display_answer: str) -> str:
    parts = _answer_parts(display_answer)
    if not parts:
        return "0"
    return ",".join(str(len(part)) for part in parts)


def _answer_initials(display_answer: str) -> str:
    parts = _answer_parts(display_answer)
    return "".join(part[0] for part in parts if part) or "N/A"


def _answer_endings(display_answer: str) -> str:
    parts = _answer_parts(display_answer)
    return "".join(part[-1] for part in parts if part) or "N/A"


def _total_letters(display_answer: str) -> int:
    return sum(len(part) for part in _answer_parts(display_answer))


def _vowel_consonant_counts(display_answer: str) -> tuple[int, int]:
    token = "".join(_answer_parts(display_answer))
    vowels = sum(1 for char in token if char in {"A", "E", "I", "O", "U"})
    consonants = max(len(token) - vowels, 0)
    return vowels, consonants


def _derive_structural_fallback_variants(
    *,
    answer_norm: str,
    display_answer: str,
    source_type: str,
) -> list[str]:
    parts = _answer_parts(display_answer)
    word_count = max(len(parts), 1)
    lengths = _answer_lengths_signature(display_answer)
    initials = _answer_initials(display_answer)
    endings = _answer_endings(display_answer)
    letters_total = _total_letters(display_answer)
    vowels, consonants = _vowel_consonant_counts(display_answer)
    source_label = _safe_source_label_for_answer(source_type, display_answer)

    return [
        _as_sentence(
            f"Core-series Pokémon {source_label}; answer uses {word_count} word{'s' if word_count != 1 else ''} with lengths {lengths}",
        ),
        _as_sentence(
            f"Pokémon {source_label} clue with initials {initials} and {letters_total} total letters",
        ),
        _as_sentence(
            f"Pokémon {source_label} clue: ending letters {endings}; vowels {vowels}, consonants {consonants}",
        ),
        _as_sentence(
            f"Pokémon {source_label} entry with enumeration {lengths}",
        ),
        _as_sentence(
            f"Pokémon {source_label} clue with {word_count} words and {letters_total} letters",
        ),
    ]


def _clue_key(clue: str) -> str:
    return WHITESPACE_RE.sub(" ", str(clue).strip()).upper()


def _is_low_quality_clue(clue: str) -> bool:
    text = _clean_text(clue)
    if not text:
        return True
    if len(text) < 24:
        return True
    return any(pattern.search(text) for pattern in LOW_QUALITY_PATTERNS)


def _is_generic_clue(clue: str) -> bool:
    text = _clean_text(clue)
    if not text:
        return True
    return any(pattern.search(text) for pattern in GENERIC_CLUE_PATTERNS)


def _clue_contains_answer_fragment(clue: str, display_answer: str) -> bool:
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            return True
    return False


def _strip_answer_fragments(clue: str, display_answer: str, source_type: str) -> str:
    out = clue
    replacement = SOURCE_REPLACEMENT.get(source_type, "this entry")
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return _as_sentence(out)


def _parse_source_ref(source_ref: str) -> tuple[str | None, int | None]:
    match = SOURCE_REF_RE.search(str(source_ref).strip())
    if not match:
        return None, None
    source_type = match.group(1)
    try:
        source_id = int(match.group(2))
    except ValueError:
        return source_type, None
    return source_type, source_id


def _strip_disallowed_metadata(clue: str) -> str:
    out = _clean_text(clue)
    if not out:
        return ""
    out = JAPANESE_PAREN_RE.sub("", out)
    out = JAPANESE_LABEL_RE.sub("", out)
    out = POKEAPI_REF_RE.sub("", out)
    out = re.sub(r"\([^)]*\)", "", out)
    out = re.sub(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", "", out)
    out = out.replace("(", "").replace(")", "")
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"\s*-\s*", " ", out)
    out = out.strip(" ;,")
    return _as_sentence(out)


def _display_answer(record: dict[str, Any]) -> str:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        tokens = [str(part).strip().upper() for part in parts if str(part).strip()]
        if tokens:
            return " ".join(tokens)
    return str(record.get("word", "")).strip().upper()


def _record_score(record: dict[str, Any]) -> tuple[int, int, int]:
    variant = str(record.get("variant", ""))
    parts = record.get("parts")
    part_count = len(parts) if isinstance(parts, list) else 1
    return (VARIANT_PRIORITY.get(variant, 99), part_count, len(str(record.get("word", ""))))


def _load_word_metadata(wordlist_path: Path) -> dict[str, dict[str, Any]]:
    rows = json.loads(wordlist_path.read_text(encoding="utf-8"))
    best_by_answer: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        answer_display = _display_answer(row)
        if not answer_display:
            continue
        existing = best_by_answer.get(answer_display)
        if existing is None or _record_score(row) < _record_score(existing):
            best_by_answer[answer_display] = row

    metadata: dict[str, dict[str, Any]] = {}
    for answer_display, row in best_by_answer.items():
        source_type = str(row.get("sourceType") or "").strip()
        source_ref = str(row.get("sourceRef") or "").strip()
        parsed_type, source_id = _parse_source_ref(source_ref)
        final_type = parsed_type or source_type
        canonical_slug = str(row.get("sourceSlug") or "").strip()
        metadata[_normalize_answer(answer_display)] = {
            "sourceType": final_type,
            "sourceRef": source_ref,
            "sourceId": source_id,
            "canonicalSlug": canonical_slug,
        }
    return metadata


def _slug_to_title_space(slug: str) -> str:
    return " ".join(part.capitalize() for part in str(slug).replace("_", "-").split("-") if part)


def _slug_to_title_hyphen(slug: str) -> str:
    return "-".join(part.capitalize() for part in str(slug).replace("_", "-").split("-") if part)


def _to_title(answer_display: str) -> str:
    return " ".join(part.capitalize() for part in str(answer_display).split() if part)


def _bulbapedia_title_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    base_answer = _to_title(answer_display)
    slug_space = _slug_to_title_space(canonical_slug or "")
    slug_hyphen = _slug_to_title_hyphen(canonical_slug or "")
    candidates: list[str] = []

    for base in (slug_hyphen, slug_space, base_answer):
        if base:
            candidates.append(base)

    base = slug_hyphen or slug_space or base_answer
    if base:
        if source_type == "pokemon-species":
            candidates.extend([f"{base} (Pokemon)", f"{base} (species)"])
        elif source_type == "move":
            candidates.extend([f"{base} (move)"])
        elif source_type == "ability":
            candidates.extend([f"{base} (Ability)", f"{base} (ability)"])
        elif source_type == "item":
            candidates.extend([f"{base} (item)"])
        elif source_type in {"location", "location-area"}:
            candidates.extend([f"{base} (location)"])
        elif source_type == "type":
            candidates.extend([f"{base} (type)", f"{base} type"])

    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        cleaned = _clean_text(candidate)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _extract_candidate_sentences(extract: str, max_sentences: int = 5) -> list[str]:
    text = _clean_text(extract)
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for sentence in SENTENCE_SPLIT_RE.split(text):
        cleaned = _as_sentence(sentence)
        key = _clue_key(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= max_sentences:
            break
    return out


def _sanitize_external_candidate(candidate: str, answer_display: str, source_type: str) -> str | None:
    cleaned = _strip_answer_fragments(candidate, answer_display, source_type)
    cleaned = _strip_disallowed_metadata(cleaned)
    if _is_low_quality_clue(cleaned):
        return None
    if _is_generic_clue(cleaned):
        return None
    if _clue_contains_answer_fragment(cleaned, answer_display):
        return None
    return cleaned


@dataclass
class FetchResult:
    status: str
    extract: str | None = None


def _fetch_bulbapedia_extract(title: str, timeout_seconds: float) -> FetchResult:
    params = {
        "action": "query",
        "format": "json",
        "prop": "extracts",
        "exintro": "1",
        "explaintext": "1",
        "redirects": "1",
        "titles": title,
    }
    try:
        response = requests.get(
            MEDIAWIKI_API_URL,
            params=params,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-clue-variants/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return FetchResult(status="timeout")
    except requests.ConnectionError:
        return FetchResult(status="connection_error")
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return FetchResult(status=f"http_{code}")
    except requests.RequestException:
        return FetchResult(status="request_error")
    except ValueError:
        return FetchResult(status="json_error")

    query = payload.get("query") if isinstance(payload, dict) else None
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, dict):
        return FetchResult(status="bad_payload")

    for page in pages.values():
        if not isinstance(page, dict):
            continue
        if "missing" in page:
            continue
        extract = page.get("extract")
        if isinstance(extract, str) and extract.strip():
            return FetchResult(status="ok", extract=extract)
    return FetchResult(status="not_found")


def _fetch_serebii_description(url: str, timeout_seconds: float) -> FetchResult:
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-clue-variants/0.1"},
        )
        response.raise_for_status()
        html = response.text
    except requests.Timeout:
        return FetchResult(status="timeout")
    except requests.ConnectionError:
        return FetchResult(status="connection_error")
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return FetchResult(status=f"http_{code}")
    except requests.RequestException:
        return FetchResult(status="request_error")

    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if meta_match:
        return FetchResult(status="ok", extract=meta_match.group(1))

    p_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    if p_match:
        text = re.sub(r"<[^>]+>", " ", p_match.group(1))
        text = _clean_text(text)
        if text:
            return FetchResult(status="ok", extract=text)
    return FetchResult(status="not_found")


def _serebii_url_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    slug = str(canonical_slug or "").strip().lower().replace(" ", "-")
    if not slug:
        slug = "-".join(part.lower() for part in answer_display.split())

    urls: list[str] = []
    if source_type == "move":
        urls.append(f"https://www.serebii.net/attackdex-sv/{slug}.shtml")
    elif source_type == "ability":
        urls.append(f"https://www.serebii.net/abilitydex/{slug}.shtml")
    elif source_type == "item":
        urls.append(f"https://www.serebii.net/itemdex/{slug}.shtml")
    elif source_type == "pokemon-species":
        urls.append(f"https://www.serebii.net/pokedex-sv/{slug}.shtml")
    else:
        urls.append(f"https://www.serebii.net/search.shtml?query={slug}")
    return urls


def _fetch_pokemondb_description(url: str, timeout_seconds: float) -> FetchResult:
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-clue-variants/0.1"},
        )
        response.raise_for_status()
        html = response.text
    except requests.Timeout:
        return FetchResult(status="timeout")
    except requests.ConnectionError:
        return FetchResult(status="connection_error")
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return FetchResult(status=f"http_{code}")
    except requests.RequestException:
        return FetchResult(status="request_error")

    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if meta_match:
        return FetchResult(status="ok", extract=meta_match.group(1))

    p_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    if p_match:
        text = re.sub(r"<[^>]+>", " ", p_match.group(1))
        text = _clean_text(text)
        if text:
            return FetchResult(status="ok", extract=text)
    return FetchResult(status="not_found")


def _pokemondb_url_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    slug = str(canonical_slug or "").strip().lower().replace(" ", "-")
    if not slug:
        slug = "-".join(part.lower() for part in answer_display.split())
    query = quote_plus(str(canonical_slug or answer_display).strip())

    urls: list[str] = []
    if source_type == "pokemon-species":
        urls.append(f"https://pokemondb.net/pokedex/{slug}")
    elif source_type == "move":
        urls.append(f"https://pokemondb.net/move/{slug}")
    elif source_type == "ability":
        urls.append(f"https://pokemondb.net/ability/{slug}")
    elif source_type == "item":
        urls.append(f"https://pokemondb.net/item/{slug}")
    elif source_type == "type":
        urls.append(f"https://pokemondb.net/type/{slug}")

    urls.append(f"https://pokemondb.net/search?q={query}")
    return urls


def _load_cache(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"entries": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"entries": {}}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {"entries": {}}
    return {"entries": entries}


def _save_cache(path: Path, cache: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_legacy_clue_cache(path: Path) -> dict[str, list[str]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    entries = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(entries, dict):
        return {}

    by_answer: dict[str, list[str]] = {}
    for key, value in entries.items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        clue = str(value.get("clue") or "").strip()
        if not clue:
            continue
        answer_display = key.split("|", 1)[-1].strip().upper()
        answer_norm = _normalize_answer(answer_display)
        if not answer_norm:
            continue
        bucket = by_answer.setdefault(answer_norm, [])
        if _clue_key(clue) not in {_clue_key(item) for item in bucket}:
            bucket.append(clue)
    return by_answer


def _derive_local_variants(existing_clues: list[str], answer_display: str, source_type: str) -> list[str]:
    derived: list[str] = []
    seen: set[str] = set()
    for clue in existing_clues:
        parts: list[str] = []
        parts.extend(SENTENCE_SPLIT_RE.split(_clean_text(clue)))
        parts.extend(segment.strip() for segment in clue.split(";") if segment.strip())
        for raw in parts:
            candidate = _as_sentence(raw)
            key = _clue_key(candidate)
            if not candidate or key in seen:
                continue
            seen.add(key)
            cleaned = _sanitize_external_candidate(candidate, answer_display, source_type)
            if cleaned:
                derived.append(cleaned)
    return derived


@dataclass
class AnswerBucket:
    display_answer: str
    clues: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build multi-clue crossword CSV with external clue variants (Bulbapedia + Serebii + PokemonDB).",
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--wordlist-json", type=Path, default=DEFAULT_WORDLIST_JSON)
    parser.add_argument("--variant-cache-json", type=Path, default=DEFAULT_VARIANT_CACHE_JSON)
    parser.add_argument("--legacy-cache-json", type=Path, default=DEFAULT_LEGACY_CACHE_JSON)
    parser.add_argument("--min-clues-per-answer", type=int, default=3)
    parser.add_argument("--max-clues-per-answer", type=int, default=5)
    parser.add_argument("--max-fetch", type=int, default=250)
    parser.add_argument("--timeout-seconds", type=float, default=6.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.2)
    parser.add_argument("--providers", type=str, default="bulbapedia,serebii,pokemondb")
    parser.add_argument(
        "--refresh-existing",
        action="store_true",
        help="Attempt external fetches up to max-clues-per-answer even when minimum is already met.",
    )
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--strict-min-clues", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    min_clues = max(1, int(args.min_clues_per_answer))
    max_clues = max(min_clues, int(args.max_clues_per_answer))
    providers = {part.strip().lower() for part in str(args.providers).split(",") if part.strip()}

    with args.input_csv.open(encoding="utf-8-sig", newline="") as handle:
        rows = [tuple(row[:2]) for row in csv.reader(handle) if len(row) >= 2]

    buckets: dict[str, AnswerBucket] = {}
    ordered_answers: list[str] = []
    for answer_raw, clue_raw in rows:
        answer_display = str(answer_raw).strip().upper()
        clue = _as_sentence(clue_raw)
        answer_norm = _normalize_answer(answer_display)
        if not answer_norm or not clue:
            continue
        bucket = buckets.get(answer_norm)
        if bucket is None:
            bucket = AnswerBucket(display_answer=answer_display, clues=[])
            buckets[answer_norm] = bucket
            ordered_answers.append(answer_norm)
        if _clue_key(clue) not in {_clue_key(item) for item in bucket.clues}:
            bucket.clues.append(clue)

    metadata_by_answer = _load_word_metadata(args.wordlist_json)
    variant_cache = _load_cache(args.variant_cache_json)
    variant_cache_entries = variant_cache["entries"]
    legacy_cache_by_answer = _load_legacy_clue_cache(args.legacy_cache_json)

    fetch_attempts = 0
    fetch_successes = 0
    fetch_failures = 0
    network_error_streak = 0
    fetch_aborted = False
    used_clue_keys: set[str] = set()
    shortfall_answers: list[tuple[str, int]] = []

    # Re-sanitize existing clues first so legacy rows cannot bypass quality filters.
    for answer_norm in ordered_answers:
        bucket = buckets[answer_norm]
        source_type = str(metadata_by_answer.get(answer_norm, {}).get("sourceType") or "")
        sanitized: list[str] = []
        seen_keys: set[str] = set()
        for clue in bucket.clues:
            cleaned = _sanitize_external_candidate(clue, bucket.display_answer, source_type)
            if not cleaned:
                continue
            key = _clue_key(cleaned)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            sanitized.append(cleaned)
            used_clue_keys.add(key)
        bucket.clues = sanitized

    for answer_norm in ordered_answers:
        bucket = buckets[answer_norm]
        meta = metadata_by_answer.get(answer_norm, {})
        source_type = str(meta.get("sourceType") or "")
        canonical_slug = str(meta.get("canonicalSlug") or "")
        variants: list[str] = list(bucket.clues)
        variant_keys = {_clue_key(clue) for clue in variants}

        def try_add(candidate: str) -> bool:
            cleaned = _sanitize_external_candidate(candidate, bucket.display_answer, source_type)
            if not cleaned:
                return False
            key = _clue_key(cleaned)
            if key in variant_keys or key in used_clue_keys:
                return False
            variants.append(cleaned)
            variant_keys.add(key)
            used_clue_keys.add(key)
            return True

        if len(variants) < max_clues:
            for local in _derive_local_variants(bucket.clues, bucket.display_answer, source_type):
                if len(variants) >= max_clues:
                    break
                try_add(local)

        for cached in legacy_cache_by_answer.get(answer_norm, []):
            if len(variants) >= max_clues:
                break
            try_add(cached)

        cache_key = answer_norm
        cached_entry = variant_cache_entries.get(cache_key)
        if isinstance(cached_entry, dict):
            for cached in cached_entry.get("clues", []):
                if len(variants) >= max_clues:
                    break
                if isinstance(cached, str):
                    try_add(cached)

        fetch_target = max_clues if args.refresh_existing else min_clues
        if len(variants) < fetch_target and not args.cache_only and not fetch_aborted:
            fetched_clues: list[str] = []

            if "bulbapedia" in providers:
                titles = _bulbapedia_title_candidates(bucket.display_answer, source_type, canonical_slug)
                for title in titles:
                    if fetch_attempts >= args.max_fetch or len(variants) + len(fetched_clues) >= fetch_target:
                        break
                    fetch_attempts += 1
                    result = _fetch_bulbapedia_extract(title, timeout_seconds=args.timeout_seconds)
                    if result.status == "ok" and result.extract:
                        fetch_successes += 1
                        network_error_streak = 0
                        for sentence in _extract_candidate_sentences(result.extract, max_sentences=6):
                            cleaned = _sanitize_external_candidate(sentence, bucket.display_answer, source_type)
                            if not cleaned:
                                continue
                            if _clue_key(cleaned) in {_clue_key(item) for item in fetched_clues}:
                                continue
                            fetched_clues.append(cleaned)
                            if len(variants) + len(fetched_clues) >= fetch_target:
                                break
                    else:
                        fetch_failures += 1
                        if result.status in {"timeout", "connection_error"}:
                            network_error_streak += 1
                            if network_error_streak >= 3:
                                fetch_aborted = True
                                break
                        else:
                            network_error_streak = 0
                    if args.request_delay_seconds > 0:
                        time.sleep(args.request_delay_seconds)

            if len(variants) + len(fetched_clues) < fetch_target and "serebii" in providers and not fetch_aborted:
                for url in _serebii_url_candidates(bucket.display_answer, source_type, canonical_slug):
                    if fetch_attempts >= args.max_fetch or len(variants) + len(fetched_clues) >= fetch_target:
                        break
                    fetch_attempts += 1
                    result = _fetch_serebii_description(url, timeout_seconds=args.timeout_seconds)
                    if result.status == "ok" and result.extract:
                        fetch_successes += 1
                        network_error_streak = 0
                        for sentence in _extract_candidate_sentences(result.extract, max_sentences=4):
                            cleaned = _sanitize_external_candidate(sentence, bucket.display_answer, source_type)
                            if not cleaned:
                                continue
                            if _clue_key(cleaned) in {_clue_key(item) for item in fetched_clues}:
                                continue
                            fetched_clues.append(cleaned)
                            if len(variants) + len(fetched_clues) >= fetch_target:
                                break
                    else:
                        fetch_failures += 1
                        if result.status in {"timeout", "connection_error"}:
                            network_error_streak += 1
                            if network_error_streak >= 3:
                                fetch_aborted = True
                                break
                        else:
                            network_error_streak = 0
                    if args.request_delay_seconds > 0:
                        time.sleep(args.request_delay_seconds)

            if len(variants) + len(fetched_clues) < fetch_target and "pokemondb" in providers and not fetch_aborted:
                for url in _pokemondb_url_candidates(bucket.display_answer, source_type, canonical_slug):
                    if fetch_attempts >= args.max_fetch or len(variants) + len(fetched_clues) >= fetch_target:
                        break
                    fetch_attempts += 1
                    result = _fetch_pokemondb_description(url, timeout_seconds=args.timeout_seconds)
                    if result.status == "ok" and result.extract:
                        fetch_successes += 1
                        network_error_streak = 0
                        for sentence in _extract_candidate_sentences(result.extract, max_sentences=4):
                            cleaned = _sanitize_external_candidate(sentence, bucket.display_answer, source_type)
                            if not cleaned:
                                continue
                            if _clue_key(cleaned) in {_clue_key(item) for item in fetched_clues}:
                                continue
                            fetched_clues.append(cleaned)
                            if len(variants) + len(fetched_clues) >= fetch_target:
                                break
                    else:
                        fetch_failures += 1
                        if result.status in {"timeout", "connection_error"}:
                            network_error_streak += 1
                            if network_error_streak >= 3:
                                fetch_aborted = True
                                break
                        else:
                            network_error_streak = 0
                    if args.request_delay_seconds > 0:
                        time.sleep(args.request_delay_seconds)

            if fetched_clues:
                for clue in fetched_clues:
                    if len(variants) >= max_clues:
                        break
                    try_add(clue)
                variant_cache_entries[cache_key] = {
                    "status": "ok",
                    "clues": fetched_clues,
                    "updatedAt": int(time.time()),
                }
            elif cache_key not in variant_cache_entries:
                variant_cache_entries[cache_key] = {
                    "status": "not_found",
                    "clues": [],
                    "updatedAt": int(time.time()),
                }

        if len(variants) < min_clues:
            for fallback in _derive_structural_fallback_variants(
                answer_norm=answer_norm,
                display_answer=bucket.display_answer,
                source_type=source_type,
            ):
                if len(variants) >= min_clues:
                    break
                try_add(fallback)

        if len(variants) < min_clues:
            shortfall_answers.append((bucket.display_answer, len(variants)))
        bucket.clues = variants[:max_clues]

    output_rows: list[tuple[str, str]] = []
    for answer_norm in sorted(ordered_answers, key=lambda key: key.replace(" ", "")):
        bucket = buckets[answer_norm]
        for clue in bucket.clues:
            output_rows.append((bucket.display_answer, clue))

    if not args.dry_run:
        with args.output_csv.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(output_rows)
        _save_cache(args.variant_cache_json, variant_cache)

    answers_total = len(ordered_answers)
    answers_meeting_min = answers_total - len(shortfall_answers)
    print(f"Answers total: {answers_total}")
    print(f"Answers with >= {min_clues} clues: {answers_meeting_min}")
    print(f"Answers below {min_clues} clues: {len(shortfall_answers)}")
    print(f"Output rows: {len(output_rows)}")
    print(f"Fetch attempts: {fetch_attempts}")
    print(f"Fetch successes: {fetch_successes}")
    print(f"Fetch failures: {fetch_failures}")
    print(f"Fetch aborted due network errors: {fetch_aborted}")
    if shortfall_answers and args.verbose:
        for answer_display, count in shortfall_answers[:200]:
            print(f"shortfall {answer_display}: {count}")
    if args.dry_run:
        print("Dry run: no files written")
    else:
        print(f"Wrote CSV: {args.output_csv}")
        print(f"Wrote variant cache: {args.variant_cache_json}")

    if args.strict_min_clues and shortfall_answers:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
