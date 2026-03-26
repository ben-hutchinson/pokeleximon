from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from uuid import uuid4

import psycopg
from dotenv import load_dotenv


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed deterministic published puzzles for Playwright live e2e tests")
    parser.add_argument("--date", default="2099-01-01", help="YYYY-MM-DD target publish date")
    parser.add_argument("--overwrite", action="store_true", help="Replace any existing puzzles for the target date/game type")
    return parser.parse_args()


def normalize_db_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def build_crossword_payload(target_date: date, tz_name: str) -> dict[str, object]:
    puzzle_id = f"e2e_crossword_{target_date.strftime('%Y%m%d')}_{uuid4().hex[:8]}"
    return {
        "id": puzzle_id,
        "date": target_date,
        "game_type": "crossword",
        "title": f"Smoke Test Crossword {target_date.isoformat()}",
        "published_at": datetime.now(timezone.utc),
        "timezone": tz_name,
        "grid": json.dumps(
            {
                "width": 3,
                "height": 3,
                "cells": [
                    {"x": 0, "y": 0, "isBlock": False, "solution": "C", "entryIdAcross": "a1", "entryIdDown": "d1"},
                    {"x": 1, "y": 0, "isBlock": False, "solution": "A", "entryIdAcross": "a1", "entryIdDown": "d2"},
                    {"x": 2, "y": 0, "isBlock": False, "solution": "T", "entryIdAcross": "a1", "entryIdDown": "d3"},
                    {"x": 0, "y": 1, "isBlock": False, "solution": "A", "entryIdAcross": "a4", "entryIdDown": "d1"},
                    {"x": 1, "y": 1, "isBlock": False, "solution": "P", "entryIdAcross": "a4", "entryIdDown": "d2"},
                    {"x": 2, "y": 1, "isBlock": False, "solution": "E", "entryIdAcross": "a4", "entryIdDown": "d3"},
                    {"x": 0, "y": 2, "isBlock": False, "solution": "T", "entryIdAcross": "a7", "entryIdDown": "d1"},
                    {"x": 1, "y": 2, "isBlock": False, "solution": "E", "entryIdAcross": "a7", "entryIdDown": "d2"},
                    {"x": 2, "y": 2, "isBlock": False, "solution": "N", "entryIdAcross": "a7", "entryIdDown": "d3"},
                ],
            }
        ),
        "entries": json.dumps(
            [
                {"id": "a1", "direction": "across", "number": 1, "answer": "CAT", "clue": "Starter pet", "length": 3, "cells": [[0, 0], [1, 0], [2, 0]]},
                {"id": "a4", "direction": "across", "number": 4, "answer": "APE", "clue": "Primate", "length": 3, "cells": [[0, 1], [1, 1], [2, 1]]},
                {"id": "a7", "direction": "across", "number": 7, "answer": "TEN", "clue": "Double five", "length": 3, "cells": [[0, 2], [1, 2], [2, 2]]},
                {"id": "d1", "direction": "down", "number": 1, "answer": "CAT", "clue": "Feline", "length": 3, "cells": [[0, 0], [0, 1], [0, 2]]},
                {"id": "d2", "direction": "down", "number": 2, "answer": "APE", "clue": "Climbing primate", "length": 3, "cells": [[1, 0], [1, 1], [1, 2]]},
                {"id": "d3", "direction": "down", "number": 3, "answer": "TEN", "clue": "Two hands, fingers-wise", "length": 3, "cells": [[2, 0], [2, 1], [2, 2]]},
            ]
        ),
        "metadata": json.dumps(
            {
                "difficulty": "easy",
                "themeTags": ["pokemon", "e2e"],
                "source": "curated",
                "generatorVersion": "playwright-e2e-1",
                "constructor": "Smoke Suite",
                "editor": "QA",
                "notes": "Deterministic published crossword for Playwright live tests.",
            }
        ),
    }


