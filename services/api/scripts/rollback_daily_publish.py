from __future__ import annotations

import argparse
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

from app.core import cache, config, db
from app.data import repo


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rollback published daily puzzle to a known-good previous puzzle")
    parser.add_argument("--game-type", choices=["crossword", "cryptic"], required=True)
    parser.add_argument("--date", help="Target daily date in YYYY-MM-DD. Defaults to today in configured timezone.")
    parser.add_argument("--source-date", help="Optional source published date to clone from.")
    parser.add_argument("--reason", default="manual rollback via script")
    parser.add_argument("--executed-by", default="ops-cli")
    return parser.parse_args()


def main() -> int:
    load_dotenv()
    args = _parse_args()

    target_date = args.date
    if not target_date:
        target_date = datetime.now(ZoneInfo(config.TIMEZONE)).date().isoformat()

    db.init_db()
    cache.init_cache()
    try:
        result = repo.rollback_daily_publish(
            date_value=target_date,
            game_type=args.game_type,
            timezone=config.TIMEZONE,
            source_date=args.source_date,
            reason=args.reason,
            executed_by=args.executed_by,
        )
        print(json.dumps(result, indent=2, ensure_ascii=True))
        return 0
    finally:
        cache.close_cache()
        db.close_db()


if __name__ == "__main__":
    raise SystemExit(main())

