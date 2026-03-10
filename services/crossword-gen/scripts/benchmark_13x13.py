from __future__ import annotations

import argparse
from collections import Counter
import csv
from dataclasses import dataclass
import json
import random
import re
import sys
from pathlib import Path
from time import perf_counter
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.feasibility import build_words_by_length, evaluate_template_feasibility  # noqa: E402
from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.publishable import PublishabilityConfig, evaluate_publishability  # noqa: E402
from crossword.seeding import build_seed_assignment  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402
from crossword.templates import load_templates  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
ANSWER_CLUE_CSV_PATH = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
TOKEN_RE = re.compile(r"[^A-Z0-9]")


@dataclass(frozen=True)
class SeedPlan:
    name: str
    seed_count: int
    min_seed_length: int
    pool_size: int
    max_tries: int


STRICT_SEED_PLAN = SeedPlan(
    name="strict_3x11",
    seed_count=3,
    min_seed_length=11,
    pool_size=250,
    max_tries=120,
)

ADAPTIVE_SEED_PLANS = [
    STRICT_SEED_PLAN,
    SeedPlan(name="adaptive_2x10", seed_count=2, min_seed_length=10, pool_size=360, max_tries=180),
    SeedPlan(name="adaptive_1x8", seed_count=1, min_seed_length=8, pool_size=520, max_tries=220),
]


def _normalize_answer(answer: str) -> str:
    return TOKEN_RE.sub("", answer.upper())


