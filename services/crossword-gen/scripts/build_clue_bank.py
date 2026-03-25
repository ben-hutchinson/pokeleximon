from __future__ import annotations

import argparse
from pathlib import Path
import re
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.clue_bank import (
    build_clue_bank,
    build_connections_rules,
    build_override_candidates,
    load_editorial_seeds,
    load_answer_rows,
    load_overrides,
    load_payload_index,
    project_crossword_wide_rows,
    write_csv_rows,
    write_json,
    write_override_candidates,
)
from crossword.answer_metadata import build_answer_metadata
from crossword.bulbapedia_evidence import fallback_structured_facts, fetch_bulbapedia_evidence
from crossword.clue_curator_local import curate_clues_locally
from crossword.clue_product_owner import evaluate_generator_candidates
from crossword.clue_unresolved_audit import build_unresolved_audit
from crossword.provider_clue_workers import build_bulbapedia_candidate_pool, generate_provider_clue


ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_ANSWER_CORPUS = ROOT_DIR / "data" / "pokeapi_answer_corpus.json"
DEFAULT_PAYLOAD_CACHE_DIR = ROOT_DIR / "services" / "data" / "pokeapi"
DEFAULT_OUTPUT_CLUE_BANK = ROOT_DIR / "data" / "clue_bank.json"
DEFAULT_OUTPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
DEFAULT_OUTPUT_REPORT = ROOT_DIR / "data" / "clue_bank_quality_report.json"
DEFAULT_OUTPUT_CONNECTIONS_RULES = ROOT_DIR / "data" / "connections_group_rules.json"
DEFAULT_OUTPUT_UNRESOLVED_AUDIT = ROOT_DIR / "data" / "clue_bank_unresolved_audit.json"
DEFAULT_OVERRIDES_CSV = ROOT_DIR / "data" / "crossword_clue_overrides.csv"
DEFAULT_EDITORIAL_SEEDS_JSON = ROOT_DIR / "data" / "clue_editorial_seeds.json"
DEFAULT_OVERRIDE_CANDIDATES = ROOT_DIR / "data" / "crossword_clue_override_candidates.csv"
DEFAULT_EVIDENCE_CACHE_DIR = ROOT_DIR / "data" / "bulbapedia_evidence"
DEFAULT_AGENT_CACHE_DIR = ROOT_DIR / "data" / "bulbapedia_clue_agent"
DEFAULT_PROVIDER_CACHE_ROOT = ROOT_DIR / "data" / "crossword_provider_agents"
SOURCE_REF_RE = re.compile(r"/api/v2/([^/]+)/(\d+)/?$")


def _curated_candidate_count(payload: dict[str, object] | None) -> int:
    if not isinstance(payload, dict):
        return 0
    response = payload.get("response")
    if not isinstance(response, dict):
        return 0
    candidates = response.get("crossword_candidates")
    if not isinstance(candidates, list):
        return 0
    return sum(1 for row in candidates if isinstance(row, dict) and str(row.get("text") or "").strip())


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the shared clue bank and projected runtime artifacts.")
    parser.add_argument("--answer-corpus", type=Path, default=DEFAULT_ANSWER_CORPUS)
    parser.add_argument("--payload-cache-dir", type=Path, default=DEFAULT_PAYLOAD_CACHE_DIR)
    parser.add_argument("--output-clue-bank", type=Path, default=DEFAULT_OUTPUT_CLUE_BANK)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-report", type=Path, default=DEFAULT_OUTPUT_REPORT)
    parser.add_argument("--output-connections-rules", type=Path, default=DEFAULT_OUTPUT_CONNECTIONS_RULES)
    parser.add_argument("--output-unresolved-audit", type=Path, default=DEFAULT_OUTPUT_UNRESOLVED_AUDIT)
    parser.add_argument("--overrides-csv", type=Path, default=DEFAULT_OVERRIDES_CSV)
    parser.add_argument("--editorial-seeds-json", type=Path, default=DEFAULT_EDITORIAL_SEEDS_JSON)
    parser.add_argument("--override-candidates-csv", type=Path, default=DEFAULT_OVERRIDE_CANDIDATES)
    parser.add_argument("--evidence-cache-dir", type=Path, default=DEFAULT_EVIDENCE_CACHE_DIR)
    parser.add_argument("--agent-cache-dir", type=Path, default=DEFAULT_AGENT_CACHE_DIR)
    parser.add_argument("--provider-cache-root", type=Path, default=DEFAULT_PROVIDER_CACHE_ROOT)
    parser.add_argument("--cache-only", action="store_true")
    parser.add_argument("--max-answers", type=int, default=0)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.0)
    parser.add_argument(
        "--generator-strategy",
        choices=("bulbapedia_only", "provider_mix"),
        default="bulbapedia_only",
        help="Use three distinct Bulbapedia candidates by default, or preserve the older mixed-provider path.",
    )
    return parser.parse_args()


