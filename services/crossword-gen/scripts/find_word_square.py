from __future__ import annotations

import json
from pathlib import Path
from collections import defaultdict

WORDLIST_PATH = Path(__file__).resolve().parents[3] / "data" / "wordlist.json"


def load_words(length: int) -> list[str]:
    data = json.loads(WORDLIST_PATH.read_text())
    return [item["word"] for item in data if len(item["word"]) == length]


def build_prefix_map(words: list[str]) -> dict[str, list[str]]:
    prefix_map: dict[str, list[str]] = defaultdict(list)
    for word in words:
        for i in range(len(word) + 1):
            prefix_map[word[:i]].append(word)
    return prefix_map


def find_square(n: int) -> list[str] | None:
    words = load_words(n)
    prefix_map = build_prefix_map(words)

    square: list[str] = []

    def is_valid_prefixes() -> bool:
        for col in range(len(square[0])):
            prefix = "".join(row[col] for row in square)
            if prefix not in prefix_map:
                return False
        return True

    def backtrack() -> bool:
        if len(square) == n:
            return True
        if square:
            if not is_valid_prefixes():
                return False
        for word in words:
            square.append(word)
            if backtrack():
                return True
            square.pop()
        return False

    if backtrack():
        return square
    return None


def main() -> None:
    for n in (5, 6, 7):
        square = find_square(n)
        if square:
            print(f"Found {n}x{n} word square:")
            for row in square:
                print(row)
            return
        print(f"No {n}x{n} word square found")


if __name__ == "__main__":
    main()
