from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
DEFAULT_OUTPUT_CSV = DEFAULT_INPUT_CSV
DEFAULT_WORDLIST_JSON = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_OVERRIDES_CSV = ROOT_DIR / "data" / "crossword_clue_overrides.csv"
DEFAULT_CANDIDATES_CSV = ROOT_DIR / "data" / "crossword_clue_override_candidates.csv"
DEFAULT_QUALITY_REPORT_JSON = ROOT_DIR / "data" / "crossword_clue_quality_report.json"
SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")
TOKEN_RE = re.compile(r"[^A-Z0-9]")
WHITESPACE_RE = re.compile(r"\s+")

GENERIC_CLUE_PATTERNS = (
    re.compile(r"(?i)^location:\s*region\s"),
    re.compile(r"(?i)^type entry \(pok[eé]api\s+\d+\)\.?$"),
    re.compile(r"(?i)^pok[eé]api ref \d+\.?$"),
    re.compile(r"(?i)^.* item \(pok[eé]api item #\d+\)\.?$"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bpok[eé]mon term from the csv lexicon\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
    re.compile(r"(?i)^core[- ]series pok[eé]mon .*answer uses \d+ word"),
    re.compile(r"(?i)^pok[eé]mon .* clue with initials [A-Z]+ and \d+ total letters"),
    re.compile(r"(?i)^pok[eé]mon .* clue: ending letters"),
    re.compile(r"(?i)^pok[eé]mon .* entry with enumeration"),
    re.compile(r"(?i)^answer uses \d+ words? with lengths"),
)

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
DISALLOWED_PATTERNS = (
    re.compile(r"(?i)\bpok[eé]api\b"),
    re.compile(r"(?i)\bjapanese\b"),
    re.compile(r"(?i)\bfallback clue\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\bxxx\b"),
    re.compile(r"(?i)\bnew effect for this (move|item|ability|location|type)\b"),
    re.compile(r"(?i)\b(todo|tbd|lorem ipsum)\b"),
    re.compile(r"\*{3,}"),
    re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"),
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


@dataclass
class Metadata:
    source_type: str
    source_id: int | None
    source_ref: str
    canonical_slug: str


def _clean_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", str(text).replace("\n", " ").replace("\f", " ")).strip()


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


def _clue_contains_answer_fragment(clue: str, display_answer: str) -> bool:
    for fragment in _answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            return True
    return False


def _is_generic_or_low_quality(clue: str) -> bool:
    return bool(_clue_quality_reasons(clue=clue, display_answer=""))


def _clue_quality_reasons(*, clue: str, display_answer: str) -> list[str]:
    text = _clean_text(clue)
    if not text:
        return ["empty_clue"]

    reasons: list[str] = []
    if any(pattern.search(text) for pattern in DISALLOWED_PATTERNS):
        reasons.append("disallowed_pattern")
    if any(pattern.search(text) for pattern in GENERIC_CLUE_PATTERNS):
        reasons.append("generic_template")
    if any(pattern.search(text) for pattern in LOW_QUALITY_PATTERNS):
        reasons.append("low_quality_surface")
    if len(text) < 24:
        reasons.append("clue_too_short")
    if display_answer and _clue_contains_answer_fragment(text, display_answer):
        reasons.append("answer_fragment_leak")
    return reasons


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


def _record_score(record: dict[str, Any]) -> tuple[int, int, int]:
    variant = str(record.get("variant", ""))
    parts = record.get("parts")
    part_count = len(parts) if isinstance(parts, list) else 1
    return (VARIANT_PRIORITY.get(variant, 99), part_count, len(str(record.get("word", ""))))


def _display_answer(record: dict[str, Any]) -> str:
    parts = record.get("parts")
    if isinstance(parts, list) and parts:
        cleaned = [str(part).strip().upper() for part in parts if str(part).strip()]
        if cleaned:
            return " ".join(cleaned)
    return str(record.get("word", "")).strip().upper()


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


def _load_word_metadata(wordlist_path: Path, payload_name_index: dict[tuple[str, int], str]) -> dict[str, Metadata]:
    rows = json.loads(wordlist_path.read_text(encoding="utf-8"))
    best_by_answer: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        display_answer = _display_answer(row)
        if not display_answer:
            continue
        existing = best_by_answer.get(display_answer)
        if existing is None or _record_score(row) < _record_score(existing):
            best_by_answer[display_answer] = row

    output: dict[str, Metadata] = {}
    for answer, row in best_by_answer.items():
        source_ref = str(row.get("sourceRef") or "").strip()
        source_type = str(row.get("sourceType") or "").strip()
        parsed_type, source_id = _parse_source_ref(source_ref)
        final_type = parsed_type or source_type
        canonical_slug = ""
        if parsed_type and isinstance(source_id, int):
            canonical_slug = payload_name_index.get((parsed_type, source_id), "")
        output[answer] = Metadata(
            source_type=final_type,
            source_id=source_id,
            source_ref=source_ref,
            canonical_slug=canonical_slug,
        )
    return output


def _read_csv_rows(path: Path) -> list[tuple[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [tuple(row[:2]) for row in csv.reader(handle) if len(row) >= 2]


def _write_csv_rows(path: Path, rows: list[tuple[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows(rows)


def _ensure_overrides_file(path: Path) -> None:
    if path.exists():
        return
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["answer", "clue", "enabled", "notes"],
        )
        writer.writeheader()


def _read_overrides(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            answer = str(row.get("answer") or "").strip().upper()
            clue = str(row.get("clue") or "").strip()
            enabled = str(row.get("enabled") or "").strip().lower()
            if not answer or not clue:
                continue
            if enabled in {"0", "false", "no", "off"}:
                continue
            out[answer] = (clue, str(row.get("notes") or "").strip())
    return out


def _read_candidate_overrides(path: Path) -> dict[str, tuple[str, str]]:
    if not path.exists():
        return {}
    out: dict[str, tuple[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            answer = str(row.get("answer") or "").strip().upper()
            clue = str(row.get("manual_clue") or "").strip()
            if not answer or not clue:
                continue
            out[answer] = (clue, "candidate_manual_clue")
    return out


def _export_candidates(
    path: Path,
    unresolved_rows: list[dict[str, Any]],
    metadata_by_answer: dict[str, Metadata],
    existing_candidate_overrides: dict[str, tuple[str, str]],
) -> int:
    candidates: list[dict[str, str]] = []
    seen_answers: set[str] = set()
    for row in unresolved_rows:
        answer = str(row.get("answer") or "").strip().upper()
        clue = str(row.get("clue") or "").strip()
        if not answer or answer in seen_answers:
            continue
        seen_answers.add(answer)
        meta = metadata_by_answer.get(answer) or Metadata(source_type="", source_id=None, source_ref="", canonical_slug="")
        manual_payload = existing_candidate_overrides.get(answer)
        candidates.append(
            {
                "answer": answer,
                "current_clue": clue,
                "source_type": str(row.get("source_type") or meta.source_type),
                "source_id": str(row.get("source_id") or (meta.source_id if isinstance(meta.source_id, int) else "")),
                "canonical_slug": str(row.get("canonical_slug") or meta.canonical_slug),
                "source_ref": str(row.get("source_ref") or meta.source_ref),
                "manual_clue": manual_payload[0] if manual_payload else "",
                "reason_codes": str(row.get("reason_codes") or ""),
                "reason_details": str(row.get("reason_details") or ""),
                "status": "manual_needed",
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        fieldnames = [
            "answer",
            "current_clue",
            "source_type",
            "source_id",
            "canonical_slug",
            "source_ref",
            "manual_clue",
            "reason_codes",
            "reason_details",
            "status",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candidates)
    return len(candidates)


def _write_quality_report(
    *,
    path: Path,
    input_rows: int,
    output_rows: int,
    unresolved_rows: list[dict[str, Any]],
    overrides_loaded: int,
    candidate_manual_clues_loaded: int,
    applied: int,
    unchanged: int,
    skipped_answer_leak: int,
    skipped_duplicate: int,
    skipped_low_quality: int,
) -> None:
    reason_counts: Counter[str] = Counter()
    for row in unresolved_rows:
        for reason in str(row.get("reason_codes") or "").split("|"):
            reason = reason.strip()
            if reason:
                reason_counts[reason] += 1

    payload = {
        "inputRowCount": input_rows,
        "outputRowCount": output_rows,
        "overridesLoaded": overrides_loaded,
        "candidateManualCluesLoaded": candidate_manual_clues_loaded,
        "overridesApplied": applied,
        "overridesUnchanged": unchanged,
        "overridesSkippedAnswerLeak": skipped_answer_leak,
        "overridesSkippedDuplicateClue": skipped_duplicate,
        "skippedLowQualityRows": skipped_low_quality,
        "unresolvedCount": len(unresolved_rows),
        "unresolvedReasonCounts": dict(sorted(reason_counts.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply manual crossword clue overrides and export unresolved fallback candidates.",
    )
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--wordlist-json", type=Path, default=DEFAULT_WORDLIST_JSON)
    parser.add_argument("--pokeapi-cache-dir", type=Path, default=ROOT_DIR / "services" / "data" / "pokeapi")
    parser.add_argument("--overrides-csv", type=Path, default=DEFAULT_OVERRIDES_CSV)
    parser.add_argument("--candidates-csv", type=Path, default=DEFAULT_CANDIDATES_CSV)
    parser.add_argument("--quality-report-json", type=Path, default=DEFAULT_QUALITY_REPORT_JSON)
    parser.add_argument(
        "--skip-candidate-overrides",
        action="store_true",
        help="Do not apply manual_clue values from candidates CSV.",
    )
    parser.add_argument(
        "--allow-unresolved",
        action="store_true",
        help="Keep unresolved low-quality clues in the output CSV (disabled by default).",
    )
    parser.add_argument("--skip-apply", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    rows = _read_csv_rows(args.input_csv)
    payload_name_index = _load_payload_name_index(args.pokeapi_cache_dir)
    metadata_by_answer = _load_word_metadata(args.wordlist_json, payload_name_index)

    _ensure_overrides_file(args.overrides_csv)
    overrides = _read_overrides(args.overrides_csv)
    candidate_overrides: dict[str, tuple[str, str]] = {}
    candidate_overrides_loaded = 0
    if not args.skip_candidate_overrides:
        candidate_overrides = _read_candidate_overrides(args.candidates_csv)
        candidate_overrides_loaded = len(candidate_overrides)
        for answer, payload in candidate_overrides.items():
            if answer not in overrides:
                overrides[answer] = payload

    applied = 0
    skipped_answer_leak = 0
    skipped_duplicate = 0
    unchanged = 0
    skipped_low_quality = 0

    output_rows: list[tuple[str, str]] = []
    used_clues: set[str] = set()
    unresolved_rows: list[dict[str, Any]] = []

    for answer, clue in rows:
        meta = metadata_by_answer.get(answer)
        source_type = meta.source_type if meta else ""
        source_id = meta.source_id if meta else None
        source_ref = meta.source_ref if meta else ""
        canonical_slug = meta.canonical_slug if meta else ""
        final_clue = clue

        if not args.skip_apply and answer in overrides:
            override_clue_raw, _ = overrides[answer]
            candidate = _strip_answer_fragments(override_clue_raw, answer, source_type)

            if _clue_contains_answer_fragment(candidate, answer):
                skipped_answer_leak += 1
            elif candidate in used_clues and candidate != clue:
                skipped_duplicate += 1
            else:
                final_clue = candidate
                if final_clue != clue:
                    applied += 1
                else:
                    unchanged += 1

        quality_reasons = _clue_quality_reasons(clue=final_clue, display_answer=answer)
        if quality_reasons:
            unresolved_rows.append(
                {
                    "answer": answer,
                    "clue": final_clue,
                    "source_type": source_type,
                    "source_id": str(source_id) if isinstance(source_id, int) else "",
                    "canonical_slug": canonical_slug,
                    "source_ref": source_ref,
                    "reason_codes": "|".join(quality_reasons),
                    "reason_details": ", ".join(quality_reasons),
                }
            )
            if not args.allow_unresolved:
                skipped_low_quality += 1
                continue

        output_rows.append((answer, final_clue))
        used_clues.add(final_clue)

    output_rows = sorted(output_rows, key=lambda value: value[0].replace(" ", ""))

    if not args.dry_run:
        _write_csv_rows(args.output_csv, output_rows)

    exported = 0
    if not args.skip_export:
        if not args.dry_run:
            exported = _export_candidates(
                args.candidates_csv,
                unresolved_rows,
                metadata_by_answer,
                candidate_overrides,
            )
        else:
            exported = len(unresolved_rows)

    if not args.dry_run:
        _write_quality_report(
            path=args.quality_report_json,
            input_rows=len(rows),
            output_rows=len(output_rows),
            unresolved_rows=unresolved_rows,
            overrides_loaded=len(overrides),
            candidate_manual_clues_loaded=candidate_overrides_loaded,
            applied=applied,
            unchanged=unchanged,
            skipped_answer_leak=skipped_answer_leak,
            skipped_duplicate=skipped_duplicate,
            skipped_low_quality=skipped_low_quality,
        )

    print(f"Input rows: {len(rows)}")
    print(f"Overrides loaded: {len(overrides)}")
    print(f"Candidate manual clues loaded: {candidate_overrides_loaded}")
    print(f"Overrides applied: {applied}")
    print(f"Overrides unchanged: {unchanged}")
    print(f"Overrides skipped (answer leak): {skipped_answer_leak}")
    print(f"Overrides skipped (duplicate clue): {skipped_duplicate}")
    print(f"Rows skipped (low quality unresolved): {skipped_low_quality}")
    print(f"Unresolved rows: {len(unresolved_rows)}")
    print(f"Candidates exported: {exported}")
    if args.dry_run:
        print("Dry run: no files written")
    else:
        print(f"Wrote clue CSV: {args.output_csv}")
        print(f"Overrides file: {args.overrides_csv}")
        print(f"Quality report: {args.quality_report_json}")
        if not args.skip_export:
            print(f"Candidates file: {args.candidates_csv}")


if __name__ == "__main__":
    main()