def load_words_scores_and_clues() -> tuple[list[str], dict[str, float], dict[str, str]]:
    if not ANSWER_CLUE_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV source: {ANSWER_CLUE_CSV_PATH}")

    clues_by_word: dict[str, str] = {}
    with ANSWER_CLUE_CSV_PATH.open(newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            answer = _normalize_answer(row[0].strip())
            clue = row[1].strip()
            if not answer or not clue:
                continue
            if not any(ch.isalpha() for ch in answer):
                continue
            if answer not in clues_by_word:
                clues_by_word[answer] = clue

    words = sorted(clues_by_word.keys())
    scores = {word: 1.0 for word in words}
    return words, scores, clues_by_word


@dataclass(frozen=True)
class AttemptResult:
    attempt: int
    seed: int
    template_name: str
    success: bool
    stage: str
    reason: str
    elapsed_seconds: float
    solver_steps: int
    solver_candidate_checks: int
    solver_max_depth: int
    seed_count: int
    details: dict[str, Any]


def _build_puzzle_payload(
    template,
    grid: Grid,
    entries,
    *,
    clues_by_word: dict[str, str],
) -> dict[str, Any]:
    cells = []
    for y in range(template.height):
        for x in range(template.width):
            if (x, y) in template.blocks:
                cells.append(
                    {
                        "x": x,
                        "y": y,
                        "isBlock": True,
                        "solution": None,
                    }
                )
            else:
                cells.append(
                    {
                        "x": x,
                        "y": y,
                        "isBlock": False,
                        "solution": grid.get(x, y),
                    }
                )

    entry_payload = []
    for entry in entries:
        answer = "".join(grid.get(x, y) or "" for x, y in entry.cells)
        clue = clues_by_word.get(answer, "Pokemon term from the CSV lexicon.")
        source_ref = f"csv://wordlist_crossword_answer_clue.csv#{answer}"
        entry_payload.append(
            {
                "id": entry.id,
                "direction": entry.direction,
                "number": entry.number,
                "answer": answer,
                "clue": clue,
                "length": entry.length,
                "cells": [list(cell) for cell in entry.cells],
                "sourceRef": source_ref,
            }
        )

    return {
        "grid": {"width": template.width, "height": template.height, "cells": cells},
        "entries": entry_payload,
    }


def _classify_solver_failure(
    *,
    solver: Solver,
    elapsed_seconds: float,
    max_seconds: float,
    max_steps: int,
) -> str:
    if solver.cp_sat_attempted and solver.cp_sat_status:
        if solver.cp_sat_status != "cp_sat_solved":
            return solver.cp_sat_status
    if max_seconds > 0 and elapsed_seconds >= max_seconds * 0.995:
        return "timeout"
    if solver.steps >= max_steps:
        return "max_steps"
    if solver.candidate_checks == 0:
        return "no_candidates"
    return "backtrack_exhausted"


def _build_seed_assignment_with_strategy(
    *,
    entries,
    words_for_seeding: dict[int, list[str]],
    word_scores: dict[str, float],
    strategy: str,
) -> tuple[dict[str, str] | None, str | None, list[dict[str, Any]]]:
    if strategy == "strict":
        plans = [STRICT_SEED_PLAN]
        allow_unseeded_fallback = False
    elif strategy == "fallback":
        plans = [STRICT_SEED_PLAN]
        allow_unseeded_fallback = True
    elif strategy == "adaptive":
        plans = ADAPTIVE_SEED_PLANS
        allow_unseeded_fallback = True
    else:
        raise ValueError(f"unknown_seed_strategy:{strategy}")

    attempts: list[dict[str, Any]] = []
    for plan in plans:
        assignment = build_seed_assignment(
            entries,
            words_by_length=words_for_seeding,
            word_scores=word_scores,
            seed_count=plan.seed_count,
            min_seed_length=plan.min_seed_length,
            pool_size=plan.pool_size,
            max_tries=plan.max_tries,
        )
        attempts.append(
            {
                "plan": plan.name,
                "seedCount": len(assignment or {}),
                "success": assignment is not None,
            }
        )
        if assignment is not None:
            return assignment, None, attempts

    if allow_unseeded_fallback:
        return {}, "seed_fallback_unseeded", attempts
    return None, "no_seed_assignment", attempts


def _run_attempt(
    *,
    attempt: int,
    seed: int,
    template,
    words: list[str],
    word_scores: dict[str, float],
    clues_by_word: dict[str, str],
    words_by_length: dict[int, list[str]],
    args: argparse.Namespace,
    publish_cfg: PublishabilityConfig,
) -> AttemptResult:
    random.seed(seed)
    entries = parse_entries(template.width, template.height, template.blocks)
    if not entries:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="template_fit",
            reason="no_entries",
            elapsed_seconds=0.0,
            solver_steps=0,
            solver_candidate_checks=0,
            solver_max_depth=0,
            seed_count=0,
            details={},
        )

    lengths = {entry.length for entry in entries}
    if min(lengths) < 4 or max(lengths) > 13:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="template_fit",
            reason="slot_length_out_of_bounds",
            elapsed_seconds=0.0,
            solver_steps=0,
            solver_candidate_checks=0,
            solver_max_depth=0,
            seed_count=0,
            details={"minLength": min(lengths), "maxLength": max(lengths)},
        )

    missing_lengths = sorted(length for length in lengths if not words_by_length.get(length))
    if missing_lengths:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="template_fit",
            reason=f"missing_words_len_{missing_lengths[0]}",
            elapsed_seconds=0.0,
            solver_steps=0,
            solver_candidate_checks=0,
            solver_max_depth=0,
            seed_count=0,
            details={"missingLengths": missing_lengths},
        )

    filtered_words = [word for word in words if len(word) in lengths and 4 <= len(word) <= 13]
    if not filtered_words:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="word_scarcity",
            reason="empty_filtered_wordlist",
            elapsed_seconds=0.0,
            solver_steps=0,
            solver_candidate_checks=0,
            solver_max_depth=0,
            seed_count=0,
            details={},
        )

    feasibility = evaluate_template_feasibility(
        entries,
        words_by_length=words_by_length,
        min_post_ac3_domain=1,
    )
    if not feasibility.feasible:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="word_scarcity",
            reason=feasibility.reason or "ac3_infeasible",
            elapsed_seconds=0.0,
            solver_steps=0,
            solver_candidate_checks=0,
            solver_max_depth=0,
            seed_count=0,
            details={},
        )

    min_domain = min(feasibility.domain_sizes.values()) if feasibility.domain_sizes else 0
    if min_domain < args.min_domain:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="word_scarcity",
            reason="fragile_domain",
            elapsed_seconds=0.0,
            solver_steps=0,
            solver_candidate_checks=0,
            solver_max_depth=0,
            seed_count=0,
            details={"minDomain": min_domain, "requiredMinDomain": args.min_domain},
        )

    words_for_seeding: dict[int, list[str]] = {}
    for word in filtered_words:
        words_for_seeding.setdefault(len(word), []).append(word)

    seed_assignments: dict[str, str] | None = None
    seed_fallback_reason: str | None = None
    seed_plan_attempts: list[dict[str, Any]] = []
    if args.seeded:
        seed_assignments, seed_fallback_reason, seed_plan_attempts = _build_seed_assignment_with_strategy(
            entries=entries,
            words_for_seeding=words_for_seeding,
            word_scores=word_scores,
            strategy=args.seed_strategy,
        )
        if seed_assignments is None:
            return AttemptResult(
                attempt=attempt,
                seed=seed,
                template_name=template.name,
                success=False,
                stage="seed_fit",
                reason=seed_fallback_reason or "no_seed_assignment",
                elapsed_seconds=0.0,
                solver_steps=0,
                solver_candidate_checks=0,
                solver_max_depth=0,
                seed_count=0,
                details={
                    "seedStrategy": args.seed_strategy,
                    "seedPlanAttempts": seed_plan_attempts,
                },
            )

    solver = Solver(
        Grid(template.width, template.height, template.blocks),
        entries,
        filtered_words,
        SolverConfig(
            max_steps=args.max_steps,
            max_candidates=8000,
            weighted_shuffle=True,
            allow_reuse=not args.disallow_reuse,
            max_seconds=args.max_seconds,
            debug=False,
            beam_width=args.beam_width,
            beam_depth=args.beam_depth,
            use_min_conflicts=not args.no_min_conflicts,
            use_cp_sat=args.cp_sat,
            cp_sat_first=not args.cp_sat_after_backtracking,
            cp_sat_max_seconds=args.cp_sat_seconds,
            cp_sat_max_domain_per_entry=args.cp_sat_max_domain,
            cp_sat_workers=args.cp_sat_workers,
        ),
        word_scores=word_scores,
        initial_assignments=seed_assignments,
    )
    start = perf_counter()
    solved = solver.solve()
    elapsed = perf_counter() - start

    if not solved:
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="slot_dead_end",
            reason=_classify_solver_failure(
                solver=solver,
                elapsed_seconds=elapsed,
                max_seconds=args.max_seconds,
                max_steps=args.max_steps,
            ),
            elapsed_seconds=elapsed,
            solver_steps=solver.steps,
            solver_candidate_checks=solver.candidate_checks,
            solver_max_depth=solver.max_depth,
            seed_count=len(seed_assignments or {}),
            details={
                "minDomain": min_domain,
                "seedStrategy": args.seed_strategy if args.seeded else "disabled",
                "seedFallbackReason": seed_fallback_reason,
                "seedPlanAttempts": seed_plan_attempts,
                "cpSatAttempted": solver.cp_sat_attempted,
                "cpSatStatus": solver.cp_sat_status,
                "cpSatWallSeconds": round(solver.cp_sat_wall_seconds, 4),
            },
        )

    puzzle = _build_puzzle_payload(
        template,
        solver.grid,
        entries,
        clues_by_word=clues_by_word,
    )
    publishability = evaluate_publishability(puzzle, config=publish_cfg)
    if not publishability.publishable:
        reason = publishability.blockers[0] if publishability.blockers else "publishability_failed"
        return AttemptResult(
            attempt=attempt,
            seed=seed,
            template_name=template.name,
            success=False,
            stage="publishability_gate",
            reason=reason,
            elapsed_seconds=elapsed,
            solver_steps=solver.steps,
            solver_candidate_checks=solver.candidate_checks,
            solver_max_depth=solver.max_depth,
            seed_count=len(seed_assignments or {}),
            details={
                "minDomain": min_domain,
                "seedStrategy": args.seed_strategy if args.seeded else "disabled",
                "seedFallbackReason": seed_fallback_reason,
                "seedPlanAttempts": seed_plan_attempts,
                "publishabilityMetrics": publishability.metrics,
                "publishabilityChecks": publishability.checks,
                "cpSatAttempted": solver.cp_sat_attempted,
                "cpSatStatus": solver.cp_sat_status,
                "cpSatWallSeconds": round(solver.cp_sat_wall_seconds, 4),
            },
        )

    return AttemptResult(
        attempt=attempt,
        seed=seed,
        template_name=template.name,
        success=True,
        stage="pass",
        reason="ok",
        elapsed_seconds=elapsed,
        solver_steps=solver.steps,
        solver_candidate_checks=solver.candidate_checks,
        solver_max_depth=solver.max_depth,
        seed_count=len(seed_assignments or {}),
        details={
            "minDomain": min_domain,
            "seedStrategy": args.seed_strategy if args.seeded else "disabled",
            "seedFallbackReason": seed_fallback_reason,
            "seedPlanAttempts": seed_plan_attempts,
            "cpSatAttempted": solver.cp_sat_attempted,
            "cpSatStatus": solver.cp_sat_status,
            "cpSatWallSeconds": round(solver.cp_sat_wall_seconds, 4),
        },
    )


