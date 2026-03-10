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

try:
    from ortools.sat.python import cp_model
except Exception:  # pragma: no cover
    cp_model = None

ROOT_DIR = BASE_DIR.parents[1]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
DETAIL_CORPUS_PATH = ROOT_DIR / "data" / "pokeapi_detail_corpus.json"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"


@dataclass(frozen=True)
class LayoutModel:
    model: Any
    block: dict[tuple[int, int], Any]
    open_: dict[tuple[int, int], Any]
    num_blocks: Any
    num_open: Any
    entry_count: Any
    across_count: Any
    down_count: Any
    across_down_diff: Any


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate connected Guardian-style 13x13 layouts with CP-SAT and fill screening"
    )
    parser.add_argument("--size", type=int, default=13)
    parser.add_argument("--target-count", type=int, default=16)
    parser.add_argument("--max-layout-attempts", type=int, default=250)
    parser.add_argument("--layout-seconds", type=float, default=2.0)
    parser.add_argument("--layout-workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=20260211)

    parser.add_argument("--min-word-len", type=int, default=4)
    parser.add_argument("--min-blocks", type=int, default=28)
    parser.add_argument("--max-blocks", type=int, default=56)
    parser.add_argument("--target-blocks", type=int, default=40)
    parser.add_argument("--min-entries", type=int, default=24)
    parser.add_argument("--max-entries", type=int, default=44)
    parser.add_argument("--target-entries", type=int, default=32)
    parser.add_argument("--max-across-down-diff", type=int, default=6)

    parser.add_argument("--skip-fill", action="store_true")
    parser.add_argument("--fill-max-seconds", type=float, default=6.0)
    parser.add_argument("--fill-cp-sat-seconds", type=float, default=4.0)
    parser.add_argument("--fill-cp-sat-max-domain", type=int, default=250)
    parser.add_argument("--fill-cp-sat-workers", type=int, default=8)
    parser.add_argument("--allow-reuse", action="store_true")
    parser.add_argument("--require-clues", action="store_true")

    parser.add_argument("--output-prefix", type=str, default="quick_connected_candidate_13x13_")
    parser.add_argument(
        "--manifest-out",
        type=Path,
        default=TEMPLATE_DIR / "quick_connected_candidate_13x13_manifest.json",
    )
    return parser.parse_args()


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


def _line_run_automaton(min_word_len: int) -> tuple[int, list[int], list[tuple[int, int, int]]]:
    # States:
    # 0 = at/after block boundary
    # 1..min_word_len-1 = in an open run shorter than min
    # min_word_len = in an open run of valid length >= min
    start = 0
    valid_finals = [0, min_word_len]
    transitions: list[tuple[int, int, int]] = []

    # block value=1, open value=0
    transitions.append((0, 1, 0))
    transitions.append((0, 0, 1 if min_word_len > 1 else min_word_len))
    for run in range(1, min_word_len):
        # Continue open run.
        nxt = min_word_len if run == (min_word_len - 1) else run + 1
        transitions.append((run, 0, nxt))
        # No transition on block from short runs => invalid.
    transitions.append((min_word_len, 0, min_word_len))
    transitions.append((min_word_len, 1, 0))
    return start, valid_finals, transitions


def _neighbors(size: int, cell: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = cell
    out: list[tuple[int, int]] = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < size and 0 <= ny < size:
            out.append((nx, ny))
    return out


def _build_layout_model(args: argparse.Namespace) -> LayoutModel:
    if cp_model is None:
        raise RuntimeError("OR-Tools is unavailable. Install `ortools` in crossword-gen requirements.")

    n = args.size
    model = cp_model.CpModel()
    block: dict[tuple[int, int], Any] = {}
    open_: dict[tuple[int, int], Any] = {}

    for y in range(n):
        for x in range(n):
            b = model.NewBoolVar(f"b_{x}_{y}")
            o = model.NewBoolVar(f"o_{x}_{y}")
            block[(x, y)] = b
            open_[(x, y)] = o
            model.Add(b + o == 1)

    # 180-degree rotational symmetry.
    for y in range(n):
        for x in range(n):
            mx, my = n - 1 - x, n - 1 - y
            if (x, y) > (mx, my):
                continue
            model.Add(block[(x, y)] == block[(mx, my)])

    # Force center open for stable connectivity flow root.
    root = (n // 2, n // 2)
    model.Add(open_[root] == 1)

    num_blocks = model.NewIntVar(0, n * n, "num_blocks")
    num_open = model.NewIntVar(0, n * n, "num_open")
    model.Add(num_blocks == sum(block.values()))
    model.Add(num_open == sum(open_.values()))
    model.Add(num_blocks >= args.min_blocks)
    model.Add(num_blocks <= args.max_blocks)

    # No across/down open runs shorter than min length.
    start_state, final_states, transitions = _line_run_automaton(args.min_word_len)
    for y in range(n):
        row = [block[(x, y)] for x in range(n)]
        model.AddAutomaton(row, start_state, final_states, transitions)
    for x in range(n):
        col = [block[(x, y)] for y in range(n)]
        model.AddAutomaton(col, start_state, final_states, transitions)

    across_starts: list[Any] = []
    down_starts: list[Any] = []

    for y in range(n):
        for x in range(n):
            if x + 1 < n:
                s = model.NewBoolVar(f"a_start_{x}_{y}")
                across_starts.append(s)
                if x == 0:
                    left_cond = 1
                else:
                    left_cond = block[(x - 1, y)]
                    model.Add(s <= left_cond)
                model.Add(s <= open_[(x, y)])
                model.Add(s <= open_[(x + 1, y)])
                if x == 0:
                    model.Add(s >= open_[(x, y)] + open_[(x + 1, y)] - 1)
                else:
                    model.Add(s >= open_[(x, y)] + left_cond + open_[(x + 1, y)] - 2)

            if y + 1 < n:
                s = model.NewBoolVar(f"d_start_{x}_{y}")
                down_starts.append(s)
                if y == 0:
                    up_cond = 1
                else:
                    up_cond = block[(x, y - 1)]
                    model.Add(s <= up_cond)
                model.Add(s <= open_[(x, y)])
                model.Add(s <= open_[(x, y + 1)])
                if y == 0:
                    model.Add(s >= open_[(x, y)] + open_[(x, y + 1)] - 1)
                else:
                    model.Add(s >= open_[(x, y)] + up_cond + open_[(x, y + 1)] - 2)

    across_count = model.NewIntVar(0, n * n, "across_count")
    down_count = model.NewIntVar(0, n * n, "down_count")
    entry_count = model.NewIntVar(0, n * n, "entry_count")
    model.Add(across_count == sum(across_starts))
    model.Add(down_count == sum(down_starts))
    model.Add(entry_count == across_count + down_count)
    model.Add(entry_count >= args.min_entries)
    model.Add(entry_count <= args.max_entries)

    across_down_diff = model.NewIntVar(0, n * n, "across_down_diff")
    model.AddAbsEquality(across_down_diff, across_count - down_count)
    model.Add(across_down_diff <= args.max_across_down_diff)

    # Connectedness over open cells via single-commodity flow from root.
    max_flow = n * n
    flow: dict[tuple[tuple[int, int], tuple[int, int]], Any] = {}
    cells = [(x, y) for y in range(n) for x in range(n)]

    for cell in cells:
        for nb in _neighbors(n, cell):
            var = model.NewIntVar(0, max_flow, f"f_{cell[0]}_{cell[1]}_{nb[0]}_{nb[1]}")
            flow[(cell, nb)] = var
            model.Add(var <= max_flow * open_[cell])
            model.Add(var <= max_flow * open_[nb])

    for cell in cells:
        inflow = sum(flow[(nb, cell)] for nb in _neighbors(n, cell))
        outflow = sum(flow[(cell, nb)] for nb in _neighbors(n, cell))
        if cell == root:
            model.Add(outflow - inflow == num_open - 1)
        else:
            model.Add(inflow - outflow == open_[cell])

    # Objective to keep Guardian-like profile.
    block_dev = model.NewIntVar(0, n * n, "block_dev")
    entry_dev = model.NewIntVar(0, n * n, "entry_dev")
    model.AddAbsEquality(block_dev, num_blocks - args.target_blocks)
    model.AddAbsEquality(entry_dev, entry_count - args.target_entries)
    model.Minimize(block_dev * 100 + entry_dev * 60 + across_down_diff * 8)

    return LayoutModel(
        model=model,
        block=block,
        open_=open_,
        num_blocks=num_blocks,
        num_open=num_open,
        entry_count=entry_count,
        across_count=across_count,
        down_count=down_count,
        across_down_diff=across_down_diff,
    )


def _extract_blocks(layout: LayoutModel, solver: Any, size: int) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y in range(size)
        for x in range(size)
        if solver.Value(layout.block[(x, y)]) == 1
    }


def _add_no_good(layout: LayoutModel, solver: Any, size: int) -> None:
    literals = []
    for y in range(size):
        for x in range(size):
            var = layout.block[(x, y)]
            if solver.Value(var) == 1:
                literals.append(var)
            else:
                literals.append(var.Not())
    layout.model.Add(sum(literals) <= len(literals) - 1)


def _build_publishability_payload(
    size: int,
    blocks: set[tuple[int, int]],
    grid: Grid,
    entries,
    *,
    word_metadata_by_word: dict[str, dict[str, str]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    cells = []
    for y in range(size):
        for x in range(size):
            if (x, y) in blocks:
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
        "grid": {"width": size, "height": size, "cells": cells},
        "entries": payload_entries,
    }


def _fill_and_check(
    *,
    args: argparse.Namespace,
    blocks: set[tuple[int, int]],
    words: list[str],
    scores: dict[str, float],
    word_metadata_by_word: dict[str, dict[str, str]],
    detail_corpus_by_ref: dict[str, dict[str, Any]],
    publish_cfg: PublishabilityConfig,
) -> tuple[bool, str, dict[str, Any]]:
    entries = parse_entries(args.size, args.size, blocks)
    if not entries:
        return False, "no_entries", {}
    lengths = {entry.length for entry in entries}
    if min(lengths) < args.min_word_len or max(lengths) > args.size:
        return False, "slot_length_out_of_bounds", {}

    filtered_words = [word for word in words if len(word) in lengths]
    solver = Solver(
        Grid(args.size, args.size, blocks),
        entries,
        filtered_words,
        SolverConfig(
            max_steps=600000,
            max_candidates=8000,
            weighted_shuffle=True,
            allow_reuse=args.allow_reuse,
            max_seconds=args.fill_max_seconds,
            debug=False,
            use_min_conflicts=False,
            use_cp_sat=True,
            cp_sat_first=True,
            cp_sat_max_seconds=args.fill_cp_sat_seconds,
            cp_sat_max_domain_per_entry=args.fill_cp_sat_max_domain,
            cp_sat_workers=args.fill_cp_sat_workers,
        ),
        word_scores=scores,
    )
    start = perf_counter()
    solved = solver.solve()
    elapsed = perf_counter() - start
    if not solved:
        reason = solver.cp_sat_status or "fill_unsolved"
        return (
            False,
            reason,
            {
                "fillElapsedSeconds": elapsed,
                "cpSatStatus": solver.cp_sat_status,
                "steps": solver.steps,
                "depth": solver.max_depth,
                "checks": solver.candidate_checks,
            },
        )

    publishability = evaluate_publishability(
        _build_publishability_payload(
            args.size,
            blocks,
            solver.grid,
            entries,
            word_metadata_by_word=word_metadata_by_word,
            detail_corpus_by_ref=detail_corpus_by_ref,
        ),
        config=publish_cfg,
    )
    if not publishability.publishable:
        reason = publishability.blockers[0] if publishability.blockers else "publishability_failed"
        return (
            False,
            f"publishability:{reason}",
            {
                "fillElapsedSeconds": elapsed,
                "publishabilityMetrics": publishability.metrics,
                "publishabilityChecks": publishability.checks,
            },
        )

    return (
        True,
        "ok",
        {
            "fillElapsedSeconds": elapsed,
            "entryCount": len(entries),
            "minLength": min(lengths),
            "maxLength": max(lengths),
        },
    )


def main() -> None:
    args = parse_args()
    words, scores, word_metadata_by_word = load_words_and_scores()
    detail_corpus_by_ref = load_detail_corpus_index(DETAIL_CORPUS_PATH)
    publish_cfg = PublishabilityConfig(require_clues=args.require_clues)
    layout = _build_layout_model(args)

    stage_counts = Counter()
    candidates: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []

    for attempt in range(1, args.max_layout_attempts + 1):
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = args.layout_seconds
        solver.parameters.num_search_workers = max(1, args.layout_workers)
        solver.parameters.random_seed = args.seed + attempt
        solver.parameters.randomize_search = True

        start = perf_counter()
        status = solver.Solve(layout.model)
        layout_elapsed = perf_counter() - start
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            stage_counts["layout_no_solution"] += 1
            break

        blocks = _extract_blocks(layout, solver, args.size)
        _add_no_good(layout, solver, args.size)

        candidate_record: dict[str, Any] = {
            "attempt": attempt,
            "blocks": len(blocks),
            "openCells": args.size * args.size - len(blocks),
            "layoutElapsedSeconds": round(layout_elapsed, 4),
            "entryCountLayout": int(solver.Value(layout.entry_count)),
            "acrossCountLayout": int(solver.Value(layout.across_count)),
            "downCountLayout": int(solver.Value(layout.down_count)),
            "acrossDownDiffLayout": int(solver.Value(layout.across_down_diff)),
        }

        if args.skip_fill:
            accepted.append(
                {
                    "blocks": blocks,
                    "score": 100000.0 - layout_elapsed * 50.0,
                    "stats": candidate_record,
                }
            )
            stage_counts["accepted"] += 1
            candidates.append({**candidate_record, "result": "accepted_no_fill"})
        else:
            ok, reason, details = _fill_and_check(
                args=args,
                blocks=blocks,
                words=words,
                scores=scores,
                word_metadata_by_word=word_metadata_by_word,
                detail_corpus_by_ref=detail_corpus_by_ref,
                publish_cfg=publish_cfg,
            )
            if ok:
                score = (
                    100000.0
                    - layout_elapsed * 30.0
                    - float(details.get("fillElapsedSeconds", 0.0)) * 100.0
                )
                accepted.append(
                    {
                        "blocks": blocks,
                        "score": score,
                        "stats": {**candidate_record, **details},
                    }
                )
                stage_counts["accepted"] += 1
                candidates.append({**candidate_record, **details, "result": "accepted"})
            else:
                stage_counts[reason] += 1
                candidates.append({**candidate_record, **details, "result": reason})

        if len(accepted) >= args.target_count * 2:
            break

    accepted.sort(key=lambda row: row["score"], reverse=True)
    selected = accepted[: args.target_count]

    if not selected:
        print("guardian_connected_templates_written=0 (existing connected candidates preserved)")
    else:
        TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
        for path in TEMPLATE_DIR.glob(f"{args.output_prefix}*.json"):
            path.unlink()
        for idx, row in enumerate(selected):
            name = f"{args.output_prefix}{idx}"
            payload = {
                "name": name,
                "width": args.size,
                "height": args.size,
                "blocks": sorted(list(row["blocks"])),
                "curationStats": row["stats"],
            }
            (TEMPLATE_DIR / f"{name}.json").write_text(json.dumps(payload, indent=2))
            print(
                f"{name}: blocks={row['stats']['blocks']} entries={row['stats']['entryCountLayout']} "
                f"across/down={row['stats']['acrossCountLayout']}/{row['stats']['downCountLayout']} "
                f"layout={row['stats']['layoutElapsedSeconds']:.2f}s"
            )
        print(f"guardian_connected_templates_written={len(selected)}")

    manifest = {
        "size": args.size,
        "seed": args.seed,
        "targetCount": args.target_count,
        "maxLayoutAttempts": args.max_layout_attempts,
        "layoutSeconds": args.layout_seconds,
        "layoutWorkers": args.layout_workers,
        "skipFill": args.skip_fill,
        "fillMaxSeconds": args.fill_max_seconds,
        "fillCpSatSeconds": args.fill_cp_sat_seconds,
        "fillCpSatMaxDomain": args.fill_cp_sat_max_domain,
        "allowReuse": args.allow_reuse,
        "requireClues": args.require_clues,
        "outputPrefix": args.output_prefix,
        "selectedCount": len(selected),
        "stageCounts": dict(stage_counts),
        "selected": [
            {
                "name": f"{args.output_prefix}{idx}",
                **row["stats"],
            }
            for idx, row in enumerate(selected)
        ],
        "candidates": candidates,
    }
    args.manifest_out.parent.mkdir(parents=True, exist_ok=True)
    args.manifest_out.write_text(json.dumps(manifest, indent=2))
    print(f"manifest_written={args.manifest_out}")
    print(f"stage_counts={dict(stage_counts)}")


if __name__ == "__main__":
    main()
