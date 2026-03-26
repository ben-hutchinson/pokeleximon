from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import re
import sys
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.answer_metadata import load_payload_name_index, load_word_metadata, normalize_answer  # noqa: E402
from crossword.bulbapedia_evidence import fallback_structured_facts, fetch_bulbapedia_evidence  # noqa: E402
from crossword.clue_bank import load_payload_index  # noqa: E402
from crossword.clue_candidate_qa import pairwise_similarity, score_candidate  # noqa: E402
from crossword.clue_curator_local import curate_clues_locally  # noqa: E402


ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue_draft.csv"
DEFAULT_OUTPUT_REPORT = ROOT_DIR / "data" / "wordlist_crossword_answer_clue_draft_report.json"
DEFAULT_WORDLIST_JSON = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_PAYLOAD_CACHE_DIR = ROOT_DIR / "services" / "data" / "pokeapi"
DEFAULT_EVIDENCE_CACHE_DIR = ROOT_DIR / "data" / "bulbapedia_evidence"
DEFAULT_LOCAL_CURATOR_CACHE_DIR = ROOT_DIR / "data" / "bulbapedia_clue_agent"
DEFAULT_DRAFT_AGENT_CACHE_DIR = ROOT_DIR / "data" / "bulbapedia_clue_agent_draft"

DRAFT_PROMPT_VERSION = "draft-quality-v1"
SIMILARITY_THRESHOLD = 0.74

DRAFT_EDITORIAL_GUIDE: dict[str, Any] = {
    "goal": "Produce short, fair, specific Pokemon crossword clues modeled on strong manual editorial clues.",
    "positivePatterns": [
        "Use short clue-like noun phrases or compact clauses, usually 2-7 words.",
        "Anchor each clue in one concrete Bulbapedia fact: evolution, route, replacement, effect, genus title, lore, or restriction.",
        "Prefer memorable hooks over raw stats or database phrasing.",
        "Vary clue angles for the same answer instead of repeating taxonomy.",
        "Use official in-universe labels when they are distinctive, such as species titles ending in Pokemon.",
        "Allow concise taxonomy only when it materially narrows the answer.",
    ],
    "antiPatterns": [
        "Do not lead with raw statline clues for species.",
        "Avoid empty category labels like Town in Unova, Held battle item, or boosting move.",
        "Avoid generic taxonomic sludge that reads like a database field.",
        "Do not copy Bulbapedia wording verbatim.",
        "Do not leak the answer or obvious answer fragments.",
        "Do not give multiple clues for the same answer that use the same angle with trivial wording changes.",
    ],
    "exampleUpgrades": [
        {"weak": "92 Attack, 60 Speed species", "better": "Frost Tree Pokemon"},
        {"weak": "20 Attack, 90 Speed species", "better": "Constantly teleporting"},
        {"weak": "130 Attack, 75 Speed species", "better": "Can foretell natural disasters"},
        {"weak": "70 Attack, 145 Speed species", "better": "Evolves from Shelmet on trade"},
        {"weak": "boosting move", "better": "Gen I Poison move increasing Defense"},
        {"weak": "poisoning move", "better": "40 base power Poison move"},
        {"weak": "Town in Unova", "better": "First encounter location of Team Plasma and N"},
        {"weak": "Unova town", "better": "Meeting place with Professor Juniper"},
        {"weak": "Held battle item", "better": "Doubles prize money"},
        {"weak": "Ungrounding held item", "better": "Blocks Ground-type moves"},
        {"weak": "Makes a regular trait rarer", "better": "Only for species with Hidden Abilities"},
    ],
    "outputRequirements": [
        "Return 3 to 6 clue candidates.",
        "Each clue should rely on a distinct fact or angle where possible.",
        "Prefer clue surfaces that a knowledgeable Pokemon player can solve without the clue feeling like a database dump.",
    ],
}