def _render_report(
    results: list[AttemptResult],
    args: argparse.Namespace,
    template_dims_by_name: dict[str, tuple[int, int]],
) -> str:
    total = len(results)
    passed = sum(1 for item in results if item.success)
    failed = total - passed
    pass_rate = (passed / total) if total else 0.0

    stage_counts = Counter(item.stage for item in results if not item.success)
    blocker_counts = Counter(f"{item.stage}:{item.reason}" for item in results if not item.success)
    template_failures = Counter(item.template_name for item in results if not item.success)

    by_size = Counter(template_dims_by_name.get(item.template_name, (0, 0)) for item in results)
    size_passes = Counter(
        template_dims_by_name.get(item.template_name, (0, 0)) for item in results if item.success
    )

    lines = [
        "# Adaptive Crossword Reliability Benchmark",
        "",
        f"- Attempts: {total}",
        f"- Passed publishability gate: {passed}",
        f"- Failed: {failed}",
        f"- Pass rate: {pass_rate:.2%}",
        (
            f"- Controls: base_seed={args.base_seed}, seeded={args.seeded}, "
            f"max_seconds={args.max_seconds}, max_steps={args.max_steps}, min_domain={args.min_domain}, "
            f"template_track={args.template_track}, template_sizes={args.template_sizes}, "
            f"seed_strategy={args.seed_strategy}, "
            f"cp_sat={args.cp_sat}, cp_sat_seconds={args.cp_sat_seconds}, "
            f"cp_sat_after_backtracking={args.cp_sat_after_backtracking}, "
            f"min_conflicts={not args.no_min_conflicts}, allow_reuse={not args.disallow_reuse}"
        ),
        "",
        "Pass Rate By Size:",
    ]
    for dims, count in sorted(by_size.items()):
        if count <= 0:
            continue
        w, h = dims
        wins = size_passes.get(dims, 0)
        lines.append(f"- `{w}x{h}`: {wins}/{count} ({(wins / count):.2%})")
    if not by_size:
        lines.append("- none")

    lines.extend(
        [
            "",
        "Top 3 blockers:",
        ]
    )
    top_blockers = blocker_counts.most_common(3)
    for idx, (reason, count) in enumerate(top_blockers, start=1):
        lines.append(f"{idx}. `{reason}` ({count})")
    for idx in range(len(top_blockers) + 1, 4):
        lines.append(f"{idx}. none")

    lines.extend(["", "Failure stages:"])
    for stage, count in stage_counts.most_common():
        lines.append(f"- `{stage}`: {count}")
    if not stage_counts:
        lines.append("- none")

    lines.extend(["", "Most impacted templates:"])
    for template_name, count in template_failures.most_common(5):
        lines.append(f"- `{template_name}`: {count} failures")
    if not template_failures:
        lines.append("- none")

    return "\n".join(lines)


