from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.answer_metadata import load_payload_name_index, load_word_metadata, normalize_answer  # noqa: E402
from crossword.clue_product_owner import evaluate_generator_candidates  # noqa: E402
from crossword.provider_clue_workers import PROVIDER_ORDER, load_answer_queue, load_provider_result  # noqa: E402


ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
DEFAULT_WORDLIST_JSON = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_POKEAPI_CACHE_DIR = ROOT_DIR / "services" / "data" / "pokeapi"
DEFAULT_PROVIDER_CACHE_ROOT = ROOT_DIR / "data" / "crossword_provider_agents"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "crossword_product_owner"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate the next provider-generated clue bundle with the product-owner checklist.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--wordlist-json", type=Path, default=DEFAULT_WORDLIST_JSON)
    parser.add_argument("--pokeapi-cache-dir", type=Path, default=DEFAULT_POKEAPI_CACHE_DIR)
    parser.add_argument("--provider-cache-root", type=Path, default=DEFAULT_PROVIDER_CACHE_ROOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def _output_path(output_dir: Path, answer_key: str) -> Path:
    return output_dir / f"{answer_key}.json"


def main() -> None:
    args = parse_args()
    processed = {path.stem.upper() for path in args.output_dir.glob("*.json")}
    payload_name_index = load_payload_name_index(args.pokeapi_cache_dir)
    metadata_by_answer = load_word_metadata(args.wordlist_json, payload_name_index)

    for row in load_answer_queue(args.input_csv):
        answer_key = normalize_answer(row["answerKey"])
        if answer_key in processed:
            continue
        provider_candidates = []
        missing_provider = False
        for provider in PROVIDER_ORDER:
            result = load_provider_result(args.provider_cache_root / provider, answer_key)
            if result is None:
                missing_provider = True
                break
            provider_candidates.append(result)
        if missing_provider:
            continue

        metadata = metadata_by_answer.get(answer_key, {})
        answer_row = {
            "answerKey": answer_key,
            "answerDisplay": row["answerDisplay"],
            "sourceType": str(metadata.get("sourceType") or ""),
            "sourceRef": str(metadata.get("sourceRef") or ""),
            "sourceSlug": str(metadata.get("canonicalSlug") or ""),
        }
        evaluation = evaluate_generator_candidates(
            answer_row=answer_row,
            provider_candidates=provider_candidates,
        )
        output_path = _output_path(args.output_dir, answer_key)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(evaluation, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"{answer_key} {evaluation['reviewStatus']}")
        return

    print("queue exhausted")


if __name__ == "__main__":
    main()
