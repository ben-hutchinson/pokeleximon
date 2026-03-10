from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import json
from pathlib import Path
import sys
from time import perf_counter
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.detail_corpus import (  # noqa: E402
    build_word_metadata_index,
    clue_for_answer,
    load_detail_corpus_index,
)
from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.publishable import PublishabilityConfig, evaluate_publishability  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402
from crossword.templates import Template, load_templates  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
DETAIL_CORPUS_PATH = ROOT_DIR / "data" / "pokeapi_detail_corpus.json"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"


@dataclass(frozen=True)
class AttemptOutcome:
    solved: bool
    publishable: bool
    reason: str
    elapsed_seconds: float
    cp_sat_status: str | None


def load_words_and_scores() -> tuple[list[str], dict[str, float], dict[str, dict[str, str]]]:
    path = WORDLIST_CROSSWORD_PATH if WORDLIST_CROSSWORD_PATH.exists() else WORDLIST_PATH
    data = json.loads(path.read_text())
    words = sorted({item["word"] for item in data if item.get("word")})
    scores: dict[str, float] = {}
    for item in data:
        word = item.get("word")
        if not word:
            continue
        source = item.get("sourceType", "")
        if source == "pokemon-species":
            scores[word] = 3.0
        elif source in {"move", "ability", "type"}:
            scores[word] = 2.0
        else:
            scores[word] = 1.5
    metadata = build_word_metadata_index(data)
    return words, scores, metadata


def _modular_templates() -> list[Template]:
    templates: list[Template] = []
    size = 13
    # 2x2 islands of 4x4 open regions at different offsets. These are high-density
    # block patterns intended for reliable, offline-curated fill.
    x_pairs = [(0, 5), (1, 6), (0, 6), (1, 7)]
    y_pairs = [(0, 5), (1, 6), (0, 6), (1, 7)]

    for x_a, x_b in x_pairs:
        for y_a, y_b in y_pairs:
            open_cells: set[tuple[int, int]] = set()
            for x0 in (x_a, x_b):
                for y0 in (y_a, y_b):
                    for x in range(x0, x0 + 4):
                        for y in range(y0, y0 + 4):
                            if 0 <= x < size and 0 <= y < size:
                                open_cells.add((x, y))
            blocks = {
                (x, y)
                for y in range(size)
                for x in range(size)
                if (x, y) not in open_cells
            }
            name = f"modular_candidate_13x13_x{x_a}_{x_b}_y{y_a}_{y_b}"
            templates.append(
                Template(
                    name=name,
                    width=size,
                    height=size,
                    blocks=blocks,
                )
            )
    return templates


