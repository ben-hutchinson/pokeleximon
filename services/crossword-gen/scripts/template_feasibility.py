from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.feasibility import build_words_by_length, evaluate_template_feasibility  # noqa: E402
from crossword.grid import parse_entries  # noqa: E402
from crossword.templates import load_templates  # noqa: E402

ROOT_DIR = BASE_DIR.parents[1]
WORDLIST_PATH = ROOT_DIR / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = ROOT_DIR / "data" / "wordlist_crossword.json"
TEMPLATE_DIR = BASE_DIR / "data" / "templates"


def load_words() -> list[str]:
    path = WORDLIST_CROSSWORD_PATH if WORDLIST_CROSSWORD_PATH.exists() else WORDLIST_PATH
    if not path.exists():
        raise FileNotFoundError(f"Missing wordlist: {path}")
    data = json.loads(path.read_text())
    return sorted({item.get("word", "") for item in data if item.get("word")})


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate AC-3 feasibility for templates")
    parser.add_argument("--size", type=int, default=13)
    parser.add_argument("--min-domain", type=int, default=2)
    args = parser.parse_args()

    words = load_words()
    words_by_length = build_words_by_length(words, min_len=4, max_len=args.size)
    templates = [t for t in load_templates(TEMPLATE_DIR) if t.width == args.size]

    feasible_count = 0
    total = 0
    for template in sorted(templates, key=lambda t: t.name):
        entries = parse_entries(template.width, template.height, template.blocks)
        report = evaluate_template_feasibility(
            entries,
            words_by_length=words_by_length,
            min_post_ac3_domain=args.min_domain,
        )
        total += 1
        if report.feasible:
            feasible_count += 1
        reason = report.reason or "ok"
        min_domain = min(report.domain_sizes.values()) if report.domain_sizes else 0
        print(
            f"{template.name}: feasible={report.feasible} min_domain={min_domain} reason={reason}"
        )

    print(f"feasible_templates={feasible_count}/{total}")


if __name__ == "__main__":
    main()
