from __future__ import annotations

import json
from itertools import product
import re
import time
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


MEDIAWIKI_API_URL = "https://bulbapedia.bulbagarden.net/w/api.php"
WHITESPACE_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")
SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")

SECTION_TITLE_PRIORITY = (
    "Biology",
    "Effect",
    "In battle",
    "Description",
    "Game data",
    "Pokédex entries",
    "Pokédex data",
    "In the core series games",
    "Trivia",
    "Anime",
)
SECOND_PASS_SECTION_TITLE_PRIORITY = (
    "Effect",
    "In battle",
    "Acquisition",
    "Description",
    "In the core series games",
    "Game data",
    "Biology",
)
EVIDENCE_VERSION = "bulbapedia-evidence-v3"


def _clean_text(value: str) -> str:
    text = unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    text = text.replace("\n", " ").replace("\f", " ")
    return WHITESPACE_RE.sub(" ", text).strip()


def _normalize_answer(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _parse_source_ref(source_ref: str) -> tuple[str | None, int | None]:
    match = SOURCE_REF_RE.search(str(source_ref or "").strip())
    if not match:
        return None, None
    source_type = match.group(1)
    try:
        source_id = int(match.group(2))
    except ValueError:
        return source_type, None
    return source_type, source_id


def _slug_to_title_space(slug: str) -> str:
    return " ".join(part.capitalize() for part in str(slug or "").replace("_", "-").split("-") if part)


def _slug_to_title_hyphen(slug: str) -> str:
    return "-".join(part.capitalize() for part in str(slug or "").replace("_", "-").split("-") if part)


def _slug_title_variants(slug: str) -> list[str]:
    parts = [part for part in str(slug or "").replace("_", "-").split("-") if part]
    if not parts:
        return []
    if len(parts) == 1:
        return [parts[0].capitalize()]

    variants: list[str] = []
    normalized_parts = [part.capitalize() for part in parts]
    separator_sets = [(" ", "-")] * (len(normalized_parts) - 1)
    if len(normalized_parts) > 5:
        separator_combos = [tuple(" " for _ in separator_sets), tuple("-" for _ in separator_sets)]
    else:
        separator_combos = product(*separator_sets)

    for separators in separator_combos:
        text = normalized_parts[0]
        for separator, part in zip(separators, normalized_parts[1:]):
            text += separator + part
        variants.append(text)
    return variants


def _generation_display_name(raw: str) -> str:
    slug = str(raw or "").strip().lower()
    if not slug.startswith("generation-"):
        return _clean_text(raw)
    suffix = slug.split("generation-", 1)[1].upper()
    return f"Gen {suffix}"


def _strip_parenthetical_suffix(value: str) -> str:
    return re.sub(r"\s*\([^)]*\)\s*$", "", _clean_text(value)).strip()


def _title_search_queries(answer_display: str, source_type: str, canonical_slug: str | None, direct_candidates: list[str]) -> list[str]:
    queries: list[str] = []
    source_label = {
        "pokemon-species": "Pokemon",
        "move": "move",
        "ability": "Ability",
        "item": "item",
        "location": "location",
        "location-area": "location",
        "type": "type",
    }.get(source_type, "")
    for candidate in direct_candidates:
        queries.append(candidate)
        if source_label:
            queries.append(f"{_strip_parenthetical_suffix(candidate)} {source_label}")

    if canonical_slug:
        slug_space = _slug_to_title_space(canonical_slug)
        if slug_space:
            queries.append(slug_space)
            if source_label:
                queries.append(f"{slug_space} {source_label}")

    # Legends: Arceus capture-ball answers are stored with an "LA" prefix in the wordlist.
    if source_type == "item":
        tokens = _clean_text(answer_display).split()
        if len(tokens) >= 2 and tokens[-1].lower() == "ball" and tokens[0].lower().startswith("la") and len(tokens[0]) > 2:
            alias = " ".join([tokens[0][2:], *tokens[1:]])
            queries.append(alias)
            if source_label:
                queries.append(f"{alias} {source_label}")

    out: list[str] = []
    seen: set[str] = set()
    for query in queries:
        cleaned = _clean_text(query)
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            out.append(cleaned)
    return out


def _accepted_search_keys(answer_display: str, canonical_slug: str | None, source_type: str) -> set[str]:
    keys = {
        _normalize_answer(answer_display),
        _normalize_answer(_slug_to_title_space(canonical_slug or "")),
        _normalize_answer(_slug_to_title_hyphen(canonical_slug or "")),
    }
    for value in _slug_title_variants(canonical_slug or ""):
        keys.add(_normalize_answer(value))

    if source_type == "item":
        tokens = _clean_text(answer_display).split()
        if len(tokens) >= 2 and tokens[-1].lower() == "ball" and tokens[0].lower().startswith("la") and len(tokens[0]) > 2:
            keys.add(_normalize_answer(" ".join([tokens[0][2:], *tokens[1:]])))
    return {key for key in keys if key}


def _cached_requires_refetch(
    payload: dict[str, Any],
    *,
    answer_display: str,
    canonical_slug: str | None,
    source_type: str,
) -> bool:
    if str(payload.get("status") or "") != "ok":
        return False
    cached_title_key = _normalize_answer(_strip_parenthetical_suffix(str(payload.get("pageTitle") or "")))
    if cached_title_key and cached_title_key not in _accepted_search_keys(answer_display, canonical_slug, source_type):
        return True
    lead = str(payload.get("leadText") or "").lower()
    if source_type in {"pokemon-species", "ability", "item"} and any(
        marker in lead for marker in ("has several referrals", "redirects here", "if you were looking for")
    ):
        if "(" not in str(payload.get("pageTitle") or ""):
            return True
    return False


def search_page_titles(query: str, timeout_seconds: float) -> list[str]:
    payload = _get_json(
        {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
        },
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(payload, dict):
        return []
    results = payload.get("query", {}).get("search")
    if not isinstance(results, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for row in results:
        if not isinstance(row, dict):
            continue
        title = _clean_text(str(row.get("title") or ""))
        lowered = title.lower()
        if title and lowered not in seen:
            seen.add(lowered)
            out.append(title)
    return out


def title_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    base_answer = " ".join(part.capitalize() for part in str(answer_display or "").split() if part)
    slug_space = _slug_to_title_space(canonical_slug or "")
    slug_hyphen = _slug_to_title_hyphen(canonical_slug or "")
    base = slug_hyphen or slug_space or base_answer
    candidates: list[str] = []
    if base:
        if source_type == "pokemon-species":
            candidates.extend([f"{base} (Pokemon)", f"{base} (Pokémon)", f"{base} (species)"])
        elif source_type == "move":
            candidates.append(f"{base} (move)")
        elif source_type == "ability":
            candidates.extend([f"{base} (Ability)", f"{base} (ability)"])
        elif source_type == "item":
            candidates.append(f"{base} (item)")
        elif source_type in {"location", "location-area"}:
            candidates.append(f"{base} (location)")
        elif source_type == "type":
            candidates.extend([f"{base} (type)", f"{base} type"])
    for item in [*(_slug_title_variants(canonical_slug or "")), slug_hyphen, slug_space, base_answer]:
        if item:
            candidates.append(item)
    out: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        cleaned = _clean_text(item)
        lowered = cleaned.lower()
        if cleaned and lowered not in seen:
            seen.add(lowered)
            out.append(cleaned)
    return out


def cache_path(cache_dir: Path, answer_key: str) -> Path:
    return cache_dir / f"{_normalize_answer(answer_key)}.json"


def _item_family_page_titles(answer_display: str, structured_facts: dict[str, Any] | None) -> list[str]:
    answer = _clean_text(answer_display).upper()
    category = _clean_text(str((structured_facts or {}).get("category") or "")).lower()
    titles: list[str] = []
    if "BERRY" in answer or "berry" in category:
        titles.append("Berry")
    if answer.endswith(" MINT") or "mint" in category:
        titles.append("Mint")
    if answer.endswith(" FOSSIL") or "fossil" in answer:
        titles.append("Fossil")
    if any(token in answer for token in (" PLATE", " MEMORY", " DRIVE", " ORB")):
        if " PLATE" in answer:
            titles.append("Plate")
        if " MEMORY" in answer:
            titles.append("Memory")
        if " DRIVE" in answer:
            titles.append("Drive")
        if " ORB" in answer:
            titles.append("Orb")
    if any(token in answer for token in (" SHARD", " MATERIAL", " ORE")) or "collectible" in category:
        if " SHARD" in answer:
            titles.append("Tera Shard")
        if " ORE" in answer:
            titles.append("Ore")
        titles.append("Material")
    if any(token in answer for token in (" KEY", " PASS", " TICKET", " FLUTE", " CARD")) or category in {"event items", "plot advancement"}:
        titles.append("Key item")
    out: list[str] = []
    seen: set[str] = set()
    for title in titles:
        lowered = title.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        out.append(title)
    return out


def load_cached_evidence(cache_dir: Path, answer_key: str, *, second_pass: bool = False) -> dict[str, Any] | None:
    path = cache_path(cache_dir, answer_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("evidenceVersion") != EVIDENCE_VERSION:
        return None
    if second_pass and payload.get("passMode") != "second_pass":
        return None
    return payload


def _get_json(params: dict[str, Any], timeout_seconds: float) -> dict[str, Any] | None:
    try:
        response = requests.get(
            MEDIAWIKI_API_URL,
            params=params,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-bulbapedia-evidence/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def resolve_page_metadata(title: str, timeout_seconds: float) -> dict[str, Any] | None:
    payload = _get_json(
        {
            "action": "query",
            "format": "json",
            "redirects": "1",
            "prop": "info",
            "inprop": "url",
            "titles": title,
        },
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(payload, dict):
        return None
    query = payload.get("query")
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, dict):
        return None
    for page in pages.values():
        if not isinstance(page, dict) or "missing" in page:
            continue
        return {
            "pageId": page.get("pageid"),
            "title": _clean_text(str(page.get("title") or "")),
            "fullUrl": str(page.get("fullurl") or ""),
            "lastRevid": page.get("lastrevid"),
        }
    return None


def fetch_lead_text(title: str, timeout_seconds: float) -> str:
    payload = _get_json(
        {
            "action": "query",
            "format": "json",
            "prop": "extracts",
            "exintro": "1",
            "explaintext": "1",
            "redirects": "1",
            "titles": title,
        },
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(payload, dict):
        return ""
    query = payload.get("query")
    pages = query.get("pages") if isinstance(query, dict) else None
    if not isinstance(pages, dict):
        return ""
    for page in pages.values():
        if not isinstance(page, dict) or "missing" in page:
            continue
        return _clean_text(str(page.get("extract") or ""))
    return ""


def fetch_sections(title: str, timeout_seconds: float) -> list[dict[str, Any]]:
    payload = _get_json(
        {"action": "parse", "format": "json", "page": title, "prop": "sections"},
        timeout_seconds=timeout_seconds,
    )
    parse = payload.get("parse") if isinstance(payload, dict) else None
    sections = parse.get("sections") if isinstance(parse, dict) else None
    if not isinstance(sections, list):
        return []
    out: list[dict[str, Any]] = []
    for row in sections:
        if not isinstance(row, dict):
            continue
        index = str(row.get("index") or "").strip()
        line = _clean_text(str(row.get("line") or ""))
        if index and line:
            out.append({"index": index, "title": line})
    return out


def fetch_section_text(title: str, section_index: str, timeout_seconds: float) -> str:
    payload = _get_json(
        {"action": "parse", "format": "json", "page": title, "prop": "text", "section": section_index},
        timeout_seconds=timeout_seconds,
    )
    parse = payload.get("parse") if isinstance(payload, dict) else None
    text = parse.get("text") if isinstance(parse, dict) else None
    html = text.get("*") if isinstance(text, dict) else ""
    return _clean_text(str(html or ""))


def _selected_section_rows(
    sections: list[dict[str, Any]],
    *,
    priority: tuple[str, ...] = SECTION_TITLE_PRIORITY,
    limit: int = 4,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for wanted in priority:
        for row in sections:
            title = str(row.get("title") or "")
            if title.lower() == wanted.lower() and row not in matched:
                matched.append(row)
    if matched:
        return matched[:limit]
    return sections[: min(2, limit)]


def fetch_bulbapedia_evidence(
    *,
    answer_key: str,
    answer_display: str,
    source_type: str,
    canonical_slug: str | None,
    structured_facts: dict[str, Any] | None,
    cache_dir: Path,
    cache_only: bool = False,
    timeout_seconds: float = 6.0,
    request_delay_seconds: float = 0.0,
    second_pass: bool = False,
) -> dict[str, Any]:
    cached = load_cached_evidence(cache_dir, answer_key, second_pass=second_pass)
    if cached is not None and not _cached_requires_refetch(
        cached,
        answer_display=answer_display,
        canonical_slug=canonical_slug,
        source_type=source_type,
    ):
        return cached
    if cache_only:
        return {
            "answerKey": _normalize_answer(answer_key),
            "answerDisplay": answer_display,
            "sourceType": source_type,
            "status": "cache_miss",
            "passMode": "second_pass" if second_pass else "first_pass",
            "titleCandidates": title_candidates(answer_display, source_type, canonical_slug),
            "sections": [],
        }

    title = ""
    metadata: dict[str, Any] | None = None
    candidates = title_candidates(answer_display, source_type, canonical_slug)
    for candidate in candidates:
        metadata = resolve_page_metadata(candidate, timeout_seconds)
        if metadata:
            title = str(metadata.get("title") or candidate)
            break
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    if not metadata or not title:
        accepted_keys = _accepted_search_keys(answer_display, canonical_slug, source_type)
        for query in _title_search_queries(answer_display, source_type, canonical_slug, candidates):
            for matched_title in search_page_titles(query, timeout_seconds):
                if _normalize_answer(_strip_parenthetical_suffix(matched_title)) not in accepted_keys:
                    continue
                metadata = resolve_page_metadata(matched_title, timeout_seconds)
                if metadata:
                    title = str(metadata.get("title") or matched_title)
                    break
                if request_delay_seconds > 0:
                    time.sleep(request_delay_seconds)
            if metadata and title:
                break

    if not metadata or not title:
        payload = {
            "answerKey": _normalize_answer(answer_key),
            "answerDisplay": answer_display,
            "sourceType": source_type,
            "status": "not_found",
            "titleCandidates": candidates,
            "sections": [],
        }
        path = cache_path(cache_dir, answer_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return payload

    lead_text = fetch_lead_text(title, timeout_seconds)
    sections = fetch_sections(title, timeout_seconds)
    selected_sections: list[dict[str, Any]] = []
    section_priority = SECOND_PASS_SECTION_TITLE_PRIORITY if second_pass else SECTION_TITLE_PRIORITY
    limit = 6 if second_pass else 4
    for row in _selected_section_rows(sections, priority=section_priority, limit=limit):
        text = fetch_section_text(title, str(row["index"]), timeout_seconds)
        if text:
            selected_sections.append({"title": row["title"], "text": text})
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    family_pages: list[dict[str, Any]] = []
    combined_evidence_length = len(lead_text) + sum(len(str(row.get("text") or "")) for row in selected_sections)
    if second_pass and source_type == "item" and combined_evidence_length < 900:
        for family_title in _item_family_page_titles(answer_display, structured_facts):
            family_metadata = resolve_page_metadata(family_title, timeout_seconds)
            if not family_metadata:
                continue
            family_page_title = str(family_metadata.get("title") or family_title)
            family_sections = fetch_sections(family_page_title, timeout_seconds)
            collected_sections: list[dict[str, Any]] = []
            for row in _selected_section_rows(family_sections, priority=section_priority, limit=3):
                text = fetch_section_text(family_page_title, str(row["index"]), timeout_seconds)
                if text:
                    collected_sections.append({"title": row["title"], "text": text, "sourcePageTitle": family_page_title})
                if request_delay_seconds > 0:
                    time.sleep(request_delay_seconds)
            if collected_sections:
                family_pages.append(
                    {
                        "pageTitle": family_page_title,
                        "pageUrl": family_metadata.get("fullUrl") or f"https://bulbapedia.bulbagarden.net/wiki/{quote(family_page_title.replace(' ', '_'))}",
                        "sections": collected_sections,
                    }
                )
                selected_sections.extend(collected_sections)

    payload = {
        "answerKey": _normalize_answer(answer_key),
        "answerDisplay": answer_display,
        "sourceType": source_type,
        "evidenceVersion": EVIDENCE_VERSION,
        "passMode": "second_pass" if second_pass else "first_pass",
        "status": "ok",
        "pageTitle": title,
        "pageUrl": metadata.get("fullUrl") or f"https://bulbapedia.bulbagarden.net/wiki/{quote(title.replace(' ', '_'))}",
        "pageId": metadata.get("pageId"),
        "pageRevisionId": metadata.get("lastRevid"),
        "leadText": lead_text,
        "sections": selected_sections,
        "familyPages": family_pages,
        "titleCandidates": candidates,
        "updatedAt": int(time.time()),
    }
    path = cache_path(cache_dir, answer_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def fallback_structured_facts(answer_row: dict[str, Any], payload: dict[str, Any] | None) -> dict[str, Any]:
    source_ref = str(answer_row.get("sourceRef") or "")
    source_type = str(answer_row.get("sourceType") or "")
    parsed_source_type, source_id = _parse_source_ref(source_ref)
    final_source_type = parsed_source_type or source_type
    facts: dict[str, Any] = {"sourceType": final_source_type, "sourceId": source_id}
    if not isinstance(payload, dict):
        return facts

    if final_source_type == "pokemon-species":
        genus = next(
            (
                _clean_text(str(row.get("genus") or ""))
                for row in payload.get("genera", [])
                if isinstance(row, dict) and row.get("language", {}).get("name") == "en"
            ),
            "",
        )
        if genus:
            facts["genus"] = genus
        generation = payload.get("generation")
        if isinstance(generation, dict):
            facts["generation"] = str(generation.get("name") or "")
            facts["generationLabel"] = _generation_display_name(str(generation.get("name") or ""))
        color = payload.get("color")
        if isinstance(color, dict):
            facts["color"] = _clean_text(str(color.get("name") or ""))
        egg_groups = payload.get("egg_groups")
        if isinstance(egg_groups, list):
            facts["eggGroups"] = [
                _clean_text(str(group.get("name") or ""))
                for group in egg_groups
                if isinstance(group, dict) and str(group.get("name") or "").strip()
            ]
    elif final_source_type in {"move", "ability", "item", "type"}:
        generation = payload.get("generation")
        if isinstance(generation, dict):
            facts["generation"] = str(generation.get("name") or "")
            facts["generationLabel"] = _generation_display_name(str(generation.get("name") or ""))
        effect_entries = payload.get("effect_entries")
        if isinstance(effect_entries, list):
            for row in effect_entries:
                if not isinstance(row, dict):
                    continue
                if row.get("language", {}).get("name") != "en":
                    continue
                text = _clean_text(str(row.get("short_effect") or row.get("effect") or ""))
                if text:
                    facts["effect"] = text
                    break
        if final_source_type == "move":
            move_type = payload.get("type")
            if isinstance(move_type, dict):
                facts["moveType"] = _clean_text(str(move_type.get("name") or "")).title()
            damage_class = payload.get("damage_class")
            if isinstance(damage_class, dict):
                facts["damageClass"] = _clean_text(str(damage_class.get("name") or "")).title()
            if isinstance(payload.get("power"), int):
                facts["power"] = int(payload["power"])
            if isinstance(payload.get("accuracy"), int):
                facts["accuracy"] = int(payload["accuracy"])
            if isinstance(payload.get("priority"), int):
                facts["priority"] = int(payload["priority"])
        elif final_source_type == "ability":
            facts["isMainSeries"] = bool(payload.get("is_main_series", True))
        elif final_source_type == "item":
            category = payload.get("category")
            if isinstance(category, dict):
                facts["category"] = _clean_text(str(category.get("name") or "")).replace("-", " ")
    elif final_source_type in {"location", "location-area"}:
        region = payload.get("region")
        if isinstance(region, dict):
            facts["region"] = str(region.get("name") or "")
            facts["regionDisplay"] = _clean_text(str(region.get("name") or "")).title()
    return facts