def _serialize_results(
    results: list[AttemptResult],
    args: argparse.Namespace,
    template_dims_by_name: dict[str, tuple[int, int]],
) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for item in results if item.success)
    blocker_counts = Counter(f"{item.stage}:{item.reason}" for item in results if not item.success)
    stage_counts = Counter(item.stage for item in results if not item.success)

    by_size = Counter(template_dims_by_name.get(item.template_name, (0, 0)) for item in results)
    size_passes = Counter(
        template_dims_by_name.get(item.template_name, (0, 0)) for item in results if item.success
    )

    return {
        "attempts": total,
        "passed": passed,
        "failed": total - passed,
        "passRate": (passed / total) if total else 0.0,
        "config": {
            "baseSeed": args.base_seed,
            "seeded": args.seeded,
            "seedStrategy": args.seed_strategy,
            "maxSeconds": args.max_seconds,
            "maxSteps": args.max_steps,
            "minDomain": args.min_domain,
            "templateTrack": args.template_track,
            "templateSizes": args.template_sizes,
            "templatePrefix": args.template_prefix,
            "templateName": args.template_name,
            "requireClues": args.require_clues,
            "cpSat": args.cp_sat,
            "cpSatSeconds": args.cp_sat_seconds,
            "cpSatMaxDomain": args.cp_sat_max_domain,
            "cpSatWorkers": args.cp_sat_workers,
            "cpSatAfterBacktracking": args.cp_sat_after_backtracking,
            "useMinConflicts": not args.no_min_conflicts,
            "allowReuse": not args.disallow_reuse,
        },
        "sizeStats": [
            {
                "size": f"{dims[0]}x{dims[1]}",
                "attempts": count,
                "passed": size_passes.get(dims, 0),
                "passRate": (size_passes.get(dims, 0) / count) if count else 0.0,
            }
            for dims, count in sorted(by_size.items())
            if count > 0
        ],
        "stageCounts": dict(stage_counts),
        "blockerCounts": dict(blocker_counts),
        "attemptResults": [
            {
                "attempt": item.attempt,
                "seed": item.seed,
                "templateName": item.template_name,
                "success": item.success,
                "stage": item.stage,
                "reason": item.reason,
                "elapsedSeconds": round(item.elapsed_seconds, 4),
                "solverSteps": item.solver_steps,
                "solverCandidateChecks": item.solver_candidate_checks,
                "solverMaxDepth": item.solver_max_depth,
                "seedCount": item.seed_count,
                "details": item.details,
            }
            for item in results
        ],
    }