DRAFT_QUALITY_PENALTIES: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (re.compile(r"(?i)^\d+\s+Attack,\s*\d+\s+Speed\s+species$"), "raw_statline_species", 26.0),
    (re.compile(r"(?i)^\d+\s+Attack(?:,\s*\d+\s+Speed)?\b.*\bspecies$"), "raw_statline_species", 22.0),
    (
        re.compile(
            r"(?i)^(town|city|village|landmark|route|cave|bay|forest|gate|meadow|mountain|lake|ruins|road|path|trail)\s+in\s+[a-z][a-z' -]+$"
        ),
        "generic_location_label",
        24.0,
    ),
    (
        re.compile(
            r"(?i)^[a-z][a-z' -]+\s+(town|city|village|landmark|route|cave|bay|forest|gate|meadow|mountain|lake|ruins|road|path|trail)$"
        ),
        "generic_location_label",
        18.0,
    ),
    (re.compile(r"(?i)^regional\s+(town|city|village|landmark|location|route|cave|bay|forest|gate|road|path|trail|ruins)$"), "regional_label", 24.0),
    (re.compile(r"(?i)^held battle item$"), "generic_item_label", 28.0),
    (re.compile(r"(?i)\bcurrently in battle\b"), "source_parse_artifact", 40.0),
    (re.compile(r"(?i)\bby-only\b"), "source_parse_artifact", 40.0),
    (
        re.compile(r"(?i)^(boosting|debuffing|poisoning|draining|healing|priority|switching|protective|flinch-causing)\s+(move|item|trait|ability)$"),
        "generic_effect_label",
        24.0,
    ),
    (re.compile(r"(?i)^[a-z]+ egg-group species$"), "egg_group_taxonomy", 18.0),
    (re.compile(r"(?i)^(brown|black|white|gray|grey|blue|yellow|red|golden)\s+gen\s+[ivx]+\s+.+\sspecies$"), "color_taxonomy", 14.0),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a Bulbapedia-grounded draft crossword clue CSV without touching runtime data.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_OUTPUT_REPORT)
    parser.add_argument("--wordlist-json", type=Path, default=DEFAULT_WORDLIST_JSON)
    parser.add_argument("--payload-cache-dir", type=Path, default=DEFAULT_PAYLOAD_CACHE_DIR)
    parser.add_argument("--evidence-cache-dir", type=Path, default=DEFAULT_EVIDENCE_CACHE_DIR)
    parser.add_argument("--local-curator-cache-dir", type=Path, default=DEFAULT_LOCAL_CURATOR_CACHE_DIR)
    parser.add_argument("--draft-agent-cache-dir", type=Path, default=DEFAULT_DRAFT_AGENT_CACHE_DIR)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--answers", nargs="*", default=[])
    parser.add_argument("--min-clues", type=int, default=2)
    parser.add_argument("--max-clues", type=int, default=5)
    parser.add_argument("--quality-threshold", type=float, default=86.0)
    parser.add_argument("--bulbapedia-timeout-seconds", type=float, default=8.0)
    parser.add_argument("--agent-timeout-seconds", type=float, default=40.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.0)
    parser.add_argument("--model", type=str, default="")
    parser.add_argument("--use-openai-agent", action="store_true")
    return parser.parse_args()


def _load_source_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            return rows
        clue_columns = max(len(header) - 1, 0)
        for raw in reader:
            if not raw:
                continue
            answer_display = str(raw[0] or "").strip().upper()
            if not answer_display:
                continue
            clues = [str(value or "").strip() for value in raw[1 : 1 + clue_columns] if str(value or "").strip()]
            rows.append(
                {
                    "answerKey": normalize_answer(answer_display),
                    "answerDisplay": answer_display,
                    "existingClues": clues,
                }
            )
    return rows


def _draft_quality_delta(text: str) -> tuple[float, list[str]]:
    flags: list[str] = []
    penalty = 0.0
    cleaned = " ".join(str(text or "").split()).strip()
    for pattern, label, amount in DRAFT_QUALITY_PENALTIES:
        if pattern.search(cleaned):
            flags.append(label)
            penalty += amount
    return -penalty, flags


