from __future__ import annotations

import argparse
import csv
from datetime import date
import json
from pathlib import Path
import random
import re
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CSV_PATH = REPO_ROOT / "data" / "wordlist_crossword_answer_clue.csv"
TOKEN_RE = re.compile(r"[^A-Z0-9]")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run worksheet-style crossword generation from answer,clue CSV"
    )
    parser.add_argument("--date", type=str, default=date.today().isoformat())
    parser.add_argument("--timezone", type=str, default="UTC")
    parser.add_argument("--seed", type=int, default=20260212)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--show-grid", action="store_true")
    return parser.parse_args()


def _normalize_answer(answer: str) -> str:
    return TOKEN_RE.sub("", answer.upper())


def _load_lexicon() -> list[dict[str, str]]:
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"Missing CSV at {CSV_PATH}")
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    with CSV_PATH.open(newline="") as handle:
        reader = csv.reader(handle)
        for row in reader:
            if len(row) < 2:
                continue
            answer = _normalize_answer(row[0].strip())
            clue = row[1].strip()
            if not answer or not clue or len(answer) < 4 or len(answer) > 15:
                continue
            if answer in seen:
                continue
            rows.append({"answer": answer, "clue": clue})
            seen.add(answer)
    if not rows:
        raise RuntimeError("csv_lexicon_empty")
    return rows


def _letter_map(placed: list[dict[str, Any]]) -> dict[tuple[int, int], str]:
    out: dict[tuple[int, int], str] = {}
    for item in placed:
        answer = str(item["answer"])
        x = int(item["x"])
        y = int(item["y"])
        direction = str(item["direction"])
        dx, dy = (1, 0) if direction == "across" else (0, 1)
        for idx, ch in enumerate(answer):
            out[(x + idx * dx, y + idx * dy)] = ch
    return out


def _can_place(
    *,
    answer: str,
    x: int,
    y: int,
    direction: str,
    letters: dict[tuple[int, int], str],
) -> tuple[bool, int, int]:
    dx, dy = (1, 0) if direction == "across" else (0, 1)
    before = (x - dx, y - dy)
    after = (x + dx * len(answer), y + dy * len(answer))
    if before in letters or after in letters:
        return False, 0, 0

    perp_a = (-dy, dx)
    perp_b = (dy, -dx)
    intersections = 0
    new_cells = 0
    for idx, ch in enumerate(answer):
        cx = x + idx * dx
        cy = y + idx * dy
        existing = letters.get((cx, cy))
        if existing is not None:
            if existing != ch:
                return False, 0, 0
            intersections += 1
            continue
        if (cx + perp_a[0], cy + perp_a[1]) in letters:
            return False, 0, 0
        if (cx + perp_b[0], cy + perp_b[1]) in letters:
            return False, 0, 0
        new_cells += 1
    return True, intersections, new_cells


def _build_layout(
    lexicon: list[dict[str, str]],
    *,
    rng: random.Random,
    target_entries: int,
    min_entries: int,
    max_width: int,
    max_height: int,
) -> list[dict[str, Any]] | None:
    freq: dict[str, int] = {}
    for row in lexicon:
        for ch in set(str(row["answer"])):
            freq[ch] = freq.get(ch, 0) + 1

    pool = list(lexicon)
    rng.shuffle(pool)
    pool = pool[: min(320, len(pool))]
    starter = max(pool, key=lambda r: (sum(freq.get(ch, 0) for ch in set(str(r["answer"]))), len(str(r["answer"]))))
    placed: list[dict[str, Any]] = [{"answer": starter["answer"], "clue": starter["clue"], "x": 0, "y": 0, "direction": "across"}]
    used = {str(starter["answer"])}

    def in_bounds(candidate: list[dict[str, Any]]) -> bool:
        letters = _letter_map(candidate)
        xs = [x for x, _ in letters.keys()]
        ys = [y for _, y in letters.keys()]
        if not xs or not ys:
            return True
        return (max(xs) - min(xs) + 1) <= max_width and (max(ys) - min(ys) + 1) <= max_height

    words = sorted(pool, key=lambda row: (len(str(row["answer"])), rng.random()), reverse=True)
    for row in words:
        answer = str(row["answer"])
        if answer in used:
            continue
        letters = _letter_map(placed)
        candidates: list[tuple[float, dict[str, Any]]] = []
        for (cx, cy), cell_ch in letters.items():
            for idx, word_ch in enumerate(answer):
                if word_ch != cell_ch:
                    continue
                for direction in ("across", "down"):
                    dx, dy = (1, 0) if direction == "across" else (0, 1)
                    start_x = cx - idx * dx
                    start_y = cy - idx * dy
                    ok, intersections, new_cells = _can_place(
                        answer=answer,
                        x=start_x,
                        y=start_y,
                        direction=direction,
                        letters=letters,
                    )
                    if not ok or intersections <= 0:
                        continue
                    entry = {
                        "answer": answer,
                        "clue": row["clue"],
                        "x": start_x,
                        "y": start_y,
                        "direction": direction,
                    }
                    if not in_bounds(placed + [entry]):
                        continue
                    score = intersections * 8.0 - new_cells * 0.3 + rng.random() * 0.05
                    candidates.append((score, entry))
        if not candidates:
            continue
        candidates.sort(key=lambda item: item[0], reverse=True)
        placed.append(candidates[0][1])
        used.add(answer)
        if len(placed) >= target_entries:
            break

    if len(placed) < min_entries:
        return None
    return placed