def _template_matches_track(template_name: str, track: str, prefix: str | None) -> bool:
    if prefix:
        return template_name.startswith(prefix)
    if track == "quick":
        return template_name.startswith("quick_candidate_13x13_")
    if track == "worksheet":
        return (
            template_name.startswith("auto_")
            or template_name.startswith("mini_")
            or template_name.startswith("constructive_")
            or template_name.startswith("a_9x9_")
        )
    if track == "all":
        return True
    return False


def _parse_template_sizes(value: str) -> list[int]:
    out: list[int] = []
    for chunk in value.split(","):
        text = chunk.strip()
        if not text:
            continue
        n = int(text)
        if n not in out:
            out.append(n)
    if not out:
        raise ValueError("template_sizes_empty")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Adaptive crossword benchmark with seed-fit and failure-stage triage"
    )
    parser.add_argument("--attempts", type=int, default=100)
    parser.add_argument("--base-seed", type=int, default=13013)
    parser.add_argument("--max-seconds", type=float, default=20.0)
    parser.add_argument("--max-steps", type=int, default=600000)
    parser.add_argument("--seeded", action="store_true")
    parser.add_argument("--seed-strategy", choices=["strict", "fallback", "adaptive"], default="strict")
    parser.add_argument("--template-track", choices=["worksheet", "quick", "all"], default="worksheet")
    parser.add_argument("--template-sizes", type=str, default="13,11,9")
    parser.add_argument("--template-prefix", type=str, default="quick_candidate_13x13_")
    parser.add_argument("--template-name", type=str, default=None)
    parser.add_argument("--beam-width", type=int, default=0)
    parser.add_argument("--beam-depth", type=int, default=0)
    parser.add_argument("--min-domain", type=int, default=2)
    parser.add_argument("--cp-sat", action="store_true")
    parser.add_argument("--cp-sat-seconds", type=float, default=2.0)
    parser.add_argument("--cp-sat-max-domain", type=int, default=1200)
    parser.add_argument("--cp-sat-workers", type=int, default=8)
    parser.add_argument("--cp-sat-after-backtracking", action="store_true")
    parser.add_argument("--no-min-conflicts", action="store_true")
    parser.add_argument("--disallow-reuse", action="store_true")
    parser.add_argument("--require-clues", action="store_true")
    parser.add_argument("--report-out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    if args.template_track != "quick" and args.template_prefix == "quick_candidate_13x13_":
        args.template_prefix = None

    size_preference = _parse_template_sizes(args.template_sizes)
    words, scores, clues_by_word = load_words_scores_and_clues()
    words_by_length = build_words_by_length(words, min_len=4, max_len=13)
    templates = load_templates(TEMPLATE_DIR)
    if args.template_name:
        templates = [t for t in templates if t.name == args.template_name]
    else:
        templates = [
            t
            for t in templates
            if t.width == t.height
            and t.width in size_preference
            and _template_matches_track(t.name, args.template_track, args.template_prefix)
        ]
    templates = sorted(templates, key=lambda t: (t.width, t.name))
    filtered_templates: list[Any] = []
    for template in templates:
        entries = parse_entries(template.width, template.height, template.blocks)
        if not entries:
            continue
        lengths = [entry.length for entry in entries]
        if min(lengths) < 4 or max(lengths) > 13:
            continue
        filtered_templates.append(template)
    templates = filtered_templates
    if not templates:
        raise RuntimeError("No templates matched the provided track/size filters")

    templates_by_size: dict[int, list[Any]] = {size: [] for size in size_preference}
    for template in templates:
        if template.width in templates_by_size:
            templates_by_size[template.width].append(template)
    template_dims_by_name = {t.name: (t.width, t.height) for t in templates}

    publish_cfg = PublishabilityConfig(require_clues=args.require_clues)
    results: list[AttemptResult] = []
    for attempt in range(1, args.attempts + 1):
        seed = args.base_seed + (attempt - 1)
        result: AttemptResult | None = None
        stage_rank = {
            "pass": 6,
            "publishability_gate": 5,
            "slot_dead_end": 4,
            "word_scarcity": 3,
            "seed_fit": 2,
            "template_fit": 1,
        }
        for size in size_preference:
            bucket = templates_by_size.get(size, [])
            if not bucket:
                continue
            template = bucket[seed % len(bucket)]
            trial = _run_attempt(
                attempt=attempt,
                seed=seed,
                template=template,
                words=words,
                word_scores=scores,
                clues_by_word=clues_by_word,
                words_by_length=words_by_length,
                args=args,
                publish_cfg=publish_cfg,
            )
            if trial.success:
                result = trial
                break
            if result is None:
                result = trial
            else:
                if stage_rank.get(trial.stage, 0) > stage_rank.get(result.stage, 0):
                    result = trial
        if result is None:
            raise RuntimeError("No templates available for any requested size")
        results.append(result)
        if args.verbose:
            print(
                f"attempt={result.attempt} seed={result.seed} template={result.template_name} "
                f"success={result.success} stage={result.stage} reason={result.reason} "
                f"time={result.elapsed_seconds:.2f}s steps={result.solver_steps} "
                f"checks={result.solver_candidate_checks} depth={result.solver_max_depth}"
            )

    report = _render_report(results, args, template_dims_by_name)
    print(report)

    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(report + "\n")
        print(f"report_written={args.report_out}")

    if args.json_out:
        payload = _serialize_results(results, args, template_dims_by_name)
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2))
        print(f"json_written={args.json_out}")


if __name__ == "__main__":
    main()
