from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import psycopg
from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed unpublished reserve puzzles")
    parser.add_argument("--game-type", choices=["crossword", "cryptic"], default="crossword")
    parser.add_argument("--count", type=int, default=10)
    parser.add_argument("--start-date", type=str, default=None, help="YYYY-MM-DD (defaults to tomorrow)")
    parser.add_argument("--title-prefix", type=str, default="Reserve Puzzle")
    parser.add_argument("--overwrite-dates", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def normalize_db_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def build_payload(game_type: str, puzzle_date: date, idx: int, timezone: str) -> dict:
    answer = "PIKACHU" if game_type == "crossword" else "EEVEE"
    clue = "Electric-type mascot" if game_type == "crossword" else "Adaptable fox-like Pokemon"
    puzzle_id = f"seed_{game_type}_{puzzle_date.strftime('%Y%m%d')}_{idx}_{uuid4().hex[:6]}"
    title = f"{game_type.title()} Reserve {puzzle_date.isoformat()}"
    grid = {
        "width": 15,
        "height": 15,
        "cells": [
            {"x": i, "y": 0, "isBlock": False, "solution": ch, "entryIdAcross": "a1", "entryIdDown": None}
            for i, ch in enumerate(answer)
        ],
    }
    entries = [
        {
            "id": "a1",
            "direction": "across",
            "number": 1,
            "answer": answer,
            "clue": clue,
            "length": len(answer),
            "cells": [[i, 0] for i in range(len(answer))],
            "sourceRef": "seed-script",
        }
    ]
    metadata = {
        "difficulty": "easy",
        "themeTags": ["reserve", game_type],
        "source": "curated",
        "generatorVersion": "seed-reserve-0.1",
    }
    return {
        "id": puzzle_id,
        "date": puzzle_date,
        "game_type": game_type,
        "title": title,
        "published_at": None,
        "timezone": timezone,
        "grid": json.dumps(grid),
        "entries": json.dumps(entries),
        "metadata": json.dumps(metadata),
    }


def resolve_start_date(value: str | None, timezone: str) -> date:
    if value:
        return date.fromisoformat(value)
    tz = ZoneInfo(timezone)
    return datetime.now(tz).date() + timedelta(days=1)


def main() -> None:
    load_dotenv()
    args = parse_args()

    db_url = normalize_db_url(os.getenv("DATABASE_URL", ""))
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    timezone = os.getenv("TIMEZONE", "Europe/London")
    start_date = resolve_start_date(args.start_date, timezone)

    inserted = 0
    skipped = 0
    deleted = 0

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for i in range(args.count):
                target_date = start_date + timedelta(days=i)
                cur.execute(
                    "SELECT "
                    "COUNT(*) FILTER (WHERE published_at IS NULL) AS unpublished_count, "
                    "COUNT(*) FILTER (WHERE published_at IS NOT NULL) AS published_count "
                    "FROM puzzles WHERE game_type = %(game_type)s AND date = %(date)s",
                    {"game_type": args.game_type, "date": target_date},
                )
                row = cur.fetchone()
                unpublished_count = int(row[0])
                published_count = int(row[1])

                if published_count > 0:
                    print(f"skip {target_date}: published puzzle already exists")
                    skipped += 1
                    continue

                if unpublished_count > 0 and not args.overwrite_dates:
                    print(f"skip {target_date}: reserve puzzle already exists (use --overwrite-dates)")
                    skipped += 1
                    continue

                if unpublished_count > 0 and args.overwrite_dates:
                    if args.dry_run:
                        print(f"dry-run delete {target_date}: {unpublished_count} existing reserve puzzle(s)")
                    else:
                        cur.execute(
                            "DELETE FROM puzzles "
                            "WHERE game_type = %(game_type)s AND date = %(date)s AND published_at IS NULL",
                            {"game_type": args.game_type, "date": target_date},
                        )
                    deleted += unpublished_count

                payload = build_payload(args.game_type, target_date, i, timezone)
                payload["title"] = f"{args.title_prefix} {target_date.isoformat()}"
                if args.dry_run:
                    print(f"dry-run insert {target_date}: id={payload['id']}")
                    inserted += 1
                    continue

                cur.execute(
                    "INSERT INTO puzzles "
                    "(id, date, game_type, title, published_at, timezone, grid, entries, metadata) "
                    "VALUES ("
                    "%(id)s, %(date)s, %(game_type)s, %(title)s, %(published_at)s, %(timezone)s, "
                    "%(grid)s::json, %(entries)s::json, %(metadata)s::json"
                    ")",
                    payload,
                )
                inserted += 1

        if args.dry_run:
            conn.rollback()
        else:
            conn.commit()

    print(
        f"done: inserted={inserted} skipped={skipped} "
        f"deleted={deleted} dry_run={args.dry_run}"
    )


if __name__ == "__main__":
    main()
