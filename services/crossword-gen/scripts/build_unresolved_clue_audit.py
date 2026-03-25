from __future__ import annotations

import argparse
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.clue_bank import write_json  # noqa: E402
from crossword.clue_unresolved_audit import build_unresolved_audit  # noqa: E402


ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_CLUE_BANK = ROOT_DIR / "data" / "clue_bank.json"
DEFAULT_OUTPUT = ROOT_DIR / "data" / "clue_bank_unresolved_audit.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the unresolved clue audit from the current clue bank.")
    parser.add_argument("--clue-bank", type=Path, default=DEFAULT_CLUE_BANK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = __import__("json").loads(args.clue_bank.read_text(encoding="utf-8"))
    entries = payload.get("entries") if isinstance(payload, dict) else []
    audit = build_unresolved_audit(entries if isinstance(entries, list) else [])
    write_json(args.output, audit)
    print(f"Unresolved answers: {audit['totalUnresolved']}")
    print(f"Buckets: {len(audit['buckets'])}")


if __name__ == "__main__":
    main()