def _build_publishability_puzzle(
    template: Template,
    grid: Grid,
    entries,
    *,
    word_metadata_by_word: dict[str, dict[str, str]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cells = []
    for y in range(template.height):
        for x in range(template.width):
            if (x, y) in template.blocks:
                cells.append({"x": x, "y": y, "isBlock": True, "solution": None})
            else:
                cells.append({"x": x, "y": y, "isBlock": False, "solution": grid.get(x, y)})

    payload_entries = []
    for entry in entries:
        answer = "".join(grid.get(x, y) or "" for x, y in entry.cells)
        clue, source_ref = clue_for_answer(
            answer=answer,
            word_metadata_by_word=word_metadata_by_word,
            detail_corpus_by_ref=detail_corpus_by_ref,
        )
        payload_entries.append(
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
        "entries": payload_entries,
    }


def _classify_unsolved_reason(solver: Solver) -> str:
    if solver.cp_sat_status and solver.cp_sat_status != "cp_sat_solved":
        return solver.cp_sat_status
    if solver.steps == 0:
        return "ac3_or_domain_failure"
    return "search_exhausted"


def _run_attempt(
    template: Template,
    words: list[str],
    scores: dict[str, float],
    *,
    allow_reuse: bool,
    max_seconds: float,
    cp_sat_seconds: float,
    cp_sat_workers: int,
    cp_sat_max_domain: int,
    word_metadata_by_word: dict[str, dict[str, str]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
    publish_cfg: PublishabilityConfig,
) -> AttemptOutcome:
    entries = parse_entries(template.width, template.height, template.blocks)
    if not entries:
        return AttemptOutcome(
            solved=False,
            publishable=False,
            reason="no_entries",
            elapsed_seconds=0.0,
            cp_sat_status=None,
        )

    lengths = {entry.length for entry in entries}
    if min(lengths) < 4 or max(lengths) > 13:
        return AttemptOutcome(
            solved=False,
            publishable=False,
            reason="slot_length_out_of_bounds",
            elapsed_seconds=0.0,
            cp_sat_status=None,
        )

    filtered_words = [word for word in words if len(word) in lengths]
    solver = Solver(
        Grid(template.width, template.height, template.blocks),
        entries,
        filtered_words,
        SolverConfig(
            max_steps=1_800_000,
            max_candidates=8000,
            weighted_shuffle=True,
            allow_reuse=allow_reuse,
            max_seconds=max_seconds,
            use_min_conflicts=False,
            use_cp_sat=True,
            cp_sat_first=True,
            cp_sat_max_seconds=cp_sat_seconds,
            cp_sat_max_domain_per_entry=cp_sat_max_domain,
            cp_sat_workers=cp_sat_workers,
        ),
        word_scores=scores,
    )

    start = perf_counter()
    solved = solver.solve()
    elapsed = perf_counter() - start
    if not solved:
        return AttemptOutcome(
            solved=False,
            publishable=False,
            reason=_classify_unsolved_reason(solver),
            elapsed_seconds=elapsed,
            cp_sat_status=solver.cp_sat_status,
        )

    puzzle = _build_publishability_puzzle(
        template,
        solver.grid,
        entries,
        word_metadata_by_word=word_metadata_by_word,
        detail_corpus_by_ref=detail_corpus_by_ref,
    )
    publishability = evaluate_publishability(puzzle, config=publish_cfg)
    if not publishability.publishable:
        reason = publishability.blockers[0] if publishability.blockers else "publishability_failed"
        return AttemptOutcome(
            solved=True,
            publishable=False,
            reason=f"publishability:{reason}",
            elapsed_seconds=elapsed,
            cp_sat_status=solver.cp_sat_status,
        )

    return AttemptOutcome(
        solved=True,
        publishable=True,
        reason="ok",
        elapsed_seconds=elapsed,
        cp_sat_status=solver.cp_sat_status,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Curate a reliable 13x13 template bank with CP-SAT + publishability checks"
    )
    parser.add_argument("--size", type=int, default=13)
    parser.add_argument(
        "--input-prefix",
        action="append",
        default=None,
        help="Template prefix to include from data/templates (repeat for multiple prefixes)",
    )
    parser.add_argument("--include-modular-candidates", action="store_true")
    parser.add_argument("--output-prefix", type=str, default="quick_13x13_")
    parser.add_argument("--target-count", type=int, default=8)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--max-seconds", type=float, default=20.0)
    parser.add_argument("--cp-sat-seconds", type=float, default=15.0)
    parser.add_argument("--cp-sat-workers", type=int, default=8)
    parser.add_argument("--cp-sat-max-domain", type=int, default=1200)
    parser.add_argument("--allow-reuse", action="store_true")
    parser.add_argument("--require-clues", action="store_true")
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=TEMPLATE_DIR / "quick_13x13_manifest.json",
    )
    args = parser.parse_args()
    if not args.input_prefix:
        args.input_prefix = ["quick_candidate_13x13_"]
    return args


def main() -> None:
    args = parse_args()
    words, scores, word_metadata_by_word = load_words_and_scores()
    detail_corpus_by_ref = load_detail_corpus_index(DETAIL_CORPUS_PATH)
    publish_cfg = PublishabilityConfig(require_clues=args.require_clues)

    existing = [template for template in load_templates(TEMPLATE_DIR) if template.width == args.size]
    chosen: list[Template] = []
    input_prefixes = tuple(args.input_prefix)
    for template in existing:
        if any(template.name.startswith(prefix) for prefix in input_prefixes):
            chosen.append(template)
    if args.include_modular_candidates:
        chosen.extend(_modular_templates())

    # De-duplicate by block signature so template families don't flood candidates.
    unique_candidates: list[Template] = []
    seen_signatures: set[tuple[tuple[int, int], ...]] = set()
    for template in chosen:
        signature = tuple(sorted(template.blocks))
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        unique_candidates.append(template)

    if not unique_candidates:
        manifest_payload = {
            "size": args.size,
            "outputPrefix": args.output_prefix,
            "allowReuse": args.allow_reuse,
            "attempts": args.attempts,
            "maxSeconds": args.max_seconds,
            "cpSatSeconds": args.cp_sat_seconds,
            "cpSatWorkers": args.cp_sat_workers,
            "cpSatMaxDomain": args.cp_sat_max_domain,
            "requireClues": args.require_clues,
            "candidateCount": 0,
            "selectedCount": 0,
            "selected": [],
            "candidates": [],
        }
        args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
        args.manifest_out.write_text(json.dumps(manifest_payload, indent=2))
        print("no_candidate_templates_selected_for_curation")
        print(f"manifest_written={args.manifest_out}")
        print("quick_templates_written=0")
        return

    candidate_rows: list[dict[str, Any]] = []
    for idx, template in enumerate(sorted(unique_candidates, key=lambda t: t.name), start=1):
        entries = parse_entries(template.width, template.height, template.blocks)
        entry_count = len(entries)
        lengths = [entry.length for entry in entries] if entries else []

        outcomes: list[AttemptOutcome] = []
        for _ in range(args.attempts):
            outcome = _run_attempt(
                template,
                words,
                scores,
                allow_reuse=args.allow_reuse,
                max_seconds=args.max_seconds,
                cp_sat_seconds=args.cp_sat_seconds,
                cp_sat_workers=args.cp_sat_workers,
                cp_sat_max_domain=args.cp_sat_max_domain,
                word_metadata_by_word=word_metadata_by_word,
                detail_corpus_by_ref=detail_corpus_by_ref,
                publish_cfg=publish_cfg,
            )
            outcomes.append(outcome)

        publishable_count = sum(1 for row in outcomes if row.publishable)
        solved_count = sum(1 for row in outcomes if row.solved)
        avg_time = sum(row.elapsed_seconds for row in outcomes) / max(len(outcomes), 1)
        blocker_counts = Counter(row.reason for row in outcomes if not row.publishable)
        cp_sat_counts = Counter(
            row.cp_sat_status for row in outcomes if row.cp_sat_status and row.cp_sat_status != "cp_sat_solved"
        )

        candidate_rows.append(
            {
                "template": template,
                "name": template.name,
                "entryCount": entry_count,
                "minLength": min(lengths) if lengths else 0,
                "maxLength": max(lengths) if lengths else 0,
                "blocks": len(template.blocks),
                "publishablePassRate": publishable_count / max(args.attempts, 1),
                "publishablePassCount": publishable_count,
                "solvedCount": solved_count,
                "avgSeconds": avg_time,
                "blockers": dict(blocker_counts),
                "cpSatFailures": dict(cp_sat_counts),
            }
        )
        print(
            f"[{idx}/{len(unique_candidates)}] {template.name}: "
            f"publishable={publishable_count}/{args.attempts} solved={solved_count}/{args.attempts} "
            f"avg={avg_time:.2f}s blockers={dict(blocker_counts)}"
        )

    passing = [row for row in candidate_rows if row["publishablePassCount"] > 0]
    passing.sort(
        key=lambda row: (
            row["publishablePassRate"],
            row["publishablePassCount"],
            -row["avgSeconds"],
        ),
        reverse=True,
    )
    selected = passing[: args.target_count]

    existing_output_paths = list(TEMPLATE_DIR.glob(f"{args.output_prefix}*.json"))
    for path in existing_output_paths:
        path.unlink()

    selected_rows: list[dict[str, Any]] = []
    for idx, row in enumerate(selected):
        template: Template = row["template"]
        name = f"{args.output_prefix}{idx}"
        payload = {
            "name": name,
            "width": template.width,
            "height": template.height,
            "blocks": sorted(list(template.blocks)),
            "sourceTemplate": row["name"],
            "curationStats": {
                "publishablePassRate": row["publishablePassRate"],
                "publishablePassCount": row["publishablePassCount"],
                "solvedCount": row["solvedCount"],
                "attempts": args.attempts,
                "avgSeconds": row["avgSeconds"],
                "entryCount": row["entryCount"],
                "minLength": row["minLength"],
                "maxLength": row["maxLength"],
                "blocks": row["blocks"],
                "blockers": row["blockers"],
                "cpSatFailures": row["cpSatFailures"],
            },
        }
        (TEMPLATE_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2))
        selected_rows.append(
            {
                "name": name,
                "sourceTemplate": row["name"],
                "publishablePassRate": row["publishablePassRate"],
                "publishablePassCount": row["publishablePassCount"],
                "solvedCount": row["solvedCount"],
                "avgSeconds": row["avgSeconds"],
                "entryCount": row["entryCount"],
                "minLength": row["minLength"],
                "maxLength": row["maxLength"],
                "blocks": row["blocks"],
            }
        )
        print(
            f"selected {name}: source={row['name']} pass_rate={row['publishablePassRate']:.2f} "
            f"entries={row['entryCount']} blocks={row['blocks']}"
        )

    manifest_payload = {
        "size": args.size,
        "outputPrefix": args.output_prefix,
        "allowReuse": args.allow_reuse,
        "attempts": args.attempts,
        "maxSeconds": args.max_seconds,
        "cpSatSeconds": args.cp_sat_seconds,
        "cpSatWorkers": args.cp_sat_workers,
        "cpSatMaxDomain": args.cp_sat_max_domain,
        "requireClues": args.require_clues,
        "candidateCount": len(candidate_rows),
        "selectedCount": len(selected_rows),
        "selected": selected_rows,
        "candidates": [
            {
                "name": row["name"],
                "entryCount": row["entryCount"],
                "minLength": row["minLength"],
                "maxLength": row["maxLength"],
                "blocks": row["blocks"],
                "publishablePassRate": row["publishablePassRate"],
                "publishablePassCount": row["publishablePassCount"],
                "solvedCount": row["solvedCount"],
                "avgSeconds": row["avgSeconds"],
                "blockers": row["blockers"],
                "cpSatFailures": row["cpSatFailures"],
            }
            for row in candidate_rows
        ],
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest_payload, indent=2))
    print(f"manifest_written={args.manifest_out}")
    print(f"quick_templates_written={len(selected_rows)}")


if __name__ == "__main__":
    main()
