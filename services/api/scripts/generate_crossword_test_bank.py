#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import types
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a local bank of crossword puzzle JSON files for testing.")
    parser.add_argument("--count", type=int, default=20, help="Number of consecutive crossword puzzles to generate.")
    parser.add_argument("--start-date", type=str, default="", help="Start date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--timezone", type=str, default="Europe/London", help="Puzzle timezone.")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="",
        help="Directory for emitted JSON files. Defaults to output/crossword-test-bank/<run>.",
    )
    parser.add_argument(
        "--strict-quality",
        action="store_true",
        help="Fail individual dates instead of allowing best-effort fallback payloads.",
    )
    return parser.parse_args()


def _install_optional_dependency_stubs() -> None:
    if importlib.util.find_spec("redis") is None and "redis" not in sys.modules:
        redis_module = types.ModuleType("redis")

        class _RedisStub:
            @classmethod
            def from_url(cls, *args: Any, **kwargs: Any) -> "_RedisStub":
                return cls()

            def ping(self) -> bool:
                return True

            def close(self) -> None:
                return None

        redis_module.Redis = _RedisStub
        sys.modules["redis"] = redis_module

    if importlib.util.find_spec("psycopg_pool") is None and "psycopg_pool" not in sys.modules:
        psycopg_pool_module = types.ModuleType("psycopg_pool")

        class _ConnectionPoolStub:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                self._closed = True

            def open(self) -> None:
                self._closed = False

            def close(self) -> None:
                self._closed = True

            @property
            def closed(self) -> bool:
                return self._closed

        psycopg_pool_module.ConnectionPool = _ConnectionPoolStub
        sys.modules["psycopg_pool"] = psycopg_pool_module


def _resolve_start_date(raw_value: str, timezone_name: str) -> date_type:
    if raw_value.strip():
        return date_type.fromisoformat(raw_value.strip())
    return datetime.now(ZoneInfo(timezone_name)).date()


def _default_output_dir(start_date: date_type, count: int, timezone_name: str) -> Path:
    stamp = datetime.now(ZoneInfo(timezone_name)).strftime("%Y%m%d-%H%M%S")
    return REPO_ROOT / "output" / "crossword-test-bank" / f"{start_date.isoformat()}-{count}-{stamp}"


def _materialize_payload(
    *,
    payload: dict[str, Any],
    quality_report: dict[str, Any],
    quality_bypassed: bool,
    attempts_used: int,
) -> dict[str, Any]:
    return {
        "id": str(payload["id"]),
        "date": payload["date"].isoformat(),
        "gameType": "crossword",
        "title": str(payload["title"]),
        "timezone": str(payload["timezone"]),
        "grid": json.loads(str(payload["grid"])),
        "entries": json.loads(str(payload["entries"])),
        "metadata": json.loads(str(payload["metadata"])),
        "qualityReport": quality_report,
        "qualityBypassed": bool(quality_bypassed),
        "qualityAttemptsUsed": int(attempts_used),
    }


def main() -> int:
    args = _parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be positive")

    _install_optional_dependency_stubs()

    if str(API_ROOT) not in sys.path:
        sys.path.insert(0, str(API_ROOT))

    from app.services.reserve_generator import (  # noqa: WPS433
        QualityGateError,
        _build_governed_crossword_puzzle_payload,
        _load_crossword_csv_lexicon,
    )

    start_date = _resolve_start_date(args.start_date, args.timezone)
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else _default_output_dir(
        start_date,
        args.count,
        args.timezone,
    )
    output_dir.mkdir(parents=True, exist_ok=True)

    lexicon = _load_crossword_csv_lexicon()
    manifest: dict[str, Any] = {
        "generatedAt": datetime.now(ZoneInfo(args.timezone)).isoformat(),
        "startDate": start_date.isoformat(),
        "countRequested": int(args.count),
        "timezone": args.timezone,
        "strictQuality": bool(args.strict_quality),
        "lexiconAnswers": len(lexicon),
        "outputDir": str(output_dir),
        "puzzles": [],
        "failures": [],
    }

    for offset in range(args.count):
        target_date = start_date + timedelta(days=offset)
        seed_value = int(target_date.strftime("%Y%m%d"))
        try:
            payload, quality_report, quality_bypassed, attempts_used = _build_governed_crossword_puzzle_payload(
                target_date=target_date,
                timezone=args.timezone,
                lexicon=lexicon,
                seed_value=seed_value,
                allow_fallback=not args.strict_quality,
            )
        except QualityGateError as exc:
            manifest["failures"].append(
                {
                    "date": target_date.isoformat(),
                    "code": exc.code,
                    "message": exc.message,
                    "attemptsUsed": exc.attempts_used,
                    "qualityReport": exc.quality_report,
                }
            )
            continue

        materialized = _materialize_payload(
            payload=payload,
            quality_report=quality_report,
            quality_bypassed=quality_bypassed,
            attempts_used=attempts_used,
        )
        puzzle_path = output_dir / f"{target_date.isoformat()}.json"
        puzzle_path.write_text(json.dumps(materialized, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")
        manifest["puzzles"].append(
            {
                "date": target_date.isoformat(),
                "id": materialized["id"],
                "title": materialized["title"],
                "entries": len(materialized["entries"]),
                "qualityScore": quality_report.get("score"),
                "isPublishable": bool(quality_report.get("isPublishable", False)),
                "qualityBypassed": bool(quality_bypassed),
                "qualityAttemptsUsed": int(attempts_used),
                "file": str(puzzle_path),
            }
        )

    manifest["countGenerated"] = len(manifest["puzzles"])
    manifest["countFailed"] = len(manifest["failures"])
    manifest["countPublishable"] = sum(1 for row in manifest["puzzles"] if row.get("isPublishable"))
    manifest["countBypassed"] = sum(1 for row in manifest["puzzles"] if row.get("qualityBypassed"))

    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=True, indent=2, sort_keys=True), encoding="utf-8")

    print(f"output_dir={output_dir}")
    print(f"manifest={manifest_path}")
    print(f"generated={manifest['countGenerated']}")
    print(f"publishable={manifest['countPublishable']}")
    print(f"bypassed={manifest['countBypassed']}")
    print(f"failed={manifest['countFailed']}")
    return 0 if manifest["countGenerated"] > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