def _candidate_row(
    *,
    text: str,
    answer_display: str,
    evidence: dict[str, Any] | None,
    evidence_ref: str,
    style: str,
    source: str,
    agent_confidence: float,
    mystery_score: float,
    specificity_score: float,
) -> dict[str, Any]:
    base_score, qa_flags, approved = score_candidate(
        text=text,
        answer_display=answer_display,
        evidence=evidence,
        evidence_ref=evidence_ref,
        style=style,
        agent_confidence=agent_confidence,
        mystery_score=mystery_score,
        specificity_score=specificity_score,
    )
    delta, editorial_flags = _draft_quality_delta(text)
    adjusted_score = round(max(base_score + delta, 0.0), 2)
    return {
        "text": text,
        "evidenceRef": evidence_ref,
        "style": style,
        "source": source,
        "baseScore": base_score,
        "adjustedScore": adjusted_score,
        "approved": approved,
        "qaFlags": sorted(set(qa_flags)),
        "editorialFlags": sorted(set(editorial_flags)),
        "agentConfidence": round(float(agent_confidence or 0.0), 3),
        "mysteryScore": round(float(mystery_score or 0.0), 3),
        "specificityScore": round(float(specificity_score or 0.0), 3),
    }


def _extract_curated_candidates(
    payload: dict[str, Any] | None,
    *,
    answer_display: str,
    evidence: dict[str, Any] | None,
    source: str,
) -> list[dict[str, Any]]:
    response = payload.get("response") if isinstance(payload, dict) else None
    candidates = response.get("crossword_candidates") if isinstance(response, dict) else None
    confidence = float(response.get("confidence") or 0.0) if isinstance(response, dict) else 0.0
    if not isinstance(candidates, list):
        return []

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in candidates:
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get("text") or "").split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            _candidate_row(
                text=text,
                answer_display=answer_display,
                evidence=evidence,
                evidence_ref=str(row.get("evidence_ref") or "lead"),
                style=str(row.get("style") or "agent_curated"),
                source=source,
                agent_confidence=confidence,
                mystery_score=float(row.get("mystery_score") or 0.0),
                specificity_score=float(row.get("specificity_score") or 0.0),
            )
        )
    return out