def _build_payload(*, target_date: date, timezone: str, seed_value: int) -> dict[str, Any]:
    lexicon = _load_lexicon()
    rng = random.Random(seed_value)
    layout: list[dict[str, Any]] | None = None
    for _ in range(28):
        layout = _build_layout(
            lexicon,
            rng=rng,
            target_entries=rng.randint(16, 26),
            min_entries=12,
            max_width=23,
            max_height=21,
        )
        if layout is not None:
            break
    if layout is None:
        raise RuntimeError("layout_failed")

    letters = _letter_map(layout)
    min_x = min(x for x, _ in letters.keys())
    max_x = max(x for x, _ in letters.keys())
    min_y = min(y for _, y in letters.keys())
    max_y = max(y for _, y in letters.keys())
    width = max_x - min_x + 1
    height = max_y - min_y + 1
    shifted_letters = {(x - min_x, y - min_y): ch for (x, y), ch in letters.items()}

    shifted = [
        {
            "answer": row["answer"],
            "clue": row["clue"],
            "direction": row["direction"],
            "x": int(row["x"]) - min_x,
            "y": int(row["y"]) - min_y,
        }
        for row in layout
    ]

    starts = sorted({(row["x"], row["y"]) for row in shifted}, key=lambda c: (c[1], c[0]))
    number_by_start = {pos: idx for idx, pos in enumerate(starts, start=1)}
    entries: list[dict[str, Any]] = []
    for row in shifted:
        answer = str(row["answer"])
        direction = str(row["direction"])
        x = int(row["x"])
        y = int(row["y"])
        number = int(number_by_start[(x, y)])
        dx, dy = (1, 0) if direction == "across" else (0, 1)
        cells = [[x + i * dx, y + i * dy] for i in range(len(answer))]
        entries.append(
            {
                "id": ("a" if direction == "across" else "d") + str(number),
                "direction": direction,
                "number": number,
                "answer": answer,
                "clue": str(row["clue"]),
                "length": len(answer),
                "cells": cells,
                "sourceRef": f"csv://wordlist_crossword_answer_clue.csv#{answer}",
            }
        )
    entries.sort(key=lambda row: (int(row["number"]), 0 if row["direction"] == "across" else 1))

    across_map: dict[tuple[int, int], str] = {}
    down_map: dict[tuple[int, int], str] = {}
    for entry in entries:
        for cx, cy in entry["cells"]:
            key = (int(cx), int(cy))
            if entry["direction"] == "across":
                across_map[key] = str(entry["id"])
            else:
                down_map[key] = str(entry["id"])

    grid_cells = []
    for y in range(height):
        for x in range(width):
            letter = shifted_letters.get((x, y))
            if letter is None:
                grid_cells.append(
                    {
                        "x": x,
                        "y": y,
                        "isBlock": True,
                        "solution": None,
                        "entryIdAcross": None,
                        "entryIdDown": None,
                    }
                )
            else:
                grid_cells.append(
                    {
                        "x": x,
                        "y": y,
                        "isBlock": False,
                        "solution": letter,
                        "entryIdAcross": across_map.get((x, y)),
                        "entryIdDown": down_map.get((x, y)),
                    }
                )

    return {
        "id": f"dryrun_crossword_{target_date.strftime('%Y%m%d')}_{seed_value}",
        "date": target_date.isoformat(),
        "gameType": "crossword",
        "title": f"Crossword Reserve {target_date.isoformat()} · Worksheet",
        "publishedAt": None,
        "timezone": timezone,
        "grid": {"width": width, "height": height, "cells": grid_cells},
        "entries": entries,
        "metadata": {
            "difficulty": "medium",
            "themeTags": ["pokemon", "worksheet", "crossword"],
            "source": "curated",
            "generatorVersion": "dry-run",
        },
    }


def _render_ascii_grid(payload: dict[str, Any]) -> str:
    grid = payload["grid"]
    entries = payload["entries"]
    width = int(grid["width"])
    height = int(grid["height"])
    letters: dict[tuple[int, int], str] = {}
    for entry in entries:
        answer = str(entry["answer"])
        for idx, cell in enumerate(entry["cells"]):
            x, y = int(cell[0]), int(cell[1])
            if idx < len(answer):
                letters[(x, y)] = answer[idx]
    lines: list[str] = []
    for y in range(height):
        row: list[str] = []
        for x in range(width):
            row.append(letters.get((x, y), "#"))
        lines.append("".join(row))
    return "\n".join(lines)


def main() -> None:
    args = parse_args()
    target_date = date.fromisoformat(args.date)
    payload = _build_payload(target_date=target_date, timezone=args.timezone, seed_value=args.seed)
    entries = payload["entries"]
    across = sum(1 for entry in entries if entry["direction"] == "across")
    down = sum(1 for entry in entries if entry["direction"] == "down")

    print(f"id={payload['id']}")
    print(f"date={payload['date']}")
    print(f"title={payload['title']}")
    print(f"grid={payload['grid']['width']}x{payload['grid']['height']}")
    print(f"entries={len(entries)} across={across} down={down}")
    if entries:
        print(f"sample={entries[0]['id']} {entries[0]['answer']} :: {entries[0]['clue']}")
    if args.show_grid:
        print("")
        print(_render_ascii_grid(payload))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(payload, indent=2) + "\n")
        print(f"json_written={args.json_out}")


if __name__ == "__main__":
    main()