def _provider_cache_dir(root: Path, provider: str) -> Path:
    return root / provider


def _generator_candidates(
    *,
    strategy: str,
    row: dict[str, object],
    structured_facts: dict[str, object],
    args: argparse.Namespace,
    evidence: dict[str, object] | None,
    curated: dict[str, object] | None,
) -> list[dict[str, object]]:
    bulbapedia_result = generate_provider_clue(
        provider="bulbapedia",
        answer_row=row,
        structured_facts=structured_facts,
        cache_dir=_provider_cache_dir(args.provider_cache_root, "bulbapedia"),
        evidence_cache_dir=args.evidence_cache_dir,
        curator_cache_dir=args.agent_cache_dir,
        cache_only=args.cache_only,
        timeout_seconds=args.timeout_seconds,
        request_delay_seconds=args.request_delay_seconds,
        evidence=evidence,
        curated=curated,
    )
    if strategy == "bulbapedia_only":
        pool = build_bulbapedia_candidate_pool(
            answer_display=str(row.get("answerDisplay") or ""),
            evidence=evidence,
            curated=curated,
        )
        return pool or [bulbapedia_result]

    provider_candidates = [bulbapedia_result]
    for provider in ("serebii", "pokemondb"):
        provider_candidates.append(
            generate_provider_clue(
                provider=provider,
                answer_row=row,
                structured_facts=structured_facts,
                cache_dir=_provider_cache_dir(args.provider_cache_root, provider),
                cache_only=args.cache_only,
                timeout_seconds=args.timeout_seconds,
                request_delay_seconds=args.request_delay_seconds,
            )
        )
    return provider_candidates


