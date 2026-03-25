from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

from crossword.answer_metadata import build_answer_metadata, load_payload_name_index, load_word_metadata, normalize_answer
from crossword.bulbapedia_evidence import fallback_structured_facts, fetch_bulbapedia_evidence
from crossword.clue_bank import load_payload_index
from crossword.clue_candidate_qa import score_candidate
from crossword.clue_curator_local import curate_clues_locally
from crossword.external_clue_sources import (
    FetchResult,
    extract_candidate_sentences,
    fetch_pokemondb_description,
    fetch_serebii_description,
    pokemondb_url_candidates,
    refine_provider_extract,
    sanitize_external_candidate,
    serebii_url_candidates,
)


PROVIDER_ORDER = ("bulbapedia", "serebii", "pokemondb")
HTML_PROVIDER_FETCHERS = {
    "serebii": fetch_serebii_description,
    "pokemondb": fetch_pokemondb_description,
}
HTML_PROVIDER_URLS = {
    "serebii": serebii_url_candidates,
    "pokemondb": pokemondb_url_candidates,
}


def _result_path(cache_dir: Path, answer_key: str) -> Path:
    return cache_dir / f"{str(answer_key or '').upper()}.json"


def load_provider_result(cache_dir: Path, answer_key: str) -> dict[str, Any] | None:
    path = _result_path(cache_dir, answer_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def write_provider_result(cache_dir: Path, payload: dict[str, Any]) -> dict[str, Any]:
    answer_key = str(payload.get("answerKey") or "").upper()
    path = _result_path(cache_dir, answer_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload


def load_answer_queue(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        first_row = next(reader, None)
        if first_row is None:
            return []
        use_header = str(first_row[0] if first_row else "").strip().lower() == "answer"
        rows = reader if use_header else [first_row, *reader]
        seen: set[str] = set()
        ordered: list[dict[str, str]] = []
        for row in rows:
            if not row:
                continue
            answer_display = str(row[0] or "").strip().upper()
            answer_key = normalize_answer(answer_display)
            if not answer_key or answer_key in seen:
                continue
            seen.add(answer_key)
            ordered.append({"answerKey": answer_key, "answerDisplay": answer_display})
        return ordered


def select_next_answer(csv_path: Path, processed_answer_keys: set[str]) -> dict[str, str] | None:
    for row in load_answer_queue(csv_path):
        if row["answerKey"] not in processed_answer_keys:
            return row
    return None


def build_bulbapedia_candidate_pool(
    *,
    answer_display: str,
    evidence: dict[str, Any] | None,
    curated: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    response = curated.get("response") if isinstance(curated, dict) else None
    candidates = response.get("crossword_candidates") if isinstance(response, dict) else None
    confidence = response.get("confidence") if isinstance(response, dict) else 0.0

    if not isinstance(candidates, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, row in enumerate(candidates, start=1):
        if not isinstance(row, dict):
            continue
        clue = str(row.get("text") or "").strip()
        if not clue:
            continue
        key = clue.upper()
        if key in seen:
            continue
        seen.add(key)
        score, flags, approved = score_candidate(
            text=clue,
            answer_display=answer_display,
            evidence=evidence,
            evidence_ref=str(row.get("evidence_ref") or ""),
            style="agent_curated",
            agent_confidence=float(confidence or 0.0),
            mystery_score=float(row.get("mystery_score") or 0.0),
            specificity_score=float(row.get("specificity_score") or 0.0),
        )
        out.append(
            {
                "provider": "bulbapedia",
                "status": "ok",
                "clue": clue,
                "score": score,
                "approved": approved,
                "qualityFlags": flags,
                "evidenceRef": str(row.get("evidence_ref") or ""),
                "sourceUrl": str((evidence or {}).get("pageUrl") or ""),
                "extract": str((evidence or {}).get("leadText") or ""),
                "rankPosition": idx,
                "style": str(row.get("style") or "agent_curated"),
            }
        )

    out.sort(key=lambda row: (0 if bool(row.get("approved", False)) else 1, -float(row.get("score") or 0.0), str(row.get("clue") or "")))
    return out


def _bulbapedia_best_candidate(
    *,
    answer_display: str,
    evidence: dict[str, Any] | None,
    curated: dict[str, Any] | None,
) -> dict[str, Any]:
    candidates = build_bulbapedia_candidate_pool(
        answer_display=answer_display,
        evidence=evidence,
        curated=curated,
    )
    if candidates:
        return candidates[0]
    return {
        "status": "no_candidates",
        "provider": "bulbapedia",
        "clue": "",
        "score": 0.0,
        "approved": False,
        "qualityFlags": ["no_candidates"],
    }


def generate_bulbapedia_clue(
    *,
    answer_row: dict[str, Any],
    structured_facts: dict[str, Any],
    cache_dir: Path,
    evidence_cache_dir: Path,
    curator_cache_dir: Path,
    cache_only: bool = False,
    timeout_seconds: float = 8.0,
    request_delay_seconds: float = 0.0,
    evidence: dict[str, Any] | None = None,
    curated: dict[str, Any] | None = None,
) -> dict[str, Any]:
    answer_key = str(answer_row.get("answerKey") or "").upper()
    cached = load_provider_result(cache_dir, answer_key)
    if cached is not None and cached.get("status") == "ok" and evidence is None and curated is None:
        return {"result": cached, "evidence": evidence, "curated": curated}

    metadata = build_answer_metadata(answer_row)
    evidence = evidence or fetch_bulbapedia_evidence(
        answer_key=answer_key,
        answer_display=str(answer_row.get("answerDisplay") or ""),
        source_type=str(metadata.get("sourceType") or ""),
        canonical_slug=str(metadata.get("canonicalSlug") or ""),
        structured_facts=structured_facts,
        cache_dir=evidence_cache_dir,
        cache_only=cache_only,
        timeout_seconds=timeout_seconds,
        request_delay_seconds=request_delay_seconds,
    )
    curated = curated or curate_clues_locally(
        answer_row=answer_row,
        evidence=evidence,
        structured_facts=structured_facts,
        cache_dir=curator_cache_dir,
    )

    best = _bulbapedia_best_candidate(
        answer_display=str(answer_row.get("answerDisplay") or ""),
        evidence=evidence,
        curated=curated,
    )
    result = {
        "answerKey": answer_key,
        "answerDisplay": str(answer_row.get("answerDisplay") or "").upper(),
        "provider": "bulbapedia",
        "status": str(best.get("status") or "no_candidates"),
        "clue": str(best.get("clue") or ""),
        "score": float(best.get("score") or 0.0),
        "approved": bool(best.get("approved", False)),
        "qualityFlags": list(best.get("qualityFlags") or []),
        "evidenceRef": str(best.get("evidenceRef") or ""),
        "sourceUrl": str(best.get("sourceUrl") or ""),
        "extract": str(best.get("extract") or ""),
        "updatedAt": int(time.time()),
    }
    write_provider_result(cache_dir, result)
    return {"result": result, "evidence": evidence, "curated": curated}


def _score_html_provider_candidate(
    *,
    provider: str,
    clue: str,
    answer_display: str,
    extract: str,
) -> tuple[float, list[str], bool]:
    agent_confidence = 0.58 if provider == "serebii" else 0.56
    mystery_score = 0.48 if provider == "serebii" else 0.44
    specificity_score = 0.54 if provider == "serebii" else 0.5
    return score_candidate(
        text=clue,
        answer_display=answer_display,
        evidence={"leadText": extract, "sections": []},
        evidence_ref="lead",
        style="agent_curated",
        agent_confidence=agent_confidence,
        mystery_score=mystery_score,
        specificity_score=specificity_score,
    )


def generate_html_provider_clue(
    *,
    provider: str,
    answer_row: dict[str, Any],
    cache_dir: Path,
    cache_only: bool = False,
    timeout_seconds: float = 8.0,
    request_delay_seconds: float = 0.0,
) -> dict[str, Any]:
    answer_key = str(answer_row.get("answerKey") or "").upper()
    cached = load_provider_result(cache_dir, answer_key)
    if cached is not None and cached.get("status") == "ok":
        return cached
    if cache_only:
        result = {
            "answerKey": answer_key,
            "answerDisplay": str(answer_row.get("answerDisplay") or "").upper(),
            "provider": provider,
            "status": "cache_miss",
            "clue": "",
            "score": 0.0,
            "approved": False,
            "qualityFlags": ["cache_miss"],
            "evidenceRef": "",
            "sourceUrl": "",
            "extract": "",
            "updatedAt": int(time.time()),
        }
        write_provider_result(cache_dir, result)
        return result

    metadata = build_answer_metadata(answer_row)
    answer_display = str(answer_row.get("answerDisplay") or "").upper()
    source_type = str(metadata.get("sourceType") or "")
    canonical_slug = str(metadata.get("canonicalSlug") or "")
    url_candidates = HTML_PROVIDER_URLS[provider](answer_display, source_type, canonical_slug)
    fetcher = HTML_PROVIDER_FETCHERS[provider]
    last_fetch: FetchResult | None = None
    best: dict[str, Any] | None = None
    best_sort_key: tuple[int, float] | None = None

    for url in url_candidates:
        fetch = fetcher(url, timeout_seconds)
        last_fetch = fetch
        if fetch.status != "ok" or not fetch.extract:
            if request_delay_seconds > 0:
                time.sleep(request_delay_seconds)
            continue
        refined_extract = refine_provider_extract(fetch.extract, answer_display)
        for idx, sentence in enumerate(extract_candidate_sentences(refined_extract, max_sentences=4), start=1):
            cleaned = sanitize_external_candidate(sentence, answer_display, source_type)
            if not cleaned:
                continue
            score, flags, approved = _score_html_provider_candidate(
                provider=provider,
                clue=cleaned,
                answer_display=answer_display,
                extract=refined_extract,
            )
            candidate = {
                "answerKey": answer_key,
                "answerDisplay": answer_display,
                "provider": provider,
                "status": "ok",
                "clue": cleaned,
                "score": score,
                "approved": approved,
                "qualityFlags": flags,
                "evidenceRef": "lead",
                "sourceUrl": url,
                "extract": refined_extract,
                "rankPosition": idx,
                "updatedAt": int(time.time()),
            }
            sort_key = (1 if approved else 0, score)
            if best is None or sort_key > best_sort_key:
                best = candidate
                best_sort_key = sort_key
        if best is not None:
            break
        if request_delay_seconds > 0:
            time.sleep(request_delay_seconds)

    if best is None:
        result = {
            "answerKey": answer_key,
            "answerDisplay": answer_display,
            "provider": provider,
            "status": "unusable_extract" if last_fetch and last_fetch.status == "ok" else str((last_fetch or {}).status if last_fetch else "not_found"),
            "clue": "",
            "score": 0.0,
            "approved": False,
            "qualityFlags": ["no_usable_candidate"],
            "evidenceRef": "",
            "sourceUrl": str(last_fetch.url if last_fetch else ""),
            "extract": str(refine_provider_extract(last_fetch.extract, answer_display) if last_fetch and last_fetch.extract else ""),
            "updatedAt": int(time.time()),
        }
        write_provider_result(cache_dir, result)
        return result

    write_provider_result(cache_dir, best)
    return best


def generate_provider_clue(
    *,
    provider: str,
    answer_row: dict[str, Any],
    structured_facts: dict[str, Any] | None = None,
    cache_dir: Path,
    evidence_cache_dir: Path | None = None,
    curator_cache_dir: Path | None = None,
    cache_only: bool = False,
    timeout_seconds: float = 8.0,
    request_delay_seconds: float = 0.0,
    evidence: dict[str, Any] | None = None,
    curated: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if provider == "bulbapedia":
        if evidence_cache_dir is None or curator_cache_dir is None:
            raise ValueError("bulbapedia provider requires evidence_cache_dir and curator_cache_dir")
        return generate_bulbapedia_clue(
            answer_row=answer_row,
            structured_facts=structured_facts or {},
            cache_dir=cache_dir,
            evidence_cache_dir=evidence_cache_dir,
            curator_cache_dir=curator_cache_dir,
            cache_only=cache_only,
            timeout_seconds=timeout_seconds,
            request_delay_seconds=request_delay_seconds,
            evidence=evidence,
            curated=curated,
        )["result"]
    return generate_html_provider_clue(
        provider=provider,
        answer_row=answer_row,
        cache_dir=cache_dir,
        cache_only=cache_only,
        timeout_seconds=timeout_seconds,
        request_delay_seconds=request_delay_seconds,
    )


def generate_next_provider_clue(
    *,
    provider: str,
    input_csv: Path,
    wordlist_json: Path,
    pokeapi_cache_dir: Path,
    cache_dir: Path,
    evidence_cache_dir: Path | None = None,
    curator_cache_dir: Path | None = None,
    cache_only: bool = False,
    timeout_seconds: float = 8.0,
    request_delay_seconds: float = 0.0,
) -> dict[str, Any] | None:
    processed_answer_keys = {path.stem.upper() for path in cache_dir.glob("*.json")}
    next_row = select_next_answer(input_csv, processed_answer_keys)
    if next_row is None:
        return None

    payload_name_index = load_payload_name_index(pokeapi_cache_dir)
    metadata_by_answer = load_word_metadata(wordlist_json, payload_name_index)
    payload_index = load_payload_index(pokeapi_cache_dir)
    metadata = metadata_by_answer.get(next_row["answerKey"], {})
    answer_row = {
        "answerKey": next_row["answerKey"],
        "answerDisplay": next_row["answerDisplay"],
        "sourceType": str(metadata.get("sourceType") or ""),
        "sourceRef": str(metadata.get("sourceRef") or ""),
        "sourceSlug": str(metadata.get("canonicalSlug") or ""),
    }
    parsed_type = str(metadata.get("sourceType") or "")
    source_id = metadata.get("sourceId")
    payload = payload_index.get((parsed_type, source_id)) if isinstance(source_id, int) else None
    structured_facts = fallback_structured_facts(answer_row, payload)
    result = generate_provider_clue(
        provider=provider,
        answer_row=answer_row,
        structured_facts=structured_facts,
        cache_dir=cache_dir,
        evidence_cache_dir=evidence_cache_dir,
        curator_cache_dir=curator_cache_dir,
        cache_only=cache_only,
        timeout_seconds=timeout_seconds,
        request_delay_seconds=request_delay_seconds,
    )
    return result
