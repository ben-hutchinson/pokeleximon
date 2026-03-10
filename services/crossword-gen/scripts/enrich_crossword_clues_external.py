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
DEFAULT_WORDLIST_JSON = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_CACHE_JSON = ROOT_DIR / "data" / "crossword_external_clue_cache.json"
DEFAULT_OUTPUT_CSV = DEFAULT_INPUT_CSV
MEDIAWIKI_API_URL = "https://bulbapedia.bulbagarden.net/w/api.php"
SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")
TOKEN_RE = re.compile(r"[^A-Z0-9]")
WHITESPACE_RE = re.compile(r"\s+")

LOW_QUALITY_PATTERNS = (
    re.compile(r"(?i)redirects here"),
    re.compile(r"(?i)this article is about"),
    re.compile(r"(?i)may refer to"),
    re.compile(r"(?i)disambiguation"),
    re.compile(r"(?i)^for the"),
    re.compile(r"(?i)if you were looking for"),
    re.compile(r"(?i)for a list of"),
    re.compile(r"(?i)see this (location|item|pokemon|move|ability|type)"),
    re.compile(r"(?i)prominent locations found within the pok[eé]mon world"),
)

GENERIC_CLUE_PATTERNS = (
    re.compile(r"(?i)^location:\s*region\s"),
    re.compile(r"(?i)^a?n?\s+location\s+in\s+[a-z][a-z' -]+\.?$"),
    re.compile(r"(?i)^pok[eé]mon elemental type\.?$"),
    re.compile(r"(?i)^pok[eé]mon item from (the )?main series games\.?$"),
    re.compile(r"(?i)^type entry \(pok[eé]api\s+\d+\)\.?$"),
    re.compile(r"(?i)^pok[eé]api ref \d+\.?$"),
    re.compile(r"(?i)^ability entry \(pok[eé]api\s+\d+\)\.?$"),
    re.compile(r"(?i)^location entry \(pok[eé]api\s+\d+\)\.?$"),
    re.compile(r"(?i)^.* item \(pok[eé]api item #\d+\)\.?$"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bpok[eé]mon term from the csv lexicon\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
    re.compile(r"(?i)^gen\s+[ivx]+\s+ability(?:\s+\(side-series data\))?:\s+battle ability from the core games\.?$"),
)

SOURCE_REPLACEMENT = {
    "pokemon-species": "this Pokemon",
    "move": "this move",
    "ability": "this ability",
    "item": "this item",
    "location": "this location",
    "location-area": "this location",
    "type": "this type",
}

VARIANT_PRIORITY = {
    "name": 0,
    "slug": 1,
    "part": 2,
}


def _clean_text(text: str) -> str:
    out = WHITESPACE_RE.sub(" ", str(text).replace("\n", " ").replace("\f", " ")).strip()
    return out


def _as_sentence(text: str) -> str:
    out = _clean_text(text)
    if out and out[-1] not in ".!?":
        out += "."
    return out


def _normalize_answer(text: str) -> str:
    return TOKEN_RE.sub("", str(text).upper())


def _answer_parts(display_answer: str) -> list[str]:
    return [part for part in str(display_answer).upper().split(" ") if part]


def _answer_fragments(display_answer: str) -> list[str]:
    parts = _answer_parts(display_answer)
    fragments: set[str] = set()
    for part in parts:
        if len(part) >= 2:
            fragments.add(part)
    for value in ("".join(parts), " ".join(parts), "-".join(parts)):
        if len(value.replace(" ", "").replace("-", "")) >= 2:
            fragments.add(value)
    return sorted(fragments, key=len, reverse=True)


def _strip_answer_fragments(clue: str, display_answer: str, source_type: str) -> str:
    out = clue
    replacement = SOURCE_REPLACEMENT.get(source_type, "this entry")
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = out.replace("this location this location", "this location")
    out = out.replace("this item this item", "this item")
    out = out.replace("this move this move", "this move")
    out = out.replace("this ability this ability", "this ability")
    out = out.replace("this Pokemon this Pokemon", "this Pokemon")
    out = out.replace("this type this type", "this type")
    return _as_sentence(out)


def _is_low_quality_clue(clue: str) -> bool:
    text = _clean_text(clue)
    if not text:
        return True
    if len(text) < 24:
        return True
    if text.lower().count("this location") >= 3:
        return True
    return any(pattern.search(text) for pattern in LOW_QUALITY_PATTERNS)


def _clue_contains_answer_fragment(clue: str, display_answer: str) -> bool:
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            return True
    return False


def _record_score(record: dict[str, Any]) -> tuple[int, int, int]:
    variant = str(record.get("variant", ""))
    parts = record.get("parts")
    part_count = len(parts) if isinstance(parts, list) else 1
    return (VARIANT_PRIORITY.get(variant, 99), part_count, len(str(record.get("word", ""))))


def _display_answer(record: dict[str, Any]) -> str:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        tokens = [str(part).strip().upper() for part in parts if str(part).strip()]
        if tokens:
            return " ".join(tokens)
    return str(record.get("word", "")).strip().upper()


def _parse_source_ref(source_ref: str) -> tuple[str | None, int | None]:
    match = SOURCE_REF_RE.search(str(source_ref).strip())
    if not match:
        return None, None
    resource = match.group(1)
    try:
        resource_id = int(match.group(2))
    except ValueError:
        return resource, None
    return resource, resource_id


def _load_payload_name_index(cache_dir: Path) -> dict[tuple[str, int], str]:
    index: dict[tuple[str, int], str] = {}
    for path in sorted(cache_dir.glob("*.json")):
        resource = path.name.split("_", 1)[0]
        if resource not in {"pokemon-species", "move", "item", "location", "location-area", "ability", "type"}:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        resource_id = payload.get("id")
        name = payload.get("name")
        if isinstance(resource_id, int) and isinstance(name, str) and name.strip():
            index[(resource, resource_id)] = name.strip()
    return index


def _slug_to_title_space(slug: str) -> str:
    return " ".join(part.capitalize() for part in str(slug).replace("_", "-").split("-") if part)


def _slug_to_title_hyphen(slug: str) -> str:
    return "-".join(part.capitalize() for part in str(slug).replace("_", "-").split("-") if part)


def _to_title_from_answer(answer_display: str) -> str:
    return " ".join(part.capitalize() for part in str(answer_display).split() if part)


def _is_generic_clue(clue: str) -> bool:
    text = str(clue).strip()
    if not text:
        return True
    return any(pattern.search(text) for pattern in GENERIC_CLUE_PATTERNS)


def _bulbapedia_title_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    base_answer = _to_title_from_answer(answer_display)
    candidates: list[str] = []

    slug_space = _slug_to_title_space(canonical_slug) if canonical_slug else ""
    slug_hyphen = _slug_to_title_hyphen(canonical_slug) if canonical_slug else ""

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


def _first_good_sentence(extract: str) -> str:
    text = _clean_text(extract)
    if not text:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    for sentence in sentences:
        s = _clean_text(sentence)
        if len(s) < 28:
            continue
        if _is_low_quality_clue(s):
            continue
        return _as_sentence(s)

    fallback = _as_sentence(text[:240])
    if _is_low_quality_clue(fallback):
        return ""
    return fallback


@dataclass
class FetchResult:
    status: str
    title: str | None = None
    extract: str | None = None
    error: str | None = None


def _search_bulbapedia_titles(query: str, timeout_seconds: float, limit: int = 8) -> tuple[list[str], str | None]:
    params = {
        "action": "opensearch",
        "format": "json",
        "search": query,
        "namespace": "0",
        "limit": str(limit),
    }
    try:
        response = requests.get(
            MEDIAWIKI_API_URL,
            params=params,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-clue-enricher/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return [], "timeout"
    except requests.ConnectionError:
        return [], "connection_error"
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return [], f"http_{code}"
    except requests.RequestException:
        return [], "request_error"
    except ValueError:
        return [], "json_error"

    if not isinstance(payload, list) or len(payload) < 2 or not isinstance(payload[1], list):
        return [], "bad_payload"

    titles: list[str] = []
    seen: set[str] = set()
    for item in payload[1]:
        if not isinstance(item, str):
            continue
        cleaned = _clean_text(item)
        key = cleaned.lower()
        if not cleaned or key in seen:
            continue
        seen.add(key)
        titles.append(cleaned)
    return titles, None


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
            headers={"User-Agent": "pokeleximon-clue-enricher/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except requests.Timeout:
        return FetchResult(status="timeout", error="timeout")
    except requests.ConnectionError as exc:
        return FetchResult(status="connection_error", error=str(exc))
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return FetchResult(status=f"http_{code}", error=str(exc))
    except requests.RequestException as exc:
        return FetchResult(status="request_error", error=str(exc))
    except ValueError as exc:
        return FetchResult(status="json_error", error=str(exc))

    query = payload.get("query") if isinstance(payload, dict) else None
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, dict):
        return FetchResult(status="bad_payload", error="missing pages")

    for page in pages.values():
        if not isinstance(page, dict):
            continue
        if "missing" in page:
            continue
        extract = page.get("extract")
        if isinstance(extract, str) and extract.strip():
            resolved_title = str(page.get("title") or title)
            return FetchResult(status="ok", title=resolved_title, extract=extract)

    return FetchResult(status="not_found")


def _fetch_html_description(url: str, timeout_seconds: float) -> FetchResult:
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-clue-enricher/0.1"},
        )
        response.raise_for_status()
        html = response.text
    except requests.Timeout:
        return FetchResult(status="timeout", error="timeout")
    except requests.ConnectionError as exc:
        return FetchResult(status="connection_error", error=str(exc))
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return FetchResult(status=f"http_{code}", error=str(exc))
    except requests.RequestException as exc:
        return FetchResult(status="request_error", error=str(exc))

    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if meta_match:
        return FetchResult(status="ok", title=url, extract=meta_match.group(1))

    p_match = re.search(r"<p[^>]*>(.*?)</p>", html, re.IGNORECASE | re.DOTALL)
    if p_match:
        text = re.sub(r"<[^>]+>", " ", p_match.group(1))
        text = _clean_text(text)
        if text:
            return FetchResult(status="ok", title=url, extract=text)
    return FetchResult(status="not_found")


def _slug_candidate(answer_display: str, canonical_slug: str | None) -> str:
    slug = str(canonical_slug or "").strip().lower().replace(" ", "-")
    if slug:
        return slug
    return "-".join(part.lower() for part in answer_display.split())


def _serebii_url_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    slug = _slug_candidate(answer_display, canonical_slug)
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


def _pokemondb_url_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    slug = _slug_candidate(answer_display, canonical_slug)
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


def _load_word_metadata(wordlist_path: Path, payload_name_index: dict[tuple[str, int], str]) -> dict[str, dict[str, Any]]:
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
        source_ref = str(row.get("sourceRef") or "").strip()
        source_type = str(row.get("sourceType") or "").strip()
        parsed_source_type, source_id = _parse_source_ref(source_ref)
        final_source_type = parsed_source_type or source_type

        canonical_slug = None
        if parsed_source_type and isinstance(source_id, int):
            canonical_slug = payload_name_index.get((parsed_source_type, source_id))

        metadata[answer_display] = {
            "sourceRef": source_ref,
            "sourceType": final_source_type,
            "sourceId": source_id,
            "canonicalSlug": canonical_slug,
        }
    return metadata


def _write_csv(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Enrich generic crossword clues with external source summaries (Bulbapedia/Serebii/PokemonDB).",
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--wordlist-json", type=Path, default=DEFAULT_WORDLIST_JSON)
    parser.add_argument("--cache-json", type=Path, default=DEFAULT_CACHE_JSON)
    parser.add_argument("--pokeapi-cache-dir", type=Path, default=ROOT_DIR / "services" / "data" / "pokeapi")
    parser.add_argument("--timeout-seconds", type=float, default=6.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.15)
    parser.add_argument("--max-fetch", type=int, default=250)
    parser.add_argument(
        "--source-types",
        type=str,
        default="location,item,type,ability,move,pokemon-species",
        help="Comma-separated source types allowed for enrichment.",
    )
    parser.add_argument("--all-clues", action="store_true", help="Try enriching all clues, not just generic ones.")
    parser.add_argument(
        "--providers",
        type=str,
        default="bulbapedia,serebii,pokemondb",
        help="Comma-separated external clue providers.",
    )
    parser.add_argument("--cache-only", action="store_true", help="Do not call external endpoints; use cache only.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    providers = {value.strip().lower() for value in str(args.providers).split(",") if value.strip()}

    allowed_source_types = {
        value.strip() for value in str(args.source_types).split(",") if value.strip()
    }

    with args.input_csv.open(encoding="utf-8-sig", newline="") as handle:
        original_rows = [tuple(row[:2]) for row in csv.reader(handle) if len(row) >= 2]

    payload_name_index = _load_payload_name_index(args.pokeapi_cache_dir)
    metadata_by_answer = _load_word_metadata(args.wordlist_json, payload_name_index)
    cache = _load_cache(args.cache_json)
    cache_entries = cache["entries"]

    used_clues = {clue for _, clue in original_rows}
    output_rows: list[tuple[str, str]] = []

    targeted = 0
    changed = 0
    cache_hits = 0
    fetch_attempts = 0
    fetch_successes = 0
    fetch_failures = 0
    skipped_duplicates = 0
    network_error_streak = 0
    fetch_aborted = False

    for answer, clue in original_rows:
        meta = metadata_by_answer.get(answer)
        if not meta:
            output_rows.append((answer, clue))
            continue

        source_type = str(meta.get("sourceType") or "").strip()
        source_id = meta.get("sourceId")
        canonical_slug = meta.get("canonicalSlug")

        if source_type and allowed_source_types and source_type not in allowed_source_types:
            output_rows.append((answer, clue))
            continue

        if not args.all_clues and not (_is_generic_clue(clue) or _is_low_quality_clue(clue)):
            output_rows.append((answer, clue))
            continue

        targeted += 1
        cache_key = f"{source_type}|{answer}"
        cached_entry = cache_entries.get(cache_key)

        candidate_clue = None
        if isinstance(cached_entry, dict) and cached_entry.get("status") == "ok":
            cached_clue = str(cached_entry.get("clue") or "").strip()
            if (
                cached_clue
                and not _is_low_quality_clue(cached_clue)
                and (args.all_clues or not _is_generic_clue(cached_clue))
            ):
                candidate_clue = cached_clue
                cache_hits += 1

        if candidate_clue is None and not args.cache_only and not fetch_aborted and fetch_attempts < args.max_fetch:
            titles = _bulbapedia_title_candidates(answer, source_type, canonical_slug)
            best_result: FetchResult | None = None
            best_source: str | None = None
            tried_titles: set[str] = set()

            def try_title(title: str) -> str | None:
                nonlocal fetch_attempts, fetch_successes, network_error_streak, fetch_aborted, best_result

                cleaned_title = _clean_text(title)
                if not cleaned_title:
                    return None
                if cleaned_title.lower() in tried_titles:
                    return None
                tried_titles.add(cleaned_title.lower())

                fetch_attempts += 1
                result = _fetch_bulbapedia_extract(cleaned_title, timeout_seconds=args.timeout_seconds)

                if result.status == "ok" and result.extract:
                    best_result = result
                    best_source = "bulbapedia"
                    fetch_successes += 1
                    network_error_streak = 0
                    return "ok"

                if result.status in {"connection_error", "timeout"}:
                    network_error_streak += 1
                else:
                    network_error_streak = 0

                if network_error_streak >= 3:
                    fetch_aborted = True
                    return "network_unavailable"

                return result.status

            if "bulbapedia" in providers:
                for title in titles:
                    status = try_title(title)
                    if status == "ok":
                        break
                    if status == "network_unavailable":
                        break

                    if fetch_attempts >= args.max_fetch:
                        break

                    if args.request_delay_seconds > 0:
                        time.sleep(args.request_delay_seconds)

                if best_result is None and not fetch_aborted and fetch_attempts < args.max_fetch:
                    search_queries = [query for query in (_to_title_from_answer(answer), _slug_to_title_space(canonical_slug or "")) if query]
                    for query in search_queries:
                        found_titles, search_error = _search_bulbapedia_titles(query, timeout_seconds=args.timeout_seconds)
                        if search_error in {"connection_error", "timeout"}:
                            network_error_streak += 1
                            if network_error_streak >= 3:
                                fetch_aborted = True
                                break
                        elif search_error is None:
                            network_error_streak = 0

                        for title in found_titles:
                            status = try_title(title)
                            if status == "ok":
                                break
                            if status == "network_unavailable":
                                break
                            if fetch_attempts >= args.max_fetch:
                                break
                            if args.request_delay_seconds > 0:
                                time.sleep(args.request_delay_seconds)

                        if best_result is not None or fetch_aborted or fetch_attempts >= args.max_fetch:
                            break

            if best_result is None and "serebii" in providers and not fetch_aborted and fetch_attempts < args.max_fetch:
                for url in _serebii_url_candidates(answer, source_type, canonical_slug):
                    if fetch_attempts >= args.max_fetch:
                        break
                    fetch_attempts += 1
                    result = _fetch_html_description(url, timeout_seconds=args.timeout_seconds)
                    if result.status == "ok" and result.extract:
                        best_result = result
                        best_source = "serebii"
                        fetch_successes += 1
                        network_error_streak = 0
                        break
                    fetch_failures += 1
                    if result.status in {"connection_error", "timeout"}:
                        network_error_streak += 1
                        if network_error_streak >= 3:
                            fetch_aborted = True
                            break
                    else:
                        network_error_streak = 0
                    if args.request_delay_seconds > 0:
                        time.sleep(args.request_delay_seconds)

            if best_result is None and "pokemondb" in providers and not fetch_aborted and fetch_attempts < args.max_fetch:
                for url in _pokemondb_url_candidates(answer, source_type, canonical_slug):
                    if fetch_attempts >= args.max_fetch:
                        break
                    fetch_attempts += 1
                    result = _fetch_html_description(url, timeout_seconds=args.timeout_seconds)
                    if result.status == "ok" and result.extract:
                        best_result = result
                        best_source = "pokemondb"
                        fetch_successes += 1
                        network_error_streak = 0
                        break
                    fetch_failures += 1
                    if result.status in {"connection_error", "timeout"}:
                        network_error_streak += 1
                        if network_error_streak >= 3:
                            fetch_aborted = True
                            break
                    else:
                        network_error_streak = 0
                    if args.request_delay_seconds > 0:
                        time.sleep(args.request_delay_seconds)

            if best_result is None:
                fetch_failures += 1
                if fetch_aborted:
                    if args.verbose:
                        print("Fetch aborted due repeated network errors; remaining rows will use cache-only.")
                status = "network_unavailable" if fetch_aborted else "not_found"
                cache_entries[cache_key] = {
                    "status": status,
                    "updatedAt": int(time.time()),
                }
            else:
                sentence = _first_good_sentence(best_result.extract or "")
                cleaned = _strip_answer_fragments(sentence, answer, source_type)
                if (
                    cleaned
                    and not _clue_contains_answer_fragment(cleaned, answer)
                    and not _is_low_quality_clue(cleaned)
                    and len(cleaned) >= 24
                ):
                    candidate_clue = cleaned
                    cache_entries[cache_key] = {
                        "status": "ok",
                        "source": best_source or "bulbapedia",
                        "title": best_result.title,
                        "clue": cleaned,
                        "updatedAt": int(time.time()),
                    }
                else:
                    cache_entries[cache_key] = {
                        "status": "unusable_extract",
                        "source": best_source or "bulbapedia",
                        "title": best_result.title,
                        "updatedAt": int(time.time()),
                    }

        final_clue = clue
        if (
            candidate_clue
            and candidate_clue != clue
            and not _is_generic_clue(candidate_clue)
            and not _is_low_quality_clue(candidate_clue)
        ):
            if candidate_clue in used_clues:
                suffix = None
                if isinstance(source_id, int):
                    source_name = str((cache_entries.get(cache_key) or {}).get("source") or "external").capitalize()
                    suffix = f" ({source_name} {source_type} #{source_id})"
                if suffix:
                    decorated = _as_sentence(candidate_clue.rstrip(".") + suffix)
                    if decorated not in used_clues and not _clue_contains_answer_fragment(decorated, answer):
                        candidate_clue = decorated
                    else:
                        candidate_clue = None
                else:
                    candidate_clue = None
                if candidate_clue is None:
                    skipped_duplicates += 1

            if candidate_clue:
                final_clue = candidate_clue
                changed += 1

        output_rows.append((answer, final_clue))
        used_clues.add(final_clue)

    output_rows = sorted(output_rows, key=lambda value: value[0].replace(" ", ""))

    if not args.dry_run:
        _write_csv(args.output_csv, output_rows)
        _save_cache(args.cache_json, cache)

    print(f"Input rows: {len(original_rows)}")
    print(f"Targeted generic/all rows: {targeted}")
    print(f"Updated clues: {changed}")
    print(f"Cache hits used: {cache_hits}")
    print(f"Fetch attempts: {fetch_attempts}")
    print(f"Fetch successes: {fetch_successes}")
    print(f"Fetch failures: {fetch_failures}")
    print(f"Skipped due duplicate clue collision: {skipped_duplicates}")
    print(f"Fetch aborted due network errors: {fetch_aborted}")
    if args.dry_run:
        print("Dry run: no files written")
    else:
        print(f"Wrote enriched CSV: {args.output_csv}")
        print(f"Wrote cache: {args.cache_json}")


if __name__ == "__main__":
    main()