def build_cryptic_payload(target_date: date, tz_name: str) -> dict[str, object]:
    puzzle_id = f"e2e_cryptic_{target_date.strftime('%Y%m%d')}_{uuid4().hex[:8]}"
    return {
        "id": puzzle_id,
        "date": target_date,
        "game_type": "cryptic",
        "title": f"Smoke Test Cryptic {target_date.isoformat()}",
        "published_at": datetime.now(timezone.utc),
        "timezone": tz_name,
        "grid": json.dumps(
            {
                "width": 4,
                "height": 1,
                "cells": [
                    {"x": 0, "y": 0, "isBlock": False, "solution": "M", "entryIdAcross": "c1", "entryIdDown": None},
                    {"x": 1, "y": 0, "isBlock": False, "solution": "E", "entryIdAcross": "c1", "entryIdDown": None},
                    {"x": 2, "y": 0, "isBlock": False, "solution": "W", "entryIdAcross": "c1", "entryIdDown": None},
                    {"x": 3, "y": 0, "isBlock": False, "solution": None, "entryIdAcross": None, "entryIdDown": None},
                ],
            }
        ),
        "entries": json.dumps(
            [
                {
                    "id": "c1",
                    "direction": "across",
                    "number": 1,
                    "answer": "MEW",
                    "clue": "Legendary psychic Pokemon we remodeled",
                    "length": 3,
                    "enumeration": "3",
                    "cells": [[0, 0], [1, 0], [2, 0]],
                    "mechanism": "anagram",
                    "wordplayMetadata": {
                        "definition": "Legendary psychic Pokemon",
                        "indicator": "remodeled",
                        "fodder": ["WE"],
                    },
                }
            ]
        ),
        "metadata": json.dumps(
            {
                "difficulty": "medium",
                "themeTags": ["pokemon", "cryptic", "e2e"],
                "source": "curated",
                "generatorVersion": "playwright-e2e-1",
                "byline": "Codex",
                "constructor": "Smoke Suite",
                "editor": "QA",
                "notes": "Deterministic published cryptic for Playwright live tests.",
            }
        ),
    }


