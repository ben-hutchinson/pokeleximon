from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(SERVICE_ROOT))

from cryptic_ml.models import LexiconEntry  # noqa: E402
from cryptic_ml.pipeline import evaluate_entry  # noqa: E402
from cryptic_ml.scorer import load_scoring_config  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate sample cryptic clue candidates")
    parser.add_argument(
        "--lexicon",
        type=Path,
        default=SERVICE_ROOT / "data" / "cryptic_lexicon.json",
        help="Path to lexicon JSON",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Number of entries to sample",
    )
    parser.add_argument(
        "--top-per-entry",
        type=int,
        default=3,
        help="How many ranked candidates to print per entry",
    )
    parser.add_argument(
        "--score-config",
        type=Path,
        default=SERVICE_ROOT / "config" / "scoring.json",
        help="Path to JSON score configuration",
    )
    return parser.parse_args()


def load_lexicon(path: Path) -> list[LexiconEntry]:
    raw = json.loads(path.read_text())
    return [
        LexiconEntry(
            answer=row["answer"],
            answer_key=row["answerKey"],
            enumeration=row["enumeration"],
            answer_tokens=tuple(row["answerTokens"]),
            source_type=row["sourceType"],
            source_ref=row["sourceRef"],
            source_slug=row["sourceSlug"],
            normalization_rule=row["normalizationRule"],
            is_multiword=bool(row["isMultiword"]),
            metadata=row.get("metadata", {}),
        )
        for row in raw
    ]


def main() -> None:
    args = parse_args()
    entries = load_lexicon(args.lexicon)
    scoring_config = load_scoring_config(args.score_config)

    preferred_keys = {"MRMIME", "FIRESTONE", "HEARTHOME"}
    picked = [e for e in entries if e.answer_key in preferred_keys]

    if len(picked) < args.limit:
        seen = {e.answer_key for e in picked}
        for row in entries:
            if row.answer_key in seen:
                continue
            picked.append(row)
            seen.add(row.answer_key)
            if len(picked) >= args.limit:
                break

    for entry in picked[: args.limit]:
        print(f"\n== {entry.answer} ({entry.enumeration}) [{entry.source_type}] ==")
        evaluations = evaluate_entry(entry, scoring_config=scoring_config)
        if not evaluations:
            print("  no plans produced")
            continue
        for idx, item in enumerate(evaluations[: args.top_per_entry], start=1):
            status = "PASS" if item.validation.is_valid else "FAIL"
            print(
                f"  {idx}. [{status}] score={item.score.score:05.2f} "
                f"{item.candidate.mechanism}: {item.candidate.clue}"
            )
            print(f"      wordplay: {item.candidate.plan_wordplay}")
            if item.validation.issues:
                for issue in item.validation.issues:
                    print(f"      - {issue.severity}:{issue.code} -> {issue.message}")
            top_reasons = sorted(
                item.score.components,
                key=lambda component: abs(component.delta),
                reverse=True,
            )[:3]
            for component in top_reasons:
                sign = "+" if component.delta >= 0 else ""
                print(f"      score[{component.name}] {sign}{component.delta:.1f}: {component.note}")


if __name__ == "__main__":
    main()