def _extract_existing_csv_candidates(
    existing_clues: list[str],
    *,
    answer_display: str,
    evidence: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for clue in existing_clues:
        text = " ".join(str(clue or "").split()).strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(
            _candidate_row(
                text=text,
                answer_display=answer_display,
                evidence=evidence,
                evidence_ref="lead",
                style="manual_override",
                source="existing_csv",
                agent_confidence=0.82,
                mystery_score=0.78,
                specificity_score=0.82,
            )
        )
    return out


def _source_priority(source: str) -> int:
    return {
        "draft_agent": 0,
        "local_curator": 1,
        "existing_csv": 2,
    }.get(str(source or ""), 9)


def _candidate_sort_key(row: dict[str, Any], quality_threshold: float) -> tuple[int, float, int, str]:
    is_high_quality = bool(row.get("approved")) and float(row.get("adjustedScore") or 0.0) >= quality_threshold
    return (
        0 if is_high_quality else 1,
        -float(row.get("adjustedScore") or 0.0),
        _source_priority(str(row.get("source") or "")),
        str(row.get("text") or ""),
    )


def _select_distinct_candidates(
    candidates: list[dict[str, Any]],
    *,
    min_clues: int,
    max_clues: int,
    quality_threshold: float,
) -> list[dict[str, Any]]:
    medium_threshold = max(80.0, float(quality_threshold) - 6.0)
    ordered = sorted(candidates, key=lambda row: _candidate_sort_key(row, quality_threshold))
    selected: list[dict[str, Any]] = []
    selected_texts: set[str] = set()

    def maybe_add(candidate: dict[str, Any]) -> bool:
        text = str(candidate.get("text") or "").strip()
        if not text:
            return False
        lowered = text.lower()
        if lowered in selected_texts:
            return False
        if any(pairwise_similarity(text, existing["text"]) >= SIMILARITY_THRESHOLD for existing in selected):
            return False
        selected.append(candidate)
        selected_texts.add(lowered)
        return len(selected) >= max_clues

    for predicate in (
        lambda row: bool(row.get("approved")) and float(row.get("adjustedScore") or 0.0) >= quality_threshold,
        lambda row: bool(row.get("approved")) and float(row.get("adjustedScore") or 0.0) >= medium_threshold,
        lambda row: len(selected) < min_clues and bool(row.get("approved")),
        lambda row: len(selected) < min_clues,
    ):
        for candidate in ordered:
            if not predicate(candidate):
                continue
            if maybe_add(candidate):
                return selected
    return selected


def _high_quality_count(candidates: list[dict[str, Any]], *, quality_threshold: float) -> int:
    return sum(1 for row in candidates if bool(row.get("approved")) and float(row.get("adjustedScore") or 0.0) >= quality_threshold)


def _write_csv(path: Path, rows: list[tuple[str, ...]], max_clues: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    header = ("answer",) + tuple(f"clue {index}" for index in range(1, max_clues + 1))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _build_answer_row(answer_display: str, metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "answerKey": normalize_answer(answer_display),
        "answerDisplay": answer_display,
        "sourceType": str(metadata.get("sourceType") or ""),
        "sourceRef": str(metadata.get("sourceRef") or ""),
        "sourceSlug": str(metadata.get("canonicalSlug") or ""),
    }


def main() -> None:
    args = parse_args()
    source_rows = _load_source_rows(args.input_csv)
    if args.answers:
        wanted = {normalize_answer(value) for value in args.answers if str(value).strip()}
        source_rows = [row for row in source_rows if row["answerKey"] in wanted]
    if args.limit > 0:
        source_rows = source_rows[: int(args.limit)]

    payload_name_index = load_payload_name_index(args.payload_cache_dir)
    word_metadata = load_word_metadata(args.wordlist_json, payload_name_index=payload_name_index)
    payload_index = load_payload_index(args.payload_cache_dir)

    output_rows: list[tuple[str, ...]] = []
    answers_below_min: list[str] = []
    selection_source_counts: Counter[str] = Counter()
    evidence_status_counts: Counter[str] = Counter()
    evidence_pass_mode_counts: Counter[str] = Counter()
    agent_status_counts: Counter[str] = Counter()
    answer_source_counts: Counter[str] = Counter()

    for source_row in source_rows:
        answer_display = str(source_row["answerDisplay"] or "").strip().upper()
        answer_key = str(source_row["answerKey"] or "").upper()
        metadata = word_metadata.get(answer_key, {})
        answer_row = _build_answer_row(answer_display, metadata)

        source_type = str(answer_row.get("sourceType") or "")
        source_id = metadata.get("sourceId")
        payload = payload_index.get((source_type, source_id)) if isinstance(source_id, int) else None
        structured_facts = fallback_structured_facts(answer_row, payload)

        evidence = fetch_bulbapedia_evidence(
            answer_key=answer_key,
            answer_display=answer_display,
            source_type=source_type,
            canonical_slug=str(metadata.get("canonicalSlug") or ""),
            structured_facts=structured_facts,
            cache_dir=args.evidence_cache_dir,
            cache_only=args.cache_only,
            timeout_seconds=args.bulbapedia_timeout_seconds,
            request_delay_seconds=args.request_delay_seconds,
        )
        evidence_status_counts[str(evidence.get("status") or "unknown")] += 1
        evidence_pass_mode_counts[str(evidence.get("passMode") or "none")] += 1

        local_payload = curate_clues_locally(
            answer_row=answer_row,
            evidence=evidence,
            structured_facts=structured_facts,
            cache_dir=args.local_curator_cache_dir,
        )
        candidate_pool = _extract_curated_candidates(
            local_payload,
            answer_display=answer_display,
            evidence=evidence,
            source="local_curator",
        )

        local_selected = _select_distinct_candidates(
            candidate_pool,
            min_clues=args.min_clues,
            max_clues=args.max_clues,
            quality_threshold=args.quality_threshold,
        )

        agent_payload: dict[str, Any] | None = None
        if _high_quality_count(local_selected, quality_threshold=args.quality_threshold) < args.min_clues:
            if str(evidence.get("status") or "") == "ok" and str(evidence.get("passMode") or "") != "second_pass":
                second_pass_evidence = fetch_bulbapedia_evidence(
                    answer_key=answer_key,
                    answer_display=answer_display,
                    source_type=source_type,
                    canonical_slug=str(metadata.get("canonicalSlug") or ""),
                    structured_facts=structured_facts,
                    cache_dir=args.evidence_cache_dir,
                    cache_only=args.cache_only,
                    timeout_seconds=args.bulbapedia_timeout_seconds,
                    request_delay_seconds=args.request_delay_seconds,
                    second_pass=True,
                )
                if str(second_pass_evidence.get("status") or "") == "ok":
                    evidence = second_pass_evidence
                    local_payload = curate_clues_locally(
                        answer_row=answer_row,
                        evidence=evidence,
                        structured_facts=structured_facts,
                        cache_dir=args.local_curator_cache_dir,
                    )
                    candidate_pool = _extract_curated_candidates(
                        local_payload,
                        answer_display=answer_display,
                        evidence=evidence,
                        source="local_curator",
                    )

            if args.use_openai_agent:
                from crossword.clue_curator_agent import call_curator

                agent_payload = call_curator(
                    answer_row=answer_row,
                    evidence=evidence,
                    structured_facts=structured_facts,
                    cache_dir=args.draft_agent_cache_dir,
                    cache_only=args.cache_only,
                    timeout_seconds=args.agent_timeout_seconds,
                    model=args.model or None,
                    editorial_guide=DRAFT_EDITORIAL_GUIDE,
                    prompt_version=DRAFT_PROMPT_VERSION,
                )
                agent_status_counts[str(agent_payload.get("status") or "unknown")] += 1
                candidate_pool.extend(
                    _extract_curated_candidates(
                        agent_payload,
                        answer_display=answer_display,
                        evidence=evidence,
                        source="draft_agent",
                    )
                )

        selected = _select_distinct_candidates(
            candidate_pool,
            min_clues=args.min_clues,
            max_clues=args.max_clues,
            quality_threshold=args.quality_threshold,
        )

        if _high_quality_count(selected, quality_threshold=args.quality_threshold) < args.min_clues and source_row["existingClues"]:
            candidate_pool.extend(
                _extract_existing_csv_candidates(
                    list(source_row["existingClues"]),
                    answer_display=answer_display,
                    evidence=evidence,
                )
            )
            selected = _select_distinct_candidates(
                candidate_pool,
                min_clues=args.min_clues,
                max_clues=args.max_clues,
                quality_threshold=args.quality_threshold,
            )

        chosen_texts = [str(row.get("text") or "") for row in selected[: args.max_clues]]
        if len(chosen_texts) < args.min_clues:
            answers_below_min.append(answer_display)

        for candidate in selected[: args.max_clues]:
            selection_source_counts[str(candidate.get("source") or "unknown")] += 1
        if selected:
            answer_source_counts[str(selected[0].get("source") or "unknown")] += 1

        padded = tuple(chosen_texts + [""] * max(0, args.max_clues - len(chosen_texts)))
        output_rows.append((answer_display, *padded))

    report = {
        "promptVersion": DRAFT_PROMPT_VERSION,
        "inputAnswerCount": len(source_rows),
        "outputAnswerCount": len(output_rows),
        "minClues": int(args.min_clues),
        "maxClues": int(args.max_clues),
        "qualityThreshold": float(args.quality_threshold),
        "useOpenAIAgent": bool(args.use_openai_agent),
        "answersBelowMinCount": len(answers_below_min),
        "answersBelowMin": answers_below_min,
        "selectionSourceCounts": dict(selection_source_counts),
        "answerPrimarySourceCounts": dict(answer_source_counts),
        "evidenceStatusCounts": dict(evidence_status_counts),
        "evidencePassModeCounts": dict(evidence_pass_mode_counts),
        "agentStatusCounts": dict(agent_status_counts),
    }

    _write_csv(args.output_csv, output_rows, args.max_clues)
    _write_json(args.output_report, report)

    print(f"Draft rows written: {len(output_rows)}")
    print(f"Answers below minimum clue count: {len(answers_below_min)}")
    print(f"Primary selected clue sources: {dict(answer_source_counts)}")
    if agent_status_counts:
        print(f"Agent status counts: {dict(agent_status_counts)}")


if __name__ == "__main__":
    main()