def build_connections_payload(target_date: date, tz_name: str) -> dict[str, object]:
    puzzle_id = f"e2e_connections_{target_date.strftime('%Y%m%d')}_{uuid4().hex[:8]}"
    return {
        "id": puzzle_id,
        "date": target_date,
        "game_type": "connections",
        "title": f"Connections {target_date.isoformat()}",
        "published_at": datetime.now(timezone.utc),
        "timezone": tz_name,
        "grid": json.dumps(
            {
                "width": 4,
                "height": 4,
                "cells": [
                    {"x": index % 4, "y": index // 4, "isBlock": False, "solution": None, "entryIdAcross": None, "entryIdDown": None}
                    for index in range(16)
                ],
            }
        ),
        "entries": json.dumps([]),
        "metadata": json.dumps(
            {
                "difficulty": "easy",
                "themeTags": ["pokemon", "connections", "e2e"],
                "source": "curated",
                "generatorVersion": "playwright-e2e-1",
                "connections": {
                    "version": 1,
                    "difficultyOrder": ["yellow", "green", "blue", "purple"],
                    "groups": [
                        {"id": "yellow", "title": "Starter Pokemon", "difficulty": "yellow", "labels": ["Bulbasaur", "Charmander", "Squirtle", "Pikachu"]},
                        {"id": "green", "title": "Eeveelutions", "difficulty": "green", "labels": ["Vaporeon", "Jolteon", "Flareon", "Umbreon"]},
                        {"id": "blue", "title": "Ghost Types", "difficulty": "blue", "labels": ["Gastly", "Haunter", "Gengar", "Misdreavus"]},
                        {"id": "purple", "title": "Legendary Birds", "difficulty": "purple", "labels": ["Articuno", "Zapdos", "Moltres", "Lugia"]},
                    ],
                    "tiles": [
                        {"id": "t1", "label": "Bulbasaur", "groupId": "yellow"},
                        {"id": "t2", "label": "Charmander", "groupId": "yellow"},
                        {"id": "t3", "label": "Squirtle", "groupId": "yellow"},
                        {"id": "t4", "label": "Pikachu", "groupId": "yellow"},
                        {"id": "t5", "label": "Vaporeon", "groupId": "green"},
                        {"id": "t6", "label": "Jolteon", "groupId": "green"},
                        {"id": "t7", "label": "Flareon", "groupId": "green"},
                        {"id": "t8", "label": "Umbreon", "groupId": "green"},
                        {"id": "t9", "label": "Gastly", "groupId": "blue"},
                        {"id": "t10", "label": "Haunter", "groupId": "blue"},
                        {"id": "t11", "label": "Gengar", "groupId": "blue"},
                        {"id": "t12", "label": "Misdreavus", "groupId": "blue"},
                        {"id": "t13", "label": "Articuno", "groupId": "purple"},
                        {"id": "t14", "label": "Zapdos", "groupId": "purple"},
                        {"id": "t15", "label": "Moltres", "groupId": "purple"},
                        {"id": "t16", "label": "Lugia", "groupId": "purple"},
                    ],
                },
            }
        ),
    }


def seed_puzzle(cur: psycopg.Cursor, payload: dict[str, object], overwrite: bool) -> str:
    game_type = str(payload["game_type"])
    target_date = payload["date"]

    cur.execute(
        "SELECT id FROM puzzles WHERE game_type = %(game_type)s AND date = %(date)s",
        {"game_type": game_type, "date": target_date},
    )
    existing = cur.fetchone()
    if existing and not overwrite:
        return f"skip {game_type} {target_date}: existing puzzle present"

    if existing and overwrite:
        cur.execute(
            "DELETE FROM puzzles WHERE game_type = %(game_type)s AND date = %(date)s",
            {"game_type": game_type, "date": target_date},
        )

    cur.execute(
        "INSERT INTO puzzles (id, date, game_type, title, published_at, timezone, grid, entries, metadata) "
        "VALUES (%(id)s, %(date)s, %(game_type)s, %(title)s, %(published_at)s, %(timezone)s, %(grid)s::json, %(entries)s::json, %(metadata)s::json)",
        payload,
    )
    return f"insert {game_type} {target_date}: id={payload['id']}"


def seed_public_profile(cur: psycopg.Cursor) -> str:
    cur.execute(
        "INSERT INTO player_profiles (player_token, display_name, public_slug, leaderboard_visible) "
        "VALUES (%(player_token)s, %(display_name)s, %(public_slug)s, true) "
        "ON CONFLICT (player_token) DO UPDATE SET "
        "display_name = EXCLUDED.display_name, "
        "public_slug = EXCLUDED.public_slug, "
        "leaderboard_visible = EXCLUDED.leaderboard_visible",
        {
            "player_token": "e2e_ash_token",
            "display_name": "Ash",
            "public_slug": "ash-ketchum",
        },
    )
    return "upsert player profile: ash-ketchum"


def seed_leaderboard_submission(cur: psycopg.Cursor, *, puzzle_id: str, game_type: str, target_date: date, solve_time_ms: int) -> str:
    cur.execute(
        "INSERT INTO leaderboard_submissions ("
        "player_token, game_type, puzzle_id, puzzle_date, completed, solve_time_ms, used_assists, used_reveals, session_id"
        ") VALUES ("
        "%(player_token)s, %(game_type)s, %(puzzle_id)s, %(puzzle_date)s, true, %(solve_time_ms)s, false, false, %(session_id)s"
        ") ON CONFLICT (player_token, puzzle_id) DO UPDATE SET "
        "completed = EXCLUDED.completed, "
        "solve_time_ms = EXCLUDED.solve_time_ms, "
        "used_assists = EXCLUDED.used_assists, "
        "used_reveals = EXCLUDED.used_reveals, "
        "session_id = EXCLUDED.session_id, "
        "updated_at = NOW()",
        {
            "player_token": "e2e_ash_token",
            "game_type": game_type,
            "puzzle_id": puzzle_id,
            "puzzle_date": target_date,
            "solve_time_ms": solve_time_ms,
            "session_id": f"seed_{game_type}_session",
        },
    )
    return f"upsert leaderboard submission: {game_type} {target_date}"


def main() -> None:
    load_dotenv()
    args = parse_args()
    db_url = normalize_db_url(os.getenv("DATABASE_URL", ""))
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")

    tz_name = os.getenv("TIMEZONE", "Europe/London")
    target_date = date.fromisoformat(args.date)

    payloads = [
        build_crossword_payload(target_date, tz_name),
        build_cryptic_payload(target_date, tz_name),
        build_connections_payload(target_date, tz_name),
    ]

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            inserted_ids: dict[str, str] = {}
            for payload in payloads:
                print(seed_puzzle(cur, payload, overwrite=args.overwrite))
                inserted_ids[str(payload["game_type"])] = str(payload["id"])
            print(seed_public_profile(cur))
            print(
                seed_leaderboard_submission(
                    cur, puzzle_id=inserted_ids["crossword"], game_type="crossword", target_date=target_date, solve_time_ms=54000
                )
            )
            print(
                seed_leaderboard_submission(
                    cur, puzzle_id=inserted_ids["cryptic"], game_type="cryptic", target_date=target_date, solve_time_ms=61000
                )
            )
            print(
                seed_leaderboard_submission(
                    cur, puzzle_id=inserted_ids["connections"], game_type="connections", target_date=target_date, solve_time_ms=45000
                )
            )
        conn.commit()


if __name__ == "__main__":
    main()
