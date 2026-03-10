from __future__ import annotations

import json
import random
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from crossword.grid import parse_entries  # noqa: E402
from crossword.feasibility import build_words_by_length, evaluate_template_feasibility  # noqa: E402

TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "data" / "templates"

MIN_LEN = 4
SIZE = 13
MIN_BLOCKS = 14
MAX_BLOCKS = 22
MIN_INTERSECTIONS = 2
MIN_INTERSECTION_LETTERS = 1
MAX_LEN4_ENTRIES = 10
MAX_LONG_ENTRIES = 10
MAX_LONG_SHORT_CROSSINGS = 24
MIN_POST_AC3_DOMAIN = 2
MAX_TRIES = 50000

WORDLIST_PATH = Path(__file__).resolve().parents[3] / "data" / "wordlist.json"
WORDLIST_CROSSWORD_PATH = Path(__file__).resolve().parents[3] / "data" / "wordlist_crossword.json"


def load_letter_sets() -> dict[int, list[set[str]]]:
    path = WORDLIST_CROSSWORD_PATH if WORDLIST_CROSSWORD_PATH.exists() else WORDLIST_PATH
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    letters_by_len: dict[int, list[set[str]]] = {}
    for item in data:
        word = item.get("word", "")
        if not word:
            continue
        length = len(word)
        if length not in letters_by_len:
            letters_by_len[length] = [set() for _ in range(length)]
        for idx, ch in enumerate(word):
            letters_by_len[length][idx].add(ch)
    return letters_by_len


def entry_intersections(entries):
    counts = {entry.id: 0 for entry in entries}
    cell_map: dict[tuple[int, int], list[str]] = {}
    for entry in entries:
        for cell in entry.cells:
            cell_map.setdefault(cell, []).append(entry.id)
    for cell_entries in cell_map.values():
        if len(cell_entries) > 1:
            for entry_id in cell_entries:
                counts[entry_id] += 1
    return counts


def load_words() -> list[str]:
    path = WORDLIST_CROSSWORD_PATH if WORDLIST_CROSSWORD_PATH.exists() else WORDLIST_PATH
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return sorted({item.get("word", "") for item in data if item.get("word")})


def count_long_short_crossings(entries) -> int:
    cell_map: dict[tuple[int, int], list] = {}
    for entry in entries:
        for cell in entry.cells:
            cell_map.setdefault(cell, []).append(entry)
    total = 0
    for cell_entries in cell_map.values():
        if len(cell_entries) < 2:
            continue
        for i in range(len(cell_entries)):
            for j in range(i + 1, len(cell_entries)):
                a = cell_entries[i]
                b = cell_entries[j]
                la = len(a.cells)
                lb = len(b.cells)
                if (la >= 12 and lb <= 5) or (lb >= 12 and la <= 5):
                    total += 1
    return total


def valid_template(
    width: int,
    height: int,
    blocks: set[tuple[int, int]],
    letters_by_len: dict[int, list[set[str]]],
    words_by_length: dict[int, list[str]],
) -> bool:
    entries = parse_entries(width, height, blocks)
    if not entries:
        return False
    lengths = [e.length for e in entries]
    if min(lengths) < MIN_LEN:
        return False
    intersections = entry_intersections(entries)
    if any(count < MIN_INTERSECTIONS for count in intersections.values()):
        return False
    len4_entries = sum(1 for length in lengths if length == 4)
    long_entries = sum(1 for length in lengths if length >= 12)
    if len4_entries > MAX_LEN4_ENTRIES:
        return False
    if long_entries > MAX_LONG_ENTRIES:
        return False
    if count_long_short_crossings(entries) > MAX_LONG_SHORT_CROSSINGS:
        return False
    if letters_by_len:
        entry_map = {entry.id: entry for entry in entries}
        cell_map: dict[tuple[int, int], list[str]] = {}
        for entry in entries:
            for idx, cell in enumerate(entry.cells):
                cell_map.setdefault(cell, []).append((entry.id, idx))
        for cell_entries in cell_map.values():
            if len(cell_entries) < 2:
                continue
            for i in range(len(cell_entries)):
                for j in range(i + 1, len(cell_entries)):
                    entry_a, pos_a = cell_entries[i]
                    entry_b, pos_b = cell_entries[j]
                    len_a = entry_map[entry_a].length
                    len_b = entry_map[entry_b].length
                    letters_a = letters_by_len.get(len_a, [])
                    letters_b = letters_by_len.get(len_b, [])
                    if not letters_a or not letters_b:
                        return False
                    if pos_a >= len(letters_a) or pos_b >= len(letters_b):
                        return False
                    if letters_a[pos_a].isdisjoint(letters_b[pos_b]):
                        return False
                    if len(letters_a[pos_a].intersection(letters_b[pos_b])) < MIN_INTERSECTION_LETTERS:
                        return False
    if words_by_length:
        report = evaluate_template_feasibility(
            entries,
            words_by_length=words_by_length,
            min_post_ac3_domain=MIN_POST_AC3_DOMAIN,
        )
        if not report.feasible:
            return False
    return True


def main() -> None:
    TEMPLATE_DIR.mkdir(parents=True, exist_ok=True)
    found = 0
    positions = [(x, y) for x in range(SIZE) for y in range(SIZE)]
    center = (SIZE // 2, SIZE // 2)
    positions.remove(center)

    def mirrored(pos):
        return (SIZE - 1 - pos[0], SIZE - 1 - pos[1])

    letters_by_len = load_letter_sets()
    words = load_words()
    words_by_length = build_words_by_length(words, min_len=MIN_LEN, max_len=SIZE)
    tries = 0
    while found < 8 and tries < MAX_TRIES:
        block_count = random.randint(MIN_BLOCKS, MAX_BLOCKS)
        half = block_count // 2
        picks = random.sample(positions, half)
        blocks = set(picks)
        for pos in picks:
            blocks.add(mirrored(pos))
        if block_count % 2 == 1:
            blocks.add(center)

        if valid_template(SIZE, SIZE, blocks, letters_by_len, words_by_length):
            name = f"auto_{SIZE}x{SIZE}_{found}"
            path = TEMPLATE_DIR / f"{name}.json"
            data = {"name": name, "width": SIZE, "height": SIZE, "blocks": list(blocks)}
            path.write_text(json.dumps(data, indent=2))
            found += 1
        tries += 1
    print(f"{SIZE}x{SIZE}: wrote {found} templates")


if __name__ == "__main__":
    main()