def main() -> None:
    args = parse_args()
    answer_rows = load_answer_rows(args.answer_corpus)
    if args.max_answers > 0:
        answer_rows = answer_rows[: int(args.max_answers)]
    payload_index = load_payload_index(args.payload_cache_dir)
    overrides = load_overrides(args.overrides_csv)
    editorial_seeds = load_editorial_seeds(args.editorial_seeds_json)
    evidence_by_answer: dict[str, dict[str, object]] = {}
    curated_by_answer: dict[str, dict[str, object]] = {}
    product_owner_by_answer: dict[str, dict[str, object]] = {}
    row_by_answer: dict[str, dict[str, object]] = {}
    structured_by_answer: dict[str, dict[str, object]] = {}

    for row in answer_rows:
        answer_key = str(row.get("answerKey") or "").upper()
        row_by_answer[answer_key] = row
        metadata = build_answer_metadata(row)
        source_ref = str(metadata.get("sourceRef") or "")
        source_type = str(metadata.get("sourceType") or "")
        source_id = metadata.get("sourceId")
        payload = payload_index.get((source_type, source_id)) if isinstance(source_id, int) else None
        structured_facts = fallback_structured_facts(row, payload)
        structured_by_answer[answer_key] = structured_facts
        canonical_slug = str((payload or {}).get("name") or metadata.get("canonicalSlug") or row.get("sourceSlug") or "")
        evidence = fetch_bulbapedia_evidence(
            answer_key=answer_key,
            answer_display=str(row.get("answerDisplay") or ""),
            source_type=source_type,
            canonical_slug=canonical_slug,
            structured_facts=structured_facts,
            cache_dir=args.evidence_cache_dir,
            cache_only=args.cache_only,
            timeout_seconds=args.timeout_seconds,
            request_delay_seconds=args.request_delay_seconds,
        )
        evidence_by_answer[answer_key] = evidence
        curated = curate_clues_locally(
            answer_row=row,
            evidence=evidence,
            structured_facts=structured_facts,
            cache_dir=args.agent_cache_dir,
        )
        curated_by_answer[answer_key] = curated
        provider_candidates = _generator_candidates(
            strategy=args.generator_strategy,
            row=row,
            structured_facts=structured_facts,
            args=args,
            evidence=evidence,
            curated=curated,
        )
        product_owner_by_answer[answer_key] = evaluate_generator_candidates(
            answer_row=row,
            provider_candidates=provider_candidates,
        )

    first_pass_entries, _ = build_clue_bank(
        answer_rows,
        payload_index,
        overrides=overrides,
        editorial_seeds=editorial_seeds,
        evidence_by_answer=evidence_by_answer,
        curated_by_answer=curated_by_answer,
        product_owner_by_answer=product_owner_by_answer,
    )
    first_pass_audit = build_unresolved_audit(first_pass_entries)
    second_pass_keys = set(str(value or "").upper() for value in first_pass_audit.get("secondPassAnswerKeys", []))
    for answer_key in sorted(second_pass_keys):
        row = row_by_answer.get(answer_key)
        if not isinstance(row, dict):
            continue
        metadata = build_answer_metadata(row)
        source_ref = str(metadata.get("sourceRef") or "")
        source_type = str(metadata.get("sourceType") or "")
        source_id = metadata.get("sourceId")
        payload = payload_index.get((source_type, source_id)) if isinstance(source_id, int) else None
        canonical_slug = str((payload or {}).get("name") or metadata.get("canonicalSlug") or row.get("sourceSlug") or "")
        structured_facts = structured_by_answer.get(answer_key, {})
        evidence = fetch_bulbapedia_evidence(
            answer_key=answer_key,
            answer_display=str(row.get("answerDisplay") or ""),
            source_type=source_type,
            canonical_slug=canonical_slug,
            structured_facts=structured_facts,
            cache_dir=args.evidence_cache_dir,
            cache_only=args.cache_only,
            timeout_seconds=args.timeout_seconds,
            request_delay_seconds=args.request_delay_seconds,
            second_pass=True,
        )
        second_pass_curated = curate_clues_locally(
            answer_row=row,
            evidence=evidence,
            structured_facts=structured_facts,
            cache_dir=args.agent_cache_dir,
        )
        provider_candidates = _generator_candidates(
            strategy=args.generator_strategy,
            row=row,
            structured_facts=structured_facts,
            args=args,
            evidence=evidence,
            curated=second_pass_curated,
        )
        first_pass_curated = curated_by_answer.get(answer_key)
        if _curated_candidate_count(second_pass_curated) >= _curated_candidate_count(first_pass_curated):
            evidence_by_answer[answer_key] = evidence
            curated_by_answer[answer_key] = second_pass_curated
            product_owner_by_answer[answer_key] = evaluate_generator_candidates(
                answer_row=row,
                provider_candidates=provider_candidates,
            )

    entries, report = build_clue_bank(
        answer_rows,
        payload_index,
        overrides=overrides,
        editorial_seeds=editorial_seeds,
        evidence_by_answer=evidence_by_answer,
        curated_by_answer=curated_by_answer,
        product_owner_by_answer=product_owner_by_answer,
    )
    unresolved_audit = build_unresolved_audit(entries)
    crossword_rows = project_crossword_wide_rows(entries, max_per_answer=3)
    connections_rules = build_connections_rules(entries)
    override_candidates = build_override_candidates(entries)

    write_json(args.output_clue_bank, {"version": 2, "entries": entries})
    write_csv_rows(args.output_csv, crossword_rows)
    write_json(args.output_report, report)
    write_json(args.output_connections_rules, {"rules": connections_rules})
    write_json(args.output_unresolved_audit, unresolved_audit)
    write_override_candidates(args.override_candidates_csv, override_candidates)

    print(f"Clue bank entries: {len(entries)}")
    print(f"Projected crossword rows: {len(crossword_rows)}")
    print(f"Connections descriptor rules: {len(connections_rules)}")
    print(f"Override candidates: {len(override_candidates)}")
    print(f"Unresolved audit buckets: {len(unresolved_audit['buckets'])}")
    print(f"Approved coverage >=3 clues: {report['approvedCoveragePct']}%")
    print(f"Generator strategy: {args.generator_strategy}")
    print(f"Evidence cache dir: {args.evidence_cache_dir}")
    print(f"Curator cache dir: {args.agent_cache_dir}")


if __name__ == "__main__":
    main()
