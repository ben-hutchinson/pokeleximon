from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from time import perf_counter

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.grid import Grid, parse_entries  # noqa: E402
from crossword.seeding import build_seed_assignment  # noqa: E402
from crossword.solver import Solver, SolverConfig  # noqa: E402
from crossword.templates import load_templates  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"
SIZE = 13


def load_words_and_scores() -> tuple[list[str], dict[str, float]]:
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
    return words, scores


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Curate fillable quick templates from candidates")
    parser.add_argument("--input-prefix", type=str, default="quick_candidate_13x13_")
    parser.add_argument("--output-prefix", type=str, default="quick_13x13_")
    parser.add_argument("--target-count", type=int, default=8)
    parser.add_argument("--attempts", type=int, default=4)
    parser.add_argument("--max-seconds", type=float, default=20.0)
    parser.add_argument("--max-steps", type=int, default=800000)
    parser.add_argument("--seeded", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    words, scores = load_words_and_scores()
    templates = [
        t
        for t in load_templates(TEMPLATE_DIR)
        if t.width == SIZE and t.name.startswith(args.input_prefix)
    ]
    templates = sorted(templates, key=lambda t: t.name)
    if not templates:
        print(f"no input templates matched prefix={args.input_prefix!r}")
        return

    passing: list[tuple[float, object, dict[str, float]]] = []
    for template in templates:
        entries = parse_entries(template.width, template.height, template.blocks)
        lengths = {entry.length for entry in entries}
        if not entries or min(lengths) < 4:
            print(f"{template.name}: skipped")
            continue

        filtered_words = [word for word in words if 4 <= len(word) <= SIZE and len(word) in lengths]
        words_by_length: dict[int, list[str]] = {}
        for word in filtered_words:
            words_by_length.setdefault(len(word), []).append(word)

        solved_count = 0
        best_depth = 0
        total_depth = 0
        total_checks = 0
        total_time = 0.0

        for _ in range(args.attempts):
            seed_assignments: dict[str, str] | None = None
            if args.seeded:
                seed_assignments = build_seed_assignment(
                    entries,
                    words_by_length=words_by_length,
                    word_scores=scores,
                    seed_count=2,
                    min_seed_length=11,
                    pool_size=250,
                    max_tries=120,
                )
            solver = Solver(
                Grid(template.width, template.height, template.blocks),
                entries,
                filtered_words,
                SolverConfig(
                    max_steps=args.max_steps,
                    max_candidates=8000,
                    weighted_shuffle=True,
                    allow_reuse=True,
                    max_seconds=args.max_seconds,
                    debug=False,
                ),
                word_scores=scores,
                initial_assignments=seed_assignments,
            )
            start = perf_counter()
            solved = solver.solve()
            elapsed = perf_counter() - start
            if solved:
                solved_count += 1
            best_depth = max(best_depth, solver.max_depth)
            total_depth += solver.max_depth
            total_checks += solver.candidate_checks
            total_time += elapsed

        solve_rate = solved_count / max(args.attempts, 1)
        avg_depth = total_depth / max(args.attempts, 1)
        avg_checks = total_checks / max(args.attempts, 1)
        avg_time = total_time / max(args.attempts, 1)
        blocks = len(template.blocks)
        # Prioritize solve rate, then depth and quick-style shape stability.
        score = (
            solve_rate * 10000.0
            + best_depth * 20.0
            + avg_depth * 10.0
            - abs(blocks - 30) * 2.0
            - avg_time
        )

        stats = {
            "solve_rate": solve_rate,
            "solved_count": float(solved_count),
            "best_depth": float(best_depth),
            "avg_depth": avg_depth,
            "avg_checks": avg_checks,
            "avg_time": avg_time,
            "blocks": float(blocks),
        }
        print(
            f"{template.name}: solved={solved_count}/{args.attempts} "
            f"depth(best/avg)={best_depth}/{avg_depth:.2f} "
            f"checks(avg)={avg_checks:.0f} time(avg)={avg_time:.2f}s"
        )
        if solved_count > 0:
            passing.append((score, template, stats))

    if not passing:
        print("fillable_templates_written=0 (existing curated templates preserved)")
        return

    passing.sort(
        key=lambda item: (item[2]["solve_rate"], item[2]["best_depth"], item[0]),
        reverse=True,
    )
    chosen = passing[: args.target_count]

    existing_output_paths = list(TEMPLATE_DIR.glob(f"{args.output_prefix}*.json"))
    for path in existing_output_paths:
        path.unlink()

    for idx, (_, template, stats) in enumerate(chosen):
        name = f"{args.output_prefix}{idx}"
        out = {
            "name": name,
            "width": template.width,
            "height": template.height,
            "blocks": sorted(list(template.blocks)),
            "sourceTemplate": template.name,
            "curationStats": stats,
        }
        (TEMPLATE_DIR / f"{name}.json").write_text(json.dumps(out, indent=2))
        print(
            f"{name}: from={template.name} solve_rate={stats['solve_rate']:.2f} "
            f"best_depth={int(stats['best_depth'])} blocks={int(stats['blocks'])}"
        )

    print(f"fillable_templates_written={len(chosen)}")


if __name__ == "__main__":
    main()
