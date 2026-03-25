from __future__ import annotations

import argparse
from pathlib import Path
import sys


BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.provider_clue_workers import generate_next_provider_clue  # noqa: E402


ROOT_DIR = BASE_DIR.parents[1]
DEFAULT_INPUT_CSV = ROOT_DIR / "data" / "wordlist_crossword_answer_clue.csv"
DEFAULT_WORDLIST_JSON = ROOT_DIR / "data" / "wordlist_crossword.json"
DEFAULT_POKEAPI_CACHE_DIR = ROOT_DIR / "services" / "data" / "pokeapi"
DEFAULT_PROVIDER_CACHE_DIR = ROOT_DIR / "data" / "crossword_provider_agents" / "pokemondb"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the next PokemonDB-backed crossword clue candidate.")
    parser.add_argument("--input-csv", type=Path, default=DEFAULT_INPUT_CSV)
    parser.add_argument("--wordlist-json", type=Path, default=DEFAULT_WORDLIST_JSON)
    parser.add_argument("--pokeapi-cache-dir", type=Path, default=DEFAULT_POKEAPI_CACHE_DIR)
    parser.add_argument("--provider-cache-dir", type=Path, default=DEFAULT_PROVIDER_CACHE_DIR)
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--request-delay-seconds", type=float, default=0.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result = generate_next_provider_clue(
        provider="pokemondb",
        input_csv=args.input_csv,
        wordlist_json=args.wordlist_json,
        pokeapi_cache_dir=args.pokeapi_cache_dir,
        cache_dir=args.provider_cache_dir,
        timeout_seconds=args.timeout_seconds,
        request_delay_seconds=args.request_delay_seconds,
    )
    if result is None:
        print("queue exhausted")
        return
    print(f"{result['answerKey']} {result['status']} {result.get('provider', 'pokemondb')}")


if __name__ == "__main__":
    main()
