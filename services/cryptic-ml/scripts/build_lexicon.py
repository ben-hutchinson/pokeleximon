from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SERVICE_ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(SERVICE_ROOT))

from cryptic_ml.lexicon import build_lexicon, write_lexicon  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build cryptic lexicon from PokeAPI-derived wordlist")
    parser.add_argument(
        "--wordlist",
        type=Path,
        default=ROOT / "data" / "wordlist.json",
        help="Path to wordlist JSON",
    )
    parser.add_argument(
        "--pokeapi-cache",
        type=Path,
        default=ROOT / "services" / "data" / "pokeapi",
        help="Path to cached PokeAPI list pages",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=SERVICE_ROOT / "data" / "cryptic_lexicon.json",
        help="Output lexicon JSON path",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    entries = build_lexicon(wordlist_path=args.wordlist, pokeapi_cache_dir=args.pokeapi_cache)
    write_lexicon(args.output, entries)

    print(f"Wrote {args.output} ({len(entries)} answers)")

    samples = {"HEARTHOME", "MRMIME", "FIRESTONE"}
    sample_rows = [e for e in entries if e.answer_key in samples]
    for row in sorted(sample_rows, key=lambda r: r.answer_key):
        print(
            f"- {row.answer_key}: answer='{row.answer}' enum=({row.enumeration}) "
            f"source={row.source_type} rule={row.normalization_rule} slug={row.source_slug}"
        )


if __name__ == "__main__":
    main()
