from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.detail_corpus import build_answer_corpus, build_detail_corpus  # noqa: E402


ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_WORDLIST_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_CACHE_DIR = ROOT_DIR / "services" / "data" / "pokeapi"
DEFAULT_OUTPUT_PATH = ROOT_DIR / "data" / "pokeapi_detail_corpus.json"
DEFAULT_REPORT_PATH = ROOT_DIR / "data" / "pokeapi_detail_corpus_report.json"
DEFAULT_ANSWER_OUTPUT_PATH = ROOT_DIR / "data" / "pokeapi_answer_corpus.json"
DEFAULT_ANSWER_REPORT_PATH = ROOT_DIR / "data" / "pokeapi_answer_corpus_report.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build an English clue/detail corpus from cached PokeAPI details and crossword wordlist refs"
    )
    parser.add_argument("--wordlist", type=Path, default=DEFAULT_WORDLIST_PATH)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    parser.add_argument("--answer-output", type=Path, default=DEFAULT_ANSWER_OUTPUT_PATH)
    parser.add_argument("--answer-report", type=Path, default=DEFAULT_ANSWER_REPORT_PATH)
    parser.add_argument("--fetch-missing", action="store_true")
    parser.add_argument("--fetch-timeout-seconds", type=float, default=20.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.0)
    parser.add_argument("--max-fetch", type=int, default=0)
    parser.add_argument("--progress-every", type=int, default=250)
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if not args.wordlist.exists():
        raise FileNotFoundError(f"Missing wordlist at {args.wordlist}")
    if not args.cache_dir.exists():
        raise FileNotFoundError(f"Missing cache directory at {args.cache_dir}")

    wordlist_rows = json.loads(args.wordlist.read_text())
    progress_callback = None
    if args.fetch_missing and args.progress_every > 0:
        progress_callback = lambda msg: print(f"[detail-corpus] {msg}")

    rows, report = build_detail_corpus(
        wordlist_rows=wordlist_rows,
        cache_dir=args.cache_dir,
        fetch_missing=args.fetch_missing,
        fetch_timeout_seconds=args.fetch_timeout_seconds,
        request_delay_seconds=args.request_delay_seconds,
        max_fetch=args.max_fetch,
        progress_every=args.progress_every,
        progress_callback=progress_callback,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(rows, indent=2))
    args.report.write_text(json.dumps(report, indent=2))

    detail_index = {
        str(row.get("sourceRef", "")).strip(): row
        for row in rows
        if isinstance(row, dict) and str(row.get("sourceRef", "")).strip()
    }
    answer_rows, answer_report = build_answer_corpus(
        wordlist_rows=wordlist_rows,
        detail_corpus_by_ref=detail_index,
    )
    args.answer_output.parent.mkdir(parents=True, exist_ok=True)
    args.answer_report.parent.mkdir(parents=True, exist_ok=True)
    args.answer_output.write_text(json.dumps(answer_rows, indent=2))
    args.answer_report.write_text(json.dumps(answer_report, indent=2))

    print(f"Wrote {args.output} ({len(rows)} source refs)")
    print(f"Report: {args.report}")
    print(f"Wrote {args.answer_output} ({len(answer_rows)} answers)")
    print(f"Answer report: {args.answer_report}")
    print(
        f"Coverage: withDetail={report['withDetail']}/{report['totalSourceRefs']} "
        f"withClue={report['withClue']}/{report['totalSourceRefs']}"
    )
    print(
        f"Answer coverage: withDetail={answer_report['withDetail']}/{answer_report['totalAnswers']} "
        f"withClue={answer_report['withClue']}/{answer_report['totalAnswers']}"
    )
    if args.fetch_missing:
        print(
            "Fetch stats: "
            f"attempted={report['fetchAttempts']} success={report['fetchSuccesses']} "
            f"failed={report['fetchFailures']} skippedByLimit={report['fetchSkippedByLimit']}"
        )
        error_counts = report.get("fetchErrorCounts", {})
        if isinstance(error_counts, dict) and error_counts:
            top = sorted(error_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
            print("Top fetch failures:", ", ".join(f"{k}:{v}" for k, v in top))


if __name__ == "__main__":
    main()
