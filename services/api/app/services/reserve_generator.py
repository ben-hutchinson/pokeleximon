from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import re
from datetime import date as date_type
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4
from zoneinfo import ZoneInfo

try:
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # pragma: no cover - allows local dry-run tooling without DB deps
    dict_row = None

from app.core.cache import get_cache
from app.core.db import get_db
from app.services.alerting import notify_external_alert
from app.services.artifact_store import write_json_artifact
from app.services.puzzle_quality import evaluate_crossword_publishability


GENERATOR_VERSION = "reserve-generator-0.3"
ANSWER_RE = re.compile(r"[^A-Z]")
ANSWER_PART_RE = re.compile(r"[A-Z0-9]+")
QUALITY_RETRY_SEED_DELTA = 9973
MAX_CROSSWORD_QUALITY_ATTEMPTS = 8
DISALLOWED_CLUE_PATTERNS = (
    re.compile(r"(?i)\bpok[eé]api\b"),
    re.compile(r"(?i)\bjapanese\b"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\b(clue|record)\s+token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bfallback clue\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\b(todo|tbd|lorem ipsum)\b"),
    re.compile(r"\*{3,}"),
    re.compile(r"(?i)\bpok[eé]mon term from the csv lexicon\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
    re.compile(r"(?i)^location:\s*region\b"),
    re.compile(r"(?i)\b(type|ability|location) entry\b"),
    re.compile(r"(?i)^core[- ]series pok[eé]mon .*answer uses \d+ word"),
    re.compile(r"(?i)^pok[eé]mon .* clue with initials [A-Z]+ and \d+ total letters"),
    re.compile(r"(?i)^pok[eé]mon .* clue: ending letters"),
    re.compile(r"(?i)^pok[eé]mon .* entry with enumeration"),
    re.compile(r"(?i)\bvowels\s+\d+\s*,\s*consonants\s+\d+\b"),
    re.compile(r"(?i)\b\d+\s+total letters\b"),
    re.compile(r"(?i)\bwith \d+ words? and \d+ letters\b"),
    re.compile(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]"),
)
CLUE_COLUMN_RE = re.compile(r"^clue\s*(\d+)$")


class QualityGateError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        quality_report: dict[str, Any] | None = None,
        attempts_used: int | None = None,
    ):
        super().__init__(code)
        self.code = code
        self.message = message
        self.quality_report = quality_report or {}
        self.attempts_used = attempts_used

    def to_detail(self) -> dict[str, Any]:
        detail: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
        }
        if self.attempts_used is not None:
            detail["attemptsUsed"] = int(self.attempts_used)
        if self.quality_report:
            detail["qualityReport"] = {
                "isPublishable": bool(self.quality_report.get("isPublishable", False)),
                "score": self.quality_report.get("score"),
                "hardFailures": list(self.quality_report.get("hardFailures", [])),
                "warnings": list(self.quality_report.get("warnings", [])),
            }
        return detail


def _resolve_crossword_csv_path() -> Path:
    override = os.getenv("CROSSWORD_CSV_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / "wordlist_crossword_answer_clue.csv"
        if candidate.exists():
            return candidate
    # Default for container/local dev; existence is validated by loader.
    return Path("/app/data/wordlist_crossword_answer_clue.csv")


CROSSWORD_CSV_PATH = _resolve_crossword_csv_path()


def _resolve_cryptic_lexicon_path() -> Path:
    override = os.getenv("CRYPTIC_CLUES_PATH") or os.getenv("CRYPTIC_CSV_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        json_candidate = parent / "cryptic_clues.json"
        if json_candidate.exists():
            return json_candidate
        csv_candidate = parent / "data" / "wordlist_cryptic_answer_clue.csv"
        if csv_candidate.exists():
            return csv_candidate
    bundled_json = Path("/app/cryptic_clues.json")
    if bundled_json.exists():
        return bundled_json
    return Path("/app/data/wordlist_cryptic_answer_clue.csv")


# Historical name kept for compatibility with existing tests and local overrides.
CRYPTIC_CSV_PATH = _resolve_cryptic_lexicon_path()
CONNECTIONS_DIFFICULTY_ORDER = ["yellow", "green", "blue", "purple"]
CONNECTIONS_LABEL_RE = re.compile(r"[^A-Z0-9 ]")
CONNECTIONS_WHITESPACE_RE = re.compile(r"\s+")
CONNECTIONS_BANNED_PATTERNS = (
    re.compile(r"(?i)\btoken\b"),
    re.compile(r"(?i)\bplaceholder\b"),
    re.compile(r"(?i)\btodo\b"),
    re.compile(r"\*{2,}"),
)


def _resolve_data_path(env_key: str, filename: str) -> Path:
    override = os.getenv(env_key)
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "data" / filename
        if candidate.exists():
            return candidate
    return Path("/app/data") / filename


CONNECTIONS_RULES_PATH = _resolve_data_path("CONNECTIONS_RULES_PATH", "connections_group_rules.json")
CONNECTIONS_OVERRIDES_PATH = _resolve_data_path("CONNECTIONS_OVERRIDES_PATH", "connections_daily_overrides.json")
CONNECTIONS_QUALITY_REPORT_PATH = _resolve_data_path("CONNECTIONS_QUALITY_REPORT_PATH", "connections_quality_report.json")
ANSWER_CORPUS_PATH = _resolve_data_path("ANSWER_CORPUS_PATH", "pokeapi_answer_corpus.json")


def _normalize_connections_label(value: str) -> str:
    text = str(value or "").strip().upper().replace("-", " ")
    text = CONNECTIONS_LABEL_RE.sub(" ", text)
    text = CONNECTIONS_WHITESPACE_RE.sub(" ", text).strip()
    return text


def _is_connections_label_allowed(label: str) -> bool:
    if not label or len(label) < 3 or len(label) > 20:
        return False
    return not any(pattern.search(label) for pattern in CONNECTIONS_BANNED_PATTERNS)


def _load_json_file(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _load_connections_rules() -> list[dict[str, Any]]:
    loaded = _load_json_file(CONNECTIONS_RULES_PATH)
    default_rules = [
        {"id": "species", "title": "Pokemon species", "sourceType": "pokemon-species", "minLength": 4, "maxLength": 14},
        {"id": "moves", "title": "Pokemon moves", "sourceType": "move", "minLength": 4, "maxLength": 14},
        {"id": "abilities", "title": "Pokemon abilities", "sourceType": "ability", "minLength": 4, "maxLength": 14},
        {"id": "items", "title": "Pokemon items", "sourceType": "item", "minLength": 4, "maxLength": 14},
        {"id": "locations", "title": "Pokemon locations", "sourceType": "location", "minLength": 4, "maxLength": 14},
        {"id": "types", "title": "Pokemon types", "sourceType": "type", "minLength": 4, "maxLength": 14},
    ]
    raw_rules = []
    if isinstance(loaded, dict) and isinstance(loaded.get("rules"), list):
        raw_rules = loaded["rules"]
    elif isinstance(loaded, list):
        raw_rules = loaded
    else:
        raw_rules = default_rules

    out: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for row in raw_rules:
        if not isinstance(row, dict):
            continue
        rule_id = str(row.get("id", "")).strip().lower()
        source_type = str(row.get("sourceType", "")).strip().lower()
        title = str(row.get("title", "")).strip() or source_type.title()
        labels = row.get("labels")
        has_explicit_labels = isinstance(labels, list) and len(labels) >= 4
        if not rule_id or rule_id in seen_ids:
            continue
        if not source_type and not has_explicit_labels:
            continue
        seen_ids.add(rule_id)
        out.append(
            {
                "id": rule_id,
                "title": title,
                "sourceType": source_type,
                "labels": labels if has_explicit_labels else None,
                "minLength": max(3, int(row.get("minLength", 4) or 4)),
                "maxLength": min(24, max(4, int(row.get("maxLength", 14) or 14))),
            }
        )
    return out if len(out) >= 4 else default_rules


def _load_connections_overrides() -> dict[str, Any]:
    loaded = _load_json_file(CONNECTIONS_OVERRIDES_PATH)
    if isinstance(loaded, dict):
        return loaded
    return {}


def _load_answer_corpus_rows() -> list[dict[str, Any]]:
    loaded = _load_json_file(ANSWER_CORPUS_PATH)
    if isinstance(loaded, list):
        return [row for row in loaded if isinstance(row, dict)]
    return []


def _build_connections_pool_by_rule(
    rules: list[dict[str, Any]],
    corpus_rows: list[dict[str, Any]],
) -> dict[str, list[str]]:
    pools: dict[str, set[str]] = {str(rule["id"]): set() for rule in rules}
    rule_by_source: dict[str, list[dict[str, Any]]] = {}
    for rule in rules:
        source_type = str(rule.get("sourceType") or "").strip().lower()
        if source_type:
            rule_by_source.setdefault(source_type, []).append(rule)

    for row in corpus_rows:
        source_type = str(row.get("sourceType", "")).strip().lower()
        display = row.get("answerDisplay") or row.get("answerKey") or ""
        normalized = _normalize_connections_label(str(display))
        if not normalized or not _is_connections_label_allowed(normalized):
            continue
        for rule in rule_by_source.get(source_type, []):
            min_len = int(rule.get("minLength", 4))
            max_len = int(rule.get("maxLength", 14))
            if len(normalized) < min_len or len(normalized) > max_len:
                continue
            pools[str(rule["id"])].add(normalized)

    for rule in rules:
        explicit_labels = rule.get("labels")
        if not isinstance(explicit_labels, list):
            continue
        bucket = pools.setdefault(str(rule["id"]), set())
        min_len = int(rule.get("minLength", 4))
        max_len = int(rule.get("maxLength", 14))
        for label in explicit_labels:
            normalized = _normalize_connections_label(str(label))
            if not normalized or not _is_connections_label_allowed(normalized):
                continue
            if len(normalized) < min_len or len(normalized) > max_len:
                continue
            bucket.add(normalized)

    return {key: sorted(values) for key, values in pools.items()}


def _connections_quality_report(
    *,
    groups: list[dict[str, Any]],
    candidate_sets: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    hard_failures: list[str] = []
    warnings: list[str] = []
    labels: list[str] = []

    if len(groups) != 4:
        hard_failures.append("group_count_not_four")
    for group in groups:
        group_labels = group.get("labels")
        if not isinstance(group_labels, list) or len(group_labels) != 4:
            hard_failures.append("group_label_count_not_four")
            continue
        for label in group_labels:
            normalized = _normalize_connections_label(str(label))
            if not _is_connections_label_allowed(normalized):
                hard_failures.append("label_contains_disallowed_content")
            labels.append(normalized)

    if len(labels) != 16:
        hard_failures.append("total_label_count_not_sixteen")

    unique_labels = set(labels)
    if len(unique_labels) != len(labels):
        hard_failures.append("duplicate_labels_present")

    if candidate_sets:
        for label in unique_labels:
            membership_count = sum(1 for values in candidate_sets.values() if label in values)
            if membership_count != 1:
                hard_failures.append("label_matches_multiple_groups")
                break

    initials = {label[0] for label in unique_labels if label}
    if len(initials) <= 6:
        warnings.append("low_initial_letter_variety")
    lengths = [len(label) for label in unique_labels]
    avg_len = (sum(lengths) / len(lengths)) if lengths else 0.0
    if avg_len < 5.0:
        warnings.append("labels_short_on_average")

    overlap_penalty = 0.0
    token_sets = [set(str(label).split(" ")) for label in unique_labels]
    for idx in range(len(token_sets)):
        for jdx in range(idx + 1, len(token_sets)):
            if token_sets[idx].intersection(token_sets[jdx]):
                overlap_penalty += 0.08

    score = max(0.0, min(100.0, 65.0 + (len(initials) * 2.4) + (avg_len * 1.5) - overlap_penalty))
    return {
        "isPublishable": len(hard_failures) == 0,
        "score": round(score, 2),
        "hardFailures": sorted(set(hard_failures)),
        "warnings": sorted(set(warnings)),
    }


def _append_connections_quality_report(entry: dict[str, Any]) -> None:
    base = {
        "updatedAt": datetime.now(ZoneInfo("UTC")).isoformat(),
        "total": 0,
        "unresolvedCount": 0,
        "items": [],
    }
    loaded = _load_json_file(CONNECTIONS_QUALITY_REPORT_PATH)
    if isinstance(loaded, dict):
        base.update(
            {
                "total": int(loaded.get("total", 0) or 0),
                "unresolvedCount": int(loaded.get("unresolvedCount", 0) or 0),
                "items": loaded.get("items", []) if isinstance(loaded.get("items"), list) else [],
            }
        )

    items = [entry, *base["items"]][:200]
    unresolved_count = sum(1 for row in items if isinstance(row, dict) and not bool(row.get("isPublishable", False)))
    payload = {
        "updatedAt": datetime.now(ZoneInfo("UTC")).isoformat(),
        "total": int(base["total"]) + 1,
        "unresolvedCount": unresolved_count,
        "items": items,
    }

    try:
        CONNECTIONS_QUALITY_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        CONNECTIONS_QUALITY_REPORT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _build_connections_payload_from_groups(
    *,
    target_date: date_type,
    timezone: str,
    groups: list[dict[str, Any]],
    rng: random.Random,
    title: str | None = None,
) -> dict[str, Any]:
    normalized_groups: list[dict[str, Any]] = []
    for idx, group in enumerate(groups):
        difficulty = CONNECTIONS_DIFFICULTY_ORDER[idx]
        labels = [_normalize_connections_label(str(label)) for label in group.get("labels", [])]
        normalized_groups.append(
            {
                "id": difficulty,
                "title": str(group.get("title", f"Group {idx + 1}")).strip() or f"Group {idx + 1}",
                "difficulty": difficulty,
                "labels": labels,
            }
        )

    tiles: list[dict[str, Any]] = []
    for group in normalized_groups:
        group_id = str(group["id"])
        for label in group["labels"]:
            tiles.append({"id": f"tile_{len(tiles) + 1}", "label": label, "groupId": group_id})
    rng.shuffle(tiles)

    cells = []
    for idx in range(16):
        cells.append(
            {
                "x": idx % 4,
                "y": idx // 4,
                "isBlock": False,
                "solution": None,
                "entryIdAcross": None,
                "entryIdDown": None,
            }
        )

    metadata = {
        "difficulty": "medium",
        "themeTags": ["pokemon", "connections"],
        "source": "curated",
        "generatorVersion": GENERATOR_VERSION,
        "connections": {
            "version": 1,
            "tiles": tiles,
            "groups": normalized_groups,
            "difficultyOrder": CONNECTIONS_DIFFICULTY_ORDER,
        },
    }

    puzzle_id = f"puz_connections_{target_date.strftime('%Y%m%d')}_{uuid4().hex[:10]}"
    return {
        "id": puzzle_id,
        "date": target_date,
        "game_type": "connections",
        "title": title or f"Connections Reserve {target_date.isoformat()}",
        "published_at": None,
        "timezone": timezone,
        "grid": json.dumps({"width": 4, "height": 4, "cells": cells}),
        "entries": json.dumps([]),
        "metadata": json.dumps(metadata),
    }


def _build_connections_puzzle_payload(
    *,
    target_date: date_type,
    timezone: str,
    seed_value: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    rng = random.Random(seed_value)
    date_key = target_date.isoformat()

    overrides = _load_connections_overrides()
    override_row = overrides.get(date_key)
    if isinstance(override_row, dict):
        groups = override_row.get("groups")
        if isinstance(groups, list):
            candidate_groups = []
            for row in groups[:4]:
                if not isinstance(row, dict):
                    continue
                labels = row.get("labels")
                if not isinstance(labels, list):
                    continue
                candidate_groups.append(
                    {
                        "title": str(row.get("title", "Override group")).strip() or "Override group",
                        "labels": [_normalize_connections_label(str(label)) for label in labels[:4]],
                    }
                )
            report = _connections_quality_report(groups=candidate_groups)
            _append_connections_quality_report(
                {
                    "date": date_key,
                    "source": "override",
                    "isPublishable": bool(report.get("isPublishable", False)),
                    "score": report.get("score"),
                    "hardFailures": report.get("hardFailures", []),
                    "warnings": report.get("warnings", []),
                }
            )
            if bool(report.get("isPublishable", False)):
                payload = _build_connections_payload_from_groups(
                    target_date=target_date,
                    timezone=timezone,
                    groups=candidate_groups,
                    rng=rng,
                    title=str(override_row.get("title", "")).strip() or f"Connections {date_key}",
                )
                return payload, report
            raise QualityGateError(
                code="connections_override_invalid",
                message="Connections override is invalid for requested date.",
                quality_report=report,
            )

    rules = _load_connections_rules()
    corpus_rows = _load_answer_corpus_rows()
    pools = _build_connections_pool_by_rule(rules, corpus_rows)
    viable_rules = [rule for rule in rules if len(pools.get(str(rule["id"]), [])) >= 4]
    if len(viable_rules) < 4:
        raise RuntimeError("connections_rule_pool_exhausted")

    best_groups: list[dict[str, Any]] | None = None
    best_report: dict[str, Any] | None = None

    for _ in range(140):
        selected_rules = rng.sample(viable_rules, 4)
        candidate_groups: list[dict[str, Any]] = []
        selected_candidate_sets: dict[str, set[str]] = {}
        for idx, rule in enumerate(selected_rules):
            group_id = CONNECTIONS_DIFFICULTY_ORDER[idx]
            pool = pools.get(str(rule["id"]), [])
            labels = rng.sample(pool, 4)
            candidate_groups.append(
                {
                    "id": group_id,
                    "title": str(rule.get("title", "Pokemon category")).strip() or "Pokemon category",
                    "labels": labels,
                }
            )
            selected_candidate_sets[group_id] = set(pool)

        report = _connections_quality_report(groups=candidate_groups, candidate_sets=selected_candidate_sets)
        if best_report is None or float(report.get("score", 0.0)) > float(best_report.get("score", 0.0)):
            best_groups = candidate_groups
            best_report = report
        if bool(report.get("isPublishable", False)):
            break

    if best_groups is None or best_report is None:
        raise RuntimeError("connections_candidate_generation_failed")

    _append_connections_quality_report(
        {
            "date": date_key,
            "source": "auto",
            "isPublishable": bool(best_report.get("isPublishable", False)),
            "score": best_report.get("score"),
            "hardFailures": best_report.get("hardFailures", []),
            "warnings": best_report.get("warnings", []),
        }
    )

    if not bool(best_report.get("isPublishable", False)):
        raise QualityGateError(
            code="connections_quality_gate_rejected",
            message="Connections candidate rejected by quality rules.",
            quality_report=best_report,
        )

    payload = _build_connections_payload_from_groups(
        target_date=target_date,
        timezone=timezone,
        groups=best_groups,
        rng=rng,
        title=f"Connections {date_key}",
    )
    return payload, best_report


def _normalize_answer(name: str) -> str:
    return ANSWER_RE.sub("", name.upper())


def _enumeration_from_display_answer(display_answer: str, normalized_answer: str) -> str:
    text = str(display_answer).strip().upper()
    if not text:
        return str(len(normalized_answer))

    matches = list(ANSWER_PART_RE.finditer(text))
    if not matches:
        return str(len(normalized_answer))
    if len(matches) == 1:
        return str(len(matches[0].group(0)))

    parts = [match.group(0) for match in matches]
    separators: list[str] = []
    prev_end = matches[0].end()
    for match in matches[1:]:
        between = text[prev_end : match.start()]
        separators.append("-" if "-" in between else ",")
        prev_end = match.end()

    out = str(len(parts[0]))
    for idx, part in enumerate(parts[1:], start=1):
        separator = separators[idx - 1] if idx - 1 < len(separators) else ","
        out += f"{separator}{len(part)}"
    return out


def _difficulty(answer_len: int) -> Literal["easy", "medium", "hard"]:
    if answer_len <= 6:
        return "easy"
    if answer_len <= 9:
        return "medium"
    return "hard"


def _crossword_difficulty(entry_count: int, average_length: float) -> Literal["easy", "medium", "hard"]:
    if entry_count <= 12 or average_length <= 6.0:
        return "easy"
    if entry_count <= 22:
        return "medium"
    return "hard"


def _normalize_clue_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", str(value)).strip()


def _clue_has_disallowed_content(clue: str) -> bool:
    text = _normalize_clue_whitespace(clue)
    if not text:
        return True
    return any(pattern.search(text) for pattern in DISALLOWED_CLUE_PATTERNS)


def _csv_header_map(row: list[str]) -> dict[str, int]:
    return {str(value or "").strip().lower().lstrip("\ufeff"): idx for idx, value in enumerate(row)}


def _ordered_clue_column_indices(header_row: list[str]) -> list[int]:
    ordered: list[tuple[int, int]] = []
    for idx, value in enumerate(header_row):
        key = str(value or "").strip().lower().lstrip("\ufeff")
        match = CLUE_COLUMN_RE.match(key)
        if match:
            ordered.append((int(match.group(1)), idx))
    ordered.sort()
    return [idx for _, idx in ordered]


def _load_crossword_csv_lexicon() -> list[dict[str, Any]]:
    if not CROSSWORD_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing crossword CSV at {CROSSWORD_CSV_PATH}")
    clues_by_answer: dict[str, list[str]] = {}
    clue_keys_by_answer: dict[str, set[str]] = {}
    enumeration_by_answer: dict[str, str] = {}
    with CROSSWORD_CSV_PATH.open(newline="") as handle:
        reader = csv.reader(handle)
        first_row = next(reader, None)
        if first_row is None:
            raise RuntimeError("crossword_csv_empty")
        header_map = _csv_header_map(first_row)
        clue_column_indices = _ordered_clue_column_indices(first_row)
        use_header = "answer" in header_map and (bool(clue_column_indices) or "clue" in header_map)
        rows = reader if use_header else [first_row, *reader]
        for row in rows:
            if len(row) < 2:
                continue
            raw_answer = _normalize_clue_whitespace(row[header_map["answer"]] if use_header else row[0]).upper()
            answer = _normalize_answer(raw_answer)
            if not answer:
                continue
            if len(answer) < 4 or len(answer) > 15:
                continue
            enumeration = _enumeration_from_display_answer(raw_answer, answer)
            prior = enumeration_by_answer.get(answer)
            if prior is None or (("," in enumeration or "-" in enumeration) and "," not in prior and "-" not in prior):
                enumeration_by_answer[answer] = enumeration
            candidate_clues: list[str] = []
            if use_header and clue_column_indices:
                for clue_idx in clue_column_indices:
                    if clue_idx >= len(row):
                        continue
                    clue = _normalize_clue_whitespace(row[clue_idx])
                    if clue:
                        candidate_clues.append(clue)
            else:
                clue = _normalize_clue_whitespace(row[header_map["clue"]] if use_header else row[1])
                if clue:
                    candidate_clues.append(clue)
            seen_keys = clue_keys_by_answer.setdefault(answer, set())
            for clue in candidate_clues:
                if _clue_has_disallowed_content(clue):
                    continue
                clue_key = re.sub(r"\s+", " ", clue).strip().upper()
                if clue_key in seen_keys:
                    continue
                seen_keys.add(clue_key)
                clues_by_answer.setdefault(answer, []).append(clue)
    entries: list[dict[str, Any]] = []
    for answer in sorted(clues_by_answer.keys()):
        clues = clues_by_answer[answer]
        if not clues:
            continue
        entries.append(
            {
                "answer": answer,
                "clues": clues,
                "enumeration": enumeration_by_answer.get(answer, str(len(answer))),
            }
        )
    if not entries:
        raise RuntimeError("crossword_csv_empty")
    return entries


def _load_cryptic_json_lexicon(path: Path) -> list[dict[str, Any]]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"cryptic_json_invalid:{path}") from exc

    if not isinstance(loaded, list):
        raise RuntimeError("cryptic_json_invalid")

    entries_by_answer: dict[str, dict[str, Any]] = {}
    clue_keys_by_answer: dict[str, set[str]] = {}
    for row in loaded:
        if not isinstance(row, dict):
            continue

        raw_answer = _normalize_clue_whitespace(str(row.get("answer") or row.get("display_answer") or "")).upper()
        if not raw_answer:
            continue

        answer_key = _normalize_answer(raw_answer)
        if not answer_key or len(answer_key) < 4 or len(answer_key) > 15:
            continue

        display_answer = _normalize_clue_whitespace(str(row.get("display_answer") or raw_answer)).upper()
        enumeration = _normalize_clue_whitespace(str(row.get("enumeration") or "")) or _enumeration_from_display_answer(
            display_answer,
            answer_key,
        )
        source_ref = (
            _normalize_clue_whitespace(str(row.get("source_ref") or "")) or f"json://{path.name}#{answer_key}"
        )
        source_type = _normalize_clue_whitespace(str(row.get("source_type") or "")) or "manual-curated"

        entry = entries_by_answer.setdefault(
            answer_key,
            {
                "answer": answer_key,
                "display_name": display_answer,
                "enumeration": enumeration,
                "source_ref": source_ref,
                "source_type": source_type,
                "clues": [],
            },
        )
        existing_enumeration = str(entry.get("enumeration", "")).strip()
        if ("," in enumeration or "-" in enumeration) and "," not in existing_enumeration and "-" not in existing_enumeration:
            entry["enumeration"] = enumeration

        raw_clues = row.get("clues")
        candidate_clues: list[dict[str, Any]] = []
        if isinstance(raw_clues, list):
            for clue_row in raw_clues:
                if isinstance(clue_row, dict):
                    clue_text = _normalize_clue_whitespace(str(clue_row.get("clue", "")))
                    if not clue_text:
                        continue
                    candidate_clues.append(
                        {
                            "clue": clue_text,
                            "mechanism": str(clue_row.get("mechanism", row.get("mechanism", "manual")) or "manual").strip().lower(),
                            "wordplay_plan": _normalize_clue_whitespace(
                                str(clue_row.get("wordplay_plan", row.get("wordplay_plan", "")) or "")
                            ),
                            "wordplay_metadata": (
                                clue_row.get("wordplay_metadata", {})
                                if isinstance(clue_row.get("wordplay_metadata"), dict)
                                else {}
                            ),
                        }
                    )
                    continue
                clue_text = _normalize_clue_whitespace(str(clue_row))
                if clue_text:
                    candidate_clues.append(
                        {
                            "clue": clue_text,
                            "mechanism": str(row.get("mechanism", "manual") or "manual").strip().lower(),
                            "wordplay_plan": _normalize_clue_whitespace(str(row.get("wordplay_plan", "") or "")),
                            "wordplay_metadata": {},
                        }
                    )
        else:
            clue_text = _normalize_clue_whitespace(str(row.get("clue", "")))
            if clue_text:
                candidate_clues.append(
                    {
                        "clue": clue_text,
                        "mechanism": str(row.get("mechanism", "manual") or "manual").strip().lower(),
                        "wordplay_plan": _normalize_clue_whitespace(str(row.get("wordplay_plan", "") or "")),
                        "wordplay_metadata": row.get("wordplay_metadata", {}) if isinstance(row.get("wordplay_metadata"), dict) else {},
                    }
                )

        seen_keys = clue_keys_by_answer.setdefault(answer_key, set())
        for clue_row in candidate_clues:
            clue = str(clue_row.get("clue", "")).strip()
            if _clue_has_disallowed_content(clue):
                continue
            clue_key = re.sub(r"\s+", " ", clue).strip().upper()
            if clue_key in seen_keys:
                continue
            seen_keys.add(clue_key)
            entry["clues"].append(clue_row)

    entries = [entries_by_answer[key] for key in sorted(entries_by_answer.keys()) if entries_by_answer[key]["clues"]]
    if not entries:
        raise RuntimeError("cryptic_json_empty")
    return entries


def _load_cryptic_csv_lexicon() -> list[dict[str, Any]]:
    if not CRYPTIC_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing cryptic lexicon at {CRYPTIC_CSV_PATH}")
    if CRYPTIC_CSV_PATH.suffix.lower() == ".json":
        return _load_cryptic_json_lexicon(CRYPTIC_CSV_PATH)

    entries_by_answer: dict[str, dict[str, Any]] = {}
    clue_keys_by_answer: dict[str, set[str]] = {}
    with CRYPTIC_CSV_PATH.open(newline="") as handle:
        reader = csv.reader(handle)
        first_row = next(reader, None)
        if first_row is None:
            raise RuntimeError("cryptic_csv_empty")
        header_map = _csv_header_map(first_row)
        clue_column_indices = _ordered_clue_column_indices(first_row)
        use_header = "answer" in header_map and (bool(clue_column_indices) or "clue" in header_map)
        rows = reader if use_header else [first_row, *reader]

        for row in rows:
            if len(row) < 2:
                continue

            def _cell(name: str, fallback_idx: int | None = None) -> str:
                if use_header:
                    idx = header_map.get(name)
                    if idx is None or idx >= len(row):
                        return ""
                    return _normalize_clue_whitespace(row[idx])
                if fallback_idx is None or fallback_idx >= len(row):
                    return ""
                return _normalize_clue_whitespace(row[fallback_idx])

            raw_answer = _cell("answer", 0).upper()
            if not raw_answer:
                continue

            answer_key = _normalize_answer(raw_answer)
            if not answer_key or len(answer_key) < 4 or len(answer_key) > 15:
                continue

            display_answer = (_cell("display_answer", 2) or raw_answer).upper()
            enumeration = _cell("enumeration", 3) or _enumeration_from_display_answer(display_answer, answer_key)
            mechanism = (_cell("mechanism", 4) or "manual").strip().lower()
            wordplay_plan = _cell("wordplay_plan", 5)
            source_ref = _cell("source_ref", 6) or f"csv://wordlist_cryptic_answer_clue.csv#{answer_key}"
            source_type = _cell("source_type", 7) or "manual-curated"

            entry = entries_by_answer.setdefault(
                answer_key,
                {
                    "answer": answer_key,
                    "display_name": display_answer,
                    "enumeration": enumeration,
                    "source_ref": source_ref,
                    "source_type": source_type,
                    "clues": [],
                },
            )
            existing_enumeration = str(entry.get("enumeration", "")).strip()
            if ("," in enumeration or "-" in enumeration) and "," not in existing_enumeration and "-" not in existing_enumeration:
                entry["enumeration"] = enumeration
            candidate_clues: list[str] = []
            if use_header and clue_column_indices:
                for clue_idx in clue_column_indices:
                    if clue_idx >= len(row):
                        continue
                    clue = _normalize_clue_whitespace(row[clue_idx])
                    if clue:
                        candidate_clues.append(clue)
            else:
                clue = _cell("clue", 1)
                if clue:
                    candidate_clues.append(clue)

            seen_keys = clue_keys_by_answer.setdefault(answer_key, set())
            for clue in candidate_clues:
                if _clue_has_disallowed_content(clue):
                    continue
                clue_key = re.sub(r"\s+", " ", clue).strip().upper()
                if clue_key in seen_keys:
                    continue
                seen_keys.add(clue_key)
                entry["clues"].append(
                    {
                        "clue": clue,
                        "mechanism": mechanism,
                        "wordplay_plan": wordplay_plan,
                        "wordplay_metadata": {},
                    }
                )

    entries = [entries_by_answer[key] for key in sorted(entries_by_answer.keys()) if entries_by_answer[key]["clues"]]
    if not entries:
        raise RuntimeError("cryptic_csv_empty")
    return entries


def _load_cryptic_lexicon() -> list[dict[str, Any]]:
    if not CRYPTIC_CSV_PATH.exists():
        raise FileNotFoundError(f"Missing cryptic lexicon at {CRYPTIC_CSV_PATH}")
    return _load_cryptic_csv_lexicon()


def _materialize_crossword_lexicon_for_run(
    lexicon: list[dict[str, Any]],
    *,
    seed_value: int,
) -> list[dict[str, Any]]:
    selected_rows: list[dict[str, Any]] = []
    for row in lexicon:
        answer = str(row.get("answer", "")).strip()
        clues = row.get("clues")
        if not answer or not isinstance(clues, list):
            continue
        enumeration = str(row.get("enumeration", "")).strip() or str(len(answer))
        clean_clues = [
            _normalize_clue_whitespace(str(clue))
            for clue in clues
            if _normalize_clue_whitespace(str(clue)) and not _clue_has_disallowed_content(str(clue))
        ]
        if not clean_clues:
            continue
        digest = hashlib.sha256(f"{answer}:{seed_value}".encode("utf-8")).hexdigest()
        clue = clean_clues[int(digest[:8], 16) % len(clean_clues)]
        selected_rows.append({"answer": answer, "clue": clue, "enumeration": enumeration})
    return selected_rows


def _materialize_cryptic_lexicon_for_run(
    lexicon: list[dict[str, Any]],
    *,
    seed_value: int,
) -> list[dict[str, Any]]:
    selected_rows: list[dict[str, Any]] = []
    for row in lexicon:
        answer = str(row.get("answer", "")).strip()
        clues = row.get("clues")
        if not answer or not isinstance(clues, list):
            continue
        clean_clues = [
            clue_row
            for clue_row in clues
            if isinstance(clue_row, dict)
            and _normalize_clue_whitespace(str(clue_row.get("clue", "")))
            and not _clue_has_disallowed_content(str(clue_row.get("clue", "")))
        ]
        if not clean_clues:
            continue
        digest = hashlib.sha256(f"{answer}:{seed_value}".encode("utf-8")).hexdigest()
        selected = dict(clean_clues[int(digest[:8], 16) % len(clean_clues)])
        selected["clue"] = _normalize_clue_whitespace(str(selected.get("clue", "")))
        selected_rows.append(
            {
                "answer": answer,
                "display_name": str(row.get("display_name", answer)).strip() or answer,
                "enumeration": str(row.get("enumeration", "")).strip() or str(len(answer)),
                "source_ref": str(row.get("source_ref", "")).strip() or f"manual://cryptic_lexicon#{answer}",
                "source_type": str(row.get("source_type", "")).strip() or "manual-curated",
                "clue": str(selected.get("clue", "")).strip(),
                "mechanism": str(selected.get("mechanism", "manual") or "manual").strip().lower(),
                "wordplay_plan": str(selected.get("wordplay_plan", "") or "").strip(),
                "wordplay_metadata": selected.get("wordplay_metadata", {}) if isinstance(selected.get("wordplay_metadata"), dict) else {},
                "all_clues": clean_clues,
            }
        )
    return selected_rows


def _crossword_letter_map(placed: list[dict[str, Any]]) -> dict[tuple[int, int], str]:
    letters: dict[tuple[int, int], str] = {}
    for item in placed:
        answer = str(item["answer"])
        x = int(item["x"])
        y = int(item["y"])
        direction = str(item["direction"])
        dx, dy = (1, 0) if direction == "across" else (0, 1)
        for idx, ch in enumerate(answer):
            letters[(x + idx * dx, y + idx * dy)] = ch
    return letters


def _can_place_word(
    *,
    answer: str,
    x: int,
    y: int,
    direction: str,
    letters: dict[tuple[int, int], str],
) -> tuple[bool, int, int]:
    dx, dy = (1, 0) if direction == "across" else (0, 1)
    perp_a = (-dy, dx)
    perp_b = (dy, -dx)

    before = (x - dx, y - dy)
    after = (x + dx * len(answer), y + dy * len(answer))
    if before in letters or after in letters:
        return False, 0, 0

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

        side_a = (cx + perp_a[0], cy + perp_a[1])
        side_b = (cx + perp_b[0], cy + perp_b[1])
        if side_a in letters or side_b in letters:
            return False, 0, 0
        new_cells += 1

    return True, intersections, new_cells


def _try_build_crossword_layout(
    lexicon: list[dict[str, Any]],
    *,
    rng: random.Random,
    target_entries: int,
    min_entries: int,
    max_width: int,
    max_height: int,
) -> list[dict[str, Any]] | None:
    letter_freq: dict[str, int] = {}
    for row in lexicon:
        for ch in set(str(row["answer"])):
            letter_freq[ch] = letter_freq.get(ch, 0) + 1

    pool = list(lexicon)
    rng.shuffle(pool)
    pool = pool[: min(len(pool), 320)]

    def starter_score(item: dict[str, Any]) -> tuple[int, int]:
        answer = str(item["answer"])
        overlap = sum(letter_freq.get(ch, 0) for ch in set(answer))
        return (overlap, len(answer))

    starter = max(pool, key=starter_score)
    placed: list[dict[str, Any]] = [{"answer": starter["answer"], "clue": starter["clue"], "x": 0, "y": 0, "direction": "across"}]
    used = {str(starter["answer"])}

    def maybe_within_bounds(candidate: list[dict[str, Any]]) -> bool:
        letters = _crossword_letter_map(candidate)
        xs = [coord[0] for coord in letters.keys()]
        ys = [coord[1] for coord in letters.keys()]
        width = (max(xs) - min(xs) + 1) if xs else 0
        height = (max(ys) - min(ys) + 1) if ys else 0
        return width <= max_width and height <= max_height

    words = sorted(pool, key=lambda row: (len(str(row["answer"])), rng.random()), reverse=True)
    for row in words:
        answer = str(row["answer"])
        if answer in used:
            continue
        letters = _crossword_letter_map(placed)
        candidates: list[tuple[float, dict[str, Any]]] = []
        for (cx, cy), cell_ch in letters.items():
            for idx, word_ch in enumerate(answer):
                if word_ch != cell_ch:
                    continue
                for direction in ("across", "down"):
                    dx, dy = (1, 0) if direction == "across" else (0, 1)
                    start_x = cx - idx * dx
                    start_y = cy - idx * dy
                    ok, intersections, new_cells = _can_place_word(
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
                        "enumeration": row.get("enumeration"),
                        "x": start_x,
                        "y": start_y,
                        "direction": direction,
                    }
                    if not maybe_within_bounds(placed + [entry]):
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


def _build_crossword_puzzle_payload(
    *,
    target_date: date_type,
    timezone: str,
    lexicon: list[dict[str, Any]],
    seed_value: int,
) -> dict[str, Any]:
    rng = random.Random(seed_value)
    selected_lexicon = _materialize_crossword_lexicon_for_run(lexicon, seed_value=seed_value)
    if not selected_lexicon:
        raise RuntimeError("crossword_csv_empty")
    layout: list[dict[str, Any]] | None = None
    for _ in range(28):
        target_entries = rng.randint(16, 26)
        layout = _try_build_crossword_layout(
            selected_lexicon,
            rng=rng,
            target_entries=target_entries,
            min_entries=12,
            max_width=23,
            max_height=21,
        )
        if layout is not None:
            break
    if layout is None:
        raise RuntimeError("crossword_layout_failed")

    letters = _crossword_letter_map(layout)
    min_x = min(x for x, _ in letters.keys())
    max_x = max(x for x, _ in letters.keys())
    min_y = min(y for _, y in letters.keys())
    max_y = max(y for _, y in letters.keys())
    width = max_x - min_x + 1
    height = max_y - min_y + 1

    shifted: list[dict[str, Any]] = []
    for item in layout:
        shifted.append(
            {
                "answer": item["answer"],
                "clue": item["clue"],
                "enumeration": item.get("enumeration"),
                "direction": item["direction"],
                "x": int(item["x"]) - min_x,
                "y": int(item["y"]) - min_y,
            }
        )

    starts = sorted({(entry["x"], entry["y"]) for entry in shifted}, key=lambda c: (c[1], c[0]))
    number_by_start: dict[tuple[int, int], int] = {pos: idx for idx, pos in enumerate(starts, start=1)}

    entries: list[dict[str, Any]] = []
    for entry in shifted:
        answer = str(entry["answer"])
        x = int(entry["x"])
        y = int(entry["y"])
        direction = str(entry["direction"])
        number = number_by_start[(x, y)]
        dx, dy = (1, 0) if direction == "across" else (0, 1)
        cells = [[x + i * dx, y + i * dy] for i in range(len(answer))]
        entry_id = ("a" if direction == "across" else "d") + str(number)
        entries.append(
            {
                "id": entry_id,
                "direction": direction,
                "number": number,
                "answer": answer,
                "clue": str(entry["clue"]),
                "length": len(answer),
                "cells": cells,
                "sourceRef": f"csv://wordlist_crossword_answer_clue.csv#{answer}",
                "enumeration": str(entry.get("enumeration") or len(answer)),
            }
        )
    entries.sort(key=lambda row: (int(row["number"]), 0 if row["direction"] == "across" else 1))

    entry_id_across_by_cell: dict[tuple[int, int], str] = {}
    entry_id_down_by_cell: dict[tuple[int, int], str] = {}
    shifted_letters = {(x - min_x, y - min_y): ch for (x, y), ch in letters.items()}
    for entry in entries:
        for cx, cy in entry["cells"]:
            key = (int(cx), int(cy))
            if entry["direction"] == "across":
                entry_id_across_by_cell[key] = str(entry["id"])
            else:
                entry_id_down_by_cell[key] = str(entry["id"])

    grid_cells: list[dict[str, Any]] = []
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
                continue
            grid_cells.append(
                {
                    "x": x,
                    "y": y,
                    "isBlock": False,
                    "solution": letter,
                    "entryIdAcross": entry_id_across_by_cell.get((x, y)),
                    "entryIdDown": entry_id_down_by_cell.get((x, y)),
                }
            )

    avg_len = sum(len(str(item["answer"])) for item in shifted) / max(len(shifted), 1)
    metadata = {
        "difficulty": _crossword_difficulty(len(entries), avg_len),
        "themeTags": ["pokemon", "worksheet", "crossword"],
        "source": "curated",
        "generatorVersion": GENERATOR_VERSION,
    }
    title = f"Crossword Reserve {target_date.isoformat()} · Worksheet"
    puzzle_id = f"puz_crossword_{target_date.strftime('%Y%m%d')}_{uuid4().hex[:10]}"
    return {
        "id": puzzle_id,
        "date": target_date,
        "game_type": "crossword",
        "title": title,
        "published_at": None,
        "timezone": timezone,
        "grid": json.dumps({"width": width, "height": height, "cells": grid_cells}),
        "entries": json.dumps(entries),
        "metadata": json.dumps(metadata),
    }


def _decode_payload_json_field(payload: dict[str, Any], field: str) -> dict[str, Any] | list[Any]:
    raw_value = payload[field]
    if isinstance(raw_value, str):
        decoded = json.loads(raw_value)
    else:
        decoded = raw_value
    if not isinstance(decoded, dict | list):
        raise RuntimeError(f"payload_{field}_invalid")
    return decoded


def _attach_crossword_quality_report(payload: dict[str, Any]) -> dict[str, Any]:
    grid = _decode_payload_json_field(payload, "grid")
    entries = _decode_payload_json_field(payload, "entries")
    metadata = _decode_payload_json_field(payload, "metadata")
    if not isinstance(grid, dict) or not isinstance(entries, list) or not isinstance(metadata, dict):
        raise RuntimeError("crossword_payload_structure_invalid")

    report = evaluate_crossword_publishability(
        grid=grid,
        entries=entries,
        metadata=metadata,
    )
    metadata["qualityReport"] = report
    payload["metadata"] = json.dumps(metadata)
    return report


def _build_governed_crossword_puzzle_payload(
    *,
    target_date: date_type,
    timezone: str,
    lexicon: list[dict[str, str]],
    seed_value: int,
    allow_fallback: bool = False,
    max_attempts: int = MAX_CROSSWORD_QUALITY_ATTEMPTS,
) -> tuple[dict[str, Any], dict[str, Any], bool, int]:
    best_payload: dict[str, Any] | None = None
    best_report: dict[str, Any] | None = None

    for attempt in range(max(1, max_attempts)):
        candidate_seed = seed_value + (attempt * QUALITY_RETRY_SEED_DELTA)
        candidate_payload = _build_crossword_puzzle_payload(
            target_date=target_date,
            timezone=timezone,
            lexicon=lexicon,
            seed_value=candidate_seed,
        )
        report = _attach_crossword_quality_report(candidate_payload)
        if best_report is None or float(report.get("score", 0.0)) > float(best_report.get("score", 0.0)):
            best_payload = candidate_payload
            best_report = report
        if bool(report.get("isPublishable", False)):
            return candidate_payload, report, False, attempt + 1

    if best_payload is None or best_report is None:
        raise QualityGateError(
            code="crossword_quality_evaluation_failed",
            message="Crossword quality evaluation failed before a publishable candidate was produced.",
            attempts_used=max(1, max_attempts),
        )
    if allow_fallback:
        return best_payload, best_report, True, max(1, max_attempts)
    hard_failures = best_report.get("hardFailures", [])
    normalized_hard_failures = {str(item) for item in hard_failures} if isinstance(hard_failures, list) else set()
    code = (
        "crossword_disallowed_clue_content_detected"
        if "clue_contains_disallowed_content" in normalized_hard_failures
        else "crossword_quality_gate_rejected"
    )
    raise QualityGateError(
        code=code,
        message="Crossword puzzle rejected by quality gate after retry budget exhausted.",
        quality_report=best_report,
        attempts_used=max(1, max_attempts),
    )


def _build_single_entry_puzzle_payload(
    game_type: Literal["crossword", "cryptic"],
    target_date: date_type,
    timezone: str,
    answer: str,
    clue: str,
    display_name: str,
    source_ref: str,
    mechanism: str | None = None,
    enumeration: str | None = None,
    wordplay_plan: str | None = None,
    wordplay_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    width = 15
    height = 15
    start_x = (width - len(answer)) // 2
    y = height // 2
    cells = [
        {
            "x": start_x + i,
            "y": y,
            "isBlock": False,
            "solution": ch,
            "entryIdAcross": "a1",
            "entryIdDown": None,
        }
        for i, ch in enumerate(answer)
    ]
    entries = [
        {
            "id": "a1",
            "direction": "across",
            "number": 1,
            "answer": answer,
            "clue": clue,
            "length": len(answer),
            "cells": [[start_x + i, y] for i in range(len(answer))],
            "sourceRef": source_ref,
            "mechanism": mechanism,
            "enumeration": enumeration,
            "wordplayPlan": wordplay_plan,
            "wordplayMetadata": wordplay_metadata if isinstance(wordplay_metadata, dict) else None,
        }
    ]
    metadata = {
        "difficulty": _difficulty(len(answer)),
        "themeTags": ["pokemon", "reserve", game_type],
        "source": "curated",
        "generatorVersion": GENERATOR_VERSION,
    }
    title = f"{game_type.title()} Reserve {target_date.isoformat()} · {display_name}"
    puzzle_id = f"puz_{game_type}_{target_date.strftime('%Y%m%d')}_{uuid4().hex[:10]}"
    return {
        "id": puzzle_id,
        "date": target_date,
        "game_type": game_type,
        "title": title,
        "published_at": None,
        "timezone": timezone,
        "grid": json.dumps({"width": width, "height": height, "cells": cells}),
        "entries": json.dumps(entries),
        "metadata": json.dumps(metadata),
    }


def _allocate_dates(
    existing_dates: set[date_type],
    start_date: date_type,
    count: int,
) -> list[date_type]:
    out: list[date_type] = []
    current = start_date
    while len(out) < count:
        if current not in existing_dates:
            out.append(current)
        current += timedelta(days=1)
    return out


def _insert_cryptic_candidate_rows(
    cur,
    *,
    job_id: str,
    puzzle_id: str,
    target_date: date_type,
    source_ref: str,
    source_type: str,
    answer_key: str,
    answer_display: str,
    clue_text: str,
    mechanism: str,
    wordplay_plan: str | None = None,
    wordplay_metadata: dict[str, Any] | None = None,
) -> None:
    cur.execute(
        "INSERT INTO cryptic_candidates ("
        "job_id, puzzle_id, target_date, source_ref, source_type, answer_key, answer_display, "
        "clue_text, mechanism, wordplay_plan, validator_passed, validator_issues, rank_score, rank_position, selected"
        ") VALUES ("
        "%(job_id)s, %(puzzle_id)s, %(target_date)s, %(source_ref)s, %(source_type)s, %(answer_key)s, %(answer_display)s, "
        "%(clue_text)s, %(mechanism)s, %(wordplay_plan)s::json, %(validator_passed)s, %(validator_issues)s::json, "
        "%(rank_score)s, %(rank_position)s, %(selected)s"
        ")",
        {
            "job_id": job_id,
            "puzzle_id": puzzle_id,
            "target_date": target_date,
            "source_ref": source_ref,
            "source_type": source_type,
            "answer_key": answer_key,
            "answer_display": answer_display,
            "clue_text": clue_text,
            "mechanism": mechanism or "manual",
            "wordplay_plan": json.dumps(
                {
                    "text": wordplay_plan or "",
                    "metadata": wordplay_metadata if isinstance(wordplay_metadata, dict) else {},
                }
            ),
            "validator_passed": True,
            "validator_issues": json.dumps([]),
            "rank_score": 100.0,
            "rank_position": 1,
            "selected": True,
        },
    )


def generate_cryptic_preview(
    *,
    limit: int = 5,
    top_k: int = 3,
    answer_key: str | None = None,
    include_invalid: bool = False,
) -> dict[str, Any]:
    del include_invalid
    lexicon = _load_cryptic_lexicon()
    normalized_answer_key = _normalize_answer(answer_key) if answer_key else None

    if normalized_answer_key:
        selected_entries = [row for row in lexicon if row.get("answer") == normalized_answer_key]
    else:
        selected_entries = list(lexicon)
        random.shuffle(selected_entries)
        selected_entries = selected_entries[:limit]

    items: list[dict[str, Any]] = []
    today_seed = int(datetime.now(ZoneInfo("Europe/London")).strftime("%Y%m%d"))
    for entry in selected_entries:
        materialized = _materialize_cryptic_lexicon_for_run([entry], seed_value=today_seed)
        if not materialized:
            continue
        selected = materialized[0]
        visible_candidates = []
        for idx, clue_row in enumerate(entry.get("clues", [])[:top_k], start=1):
            if not isinstance(clue_row, dict):
                continue
            visible_candidates.append(
                {
                    "clue": str(clue_row.get("clue", "")),
                    "mechanism": str(clue_row.get("mechanism", "manual") or "manual"),
                    "rankScore": float(max(0, top_k - idx + 1)),
                    "rankPosition": idx,
                    "validatorPassed": True,
                    "validatorIssues": [],
                    "wordplayPlan": str(clue_row.get("wordplay_plan", "") or ""),
                    "metadata": clue_row.get("wordplay_metadata", {}) if isinstance(clue_row.get("wordplay_metadata"), dict) else {},
                }
            )

        items.append(
            {
                "answer": entry.get("display_name") or entry.get("answer"),
                "answerKey": entry.get("answer"),
                "enumeration": entry.get("enumeration"),
                "sourceType": entry.get("source_type"),
                "sourceRef": entry.get("source_ref"),
                "selected": {
                    "clue": selected.get("clue"),
                    "mechanism": selected.get("mechanism"),
                    "rankScore": 100.0,
                    "validatorPassed": True,
                    "validatorIssues": [],
                    "wordplayPlan": selected.get("wordplay_plan"),
                    "metadata": selected.get("wordplay_metadata", {}),
                },
                "candidates": visible_candidates,
            }
        )

    return {
        "items": items,
        "count": len(items),
        "requestedLimit": limit,
        "topK": top_k,
        "answerKey": normalized_answer_key,
        "includeInvalid": False,
    }


def _select_cryptic_candidate_for_date(
    lexicon: list[dict[str, Any]],
    *,
    target_date: date_type,
    excluded_answers: set[str] | None = None,
) -> dict[str, Any] | None:
    seed_value = int(target_date.strftime("%Y%m%d"))
    materialized = _materialize_cryptic_lexicon_for_run(lexicon, seed_value=seed_value)
    rng = random.Random(seed_value)
    rng.shuffle(materialized)
    seen_answers = excluded_answers or set()
    for row in materialized:
        answer = str(row.get("answer", "")).strip()
        if not answer or answer in seen_answers:
            continue
        return row
    return None


def _insert_generation_job(
    cur,
    job_id: str,
    job_date: date_type,
    model_version: str,
    job_type: str = "reserve_topup",
) -> None:
    cur.execute(
        "INSERT INTO generation_jobs "
        "(id, type, date, status, started_at, model_version) "
        "VALUES (%(id)s, %(type)s, %(date)s, %(status)s, %(started_at)s, %(model_version)s)",
        {
            "id": job_id,
            "type": job_type,
            "date": job_date,
            "status": "running",
            "started_at": datetime.now(ZoneInfo("UTC")),
            "model_version": model_version,
        },
    )


def _complete_generation_job(cur, job_id: str, status: str, logs: str) -> None:
    cur.execute(
        "UPDATE generation_jobs "
        "SET status = %(status)s, finished_at = %(finished_at)s, logs_url = %(logs_url)s "
        "WHERE id = %(id)s",
        {
            "id": job_id,
            "status": status,
            "finished_at": datetime.now(ZoneInfo("UTC")),
            "logs_url": logs,
        },
    )


def _puzzle_payload_for_artifact(
    *,
    payload: dict[str, Any],
    game_type: Literal["crossword", "cryptic", "connections"],
    job_id: str,
) -> dict[str, Any]:
    return {
        "id": payload["id"],
        "date": str(payload["date"]),
        "gameType": game_type,
        "title": payload["title"],
        "timezone": payload["timezone"],
        "grid": json.loads(payload["grid"]),
        "entries": json.loads(payload["entries"]),
        "metadata": json.loads(payload["metadata"]),
        "jobId": job_id,
        "generatedAt": datetime.now(ZoneInfo("UTC")).isoformat(),
    }


def _mark_generation_job_failed(
    job_id: str,
    job_date: date_type,
    error_message: str,
    model_version: str,
    job_type: str = "reserve_topup",
) -> None:
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE generation_jobs "
                "SET status = %(status)s, finished_at = %(finished_at)s, logs_url = %(logs_url)s "
                "WHERE id = %(id)s",
                {
                    "id": job_id,
                    "status": "failed",
                    "finished_at": datetime.now(ZoneInfo("UTC")),
                    "logs_url": error_message,
                },
            )
            if cur.rowcount == 0:
                cur.execute(
                    "INSERT INTO generation_jobs "
                    "(id, type, date, status, started_at, finished_at, logs_url, model_version) "
                    "VALUES ("
                    "%(id)s, %(type)s, %(date)s, %(status)s, %(started_at)s, %(finished_at)s, %(logs_url)s, %(model_version)s"
                    ")",
                    {
                        "id": job_id,
                        "type": job_type,
                        "date": job_date,
                        "status": "failed",
                        "started_at": datetime.now(ZoneInfo("UTC")),
                        "finished_at": datetime.now(ZoneInfo("UTC")),
                        "logs_url": error_message,
                        "model_version": model_version,
                    },
                )
        conn.commit()

    notify_external_alert(
        event_type="generation_job_failed",
        severity="error",
        message=f"{job_type} failed for {job_date.isoformat()}",
        details={
            "jobId": job_id,
            "jobType": job_type,
            "date": job_date.isoformat(),
            "modelVersion": model_version,
            "error": error_message,
        },
    )


def top_up_reserve(
    game_type: Literal["crossword", "cryptic", "connections"],
    target_count: int,
    timezone: str,
    max_create_per_run: int = 25,
) -> dict[str, Any]:
    tz = ZoneInfo(timezone)
    today = datetime.now(tz).date()
    inserted = 0
    reserve_count = 0
    reserve_after = 0
    job_id = f"job_reserve_topup_{game_type}_{uuid4().hex[:10]}"
    job_model_version = f"{GENERATOR_VERSION}:{game_type}"
    puzzle_artifacts: list[str] = []
    quality_fallbacks: list[dict[str, Any]] = []
    quality_attempts_total = 0
    quality_evaluated_count = 0
    cryptic_shortfall_count = 0
    target_dates: list[date_type] = []

    try:
        with get_db() as conn:
            cursor_kwargs = {"row_factory": dict_row} if dict_row is not None else {}
            with conn.cursor(**cursor_kwargs) as cur:
                _insert_generation_job(
                    cur,
                    job_id=job_id,
                    job_date=today,
                    model_version=job_model_version,
                )
                cur.execute(
                    "SELECT COUNT(*) AS reserve_count "
                    "FROM puzzles "
                    "WHERE game_type = %(game_type)s "
                    "AND published_at IS NULL AND date > %(today)s",
                    {"game_type": game_type, "today": today},
                )
                reserve_count = int(cur.fetchone()["reserve_count"])
                missing = max(target_count - reserve_count, 0)
                to_create = min(missing, max_create_per_run)

                if to_create > 0:
                    cur.execute(
                        "SELECT date FROM puzzles WHERE game_type = %(game_type)s AND date >= %(start_date)s",
                        {"game_type": game_type, "start_date": today + timedelta(days=1)},
                    )
                    existing_dates = {cast_row["date"] for cast_row in cur.fetchall()}
                    target_dates = _allocate_dates(existing_dates, today + timedelta(days=1), to_create)

                    crossword_lexicon: list[dict[str, Any]] | None = None
                    cryptic_lexicon: list[dict[str, Any]] | None = None
                    if game_type == "cryptic":
                        cur.execute(
                            "SELECT entries->0->>'answer' AS answer "
                            "FROM puzzles "
                            "WHERE game_type = %(game_type)s AND published_at IS NULL AND date > %(today)s",
                            {"game_type": game_type, "today": today},
                        )
                        existing_answers = {row["answer"] for row in cur.fetchall() if row.get("answer")}
                        cryptic_lexicon = _load_cryptic_lexicon()
                    elif game_type == "crossword":
                        crossword_lexicon = _load_crossword_csv_lexicon()

                    cryptic_shortfall_count = 0
                    for idx, target_date in enumerate(target_dates):
                        candidate: dict[str, Any] | None = None
                        if game_type == "crossword":
                            if crossword_lexicon is None:
                                raise RuntimeError("crossword_lexicon_unavailable")
                            payload, quality_report, quality_bypassed, attempts_used = _build_governed_crossword_puzzle_payload(
                                target_date=target_date,
                                timezone=timezone,
                                lexicon=crossword_lexicon,
                                seed_value=int(target_date.strftime("%Y%m%d")) + idx,
                                allow_fallback=True,
                            )
                            quality_attempts_total += attempts_used
                            quality_evaluated_count += 1
                            if quality_bypassed:
                                quality_fallbacks.append(
                                    {
                                        "date": target_date.isoformat(),
                                        "score": quality_report.get("score"),
                                        "hardFailures": quality_report.get("hardFailures", []),
                                        "warnings": quality_report.get("warnings", []),
                                    }
                                )
                        elif game_type == "cryptic":
                            if cryptic_lexicon is None:
                                raise RuntimeError("cryptic_lexicon_unavailable")
                            candidate = _select_cryptic_candidate_for_date(
                                cryptic_lexicon,
                                target_date=target_date,
                                excluded_answers=existing_answers,
                            )
                            if candidate is None:
                                cryptic_shortfall_count = len(target_dates) - idx
                                break
                            existing_answers.add(str(candidate.get("answer", "")))
                            payload = _build_single_entry_puzzle_payload(
                                game_type=game_type,
                                target_date=target_date,
                                timezone=timezone,
                                answer=candidate["answer"],
                                clue=candidate["clue"],
                                display_name=candidate["display_name"],
                                source_ref=candidate["source_ref"],
                                mechanism=candidate.get("mechanism"),
                                enumeration=candidate.get("enumeration"),
                                wordplay_plan=candidate.get("wordplay_plan"),
                                wordplay_metadata=candidate.get("wordplay_metadata"),
                            )
                        else:
                            payload, _ = _build_connections_puzzle_payload(
                                target_date=target_date,
                                timezone=timezone,
                                seed_value=int(target_date.strftime("%Y%m%d")) + idx,
                            )
                        cur.execute(
                            "INSERT INTO puzzles "
                            "(id, date, game_type, title, published_at, timezone, grid, entries, metadata) "
                            "VALUES ("
                            "%(id)s, %(date)s, %(game_type)s, %(title)s, %(published_at)s, %(timezone)s, "
                            "%(grid)s::json, %(entries)s::json, %(metadata)s::json"
                            ") "
                            "ON CONFLICT (id) DO NOTHING",
                            payload,
                        )
                        if cur.rowcount == 1:
                            inserted += 1
                            artifact_ref = write_json_artifact(
                                artifact_type="puzzles",
                                object_id=str(payload["id"]),
                                payload=_puzzle_payload_for_artifact(
                                    payload=payload,
                                    game_type=game_type,
                                    job_id=job_id,
                                ),
                            )
                            if artifact_ref:
                                puzzle_artifacts.append(artifact_ref)
                            if game_type == "cryptic":
                                if candidate is None:
                                    raise RuntimeError("cryptic_candidate_unavailable")
                                _insert_cryptic_candidate_rows(
                                    cur,
                                    job_id=job_id,
                                    puzzle_id=payload["id"],
                                    target_date=target_date,
                                    source_ref=candidate.get("source_ref", ""),
                                    source_type=candidate.get("source_type", ""),
                                    answer_key=candidate.get("answer", ""),
                                    answer_display=candidate.get("display_name", ""),
                                    clue_text=str(candidate.get("clue", "")),
                                    mechanism=str(candidate.get("mechanism", "manual") or "manual"),
                                    wordplay_plan=str(candidate.get("wordplay_plan", "") or ""),
                                    wordplay_metadata=candidate.get("wordplay_metadata", {}),
                                )

                cur.execute(
                    "SELECT COUNT(*) AS reserve_count "
                    "FROM puzzles "
                    "WHERE game_type = %(game_type)s "
                    "AND published_at IS NULL AND date > %(today)s",
                    {"game_type": game_type, "today": today},
                )
                reserve_after = int(cur.fetchone()["reserve_count"])
                if game_type == "cryptic" and cryptic_shortfall_count == 0 and inserted < len(target_dates):
                    cryptic_shortfall_count = len(target_dates) - inserted
                if game_type == "cryptic" and cryptic_shortfall_count > 0:
                    notify_external_alert(
                        event_type="cryptic_reserve_shortfall",
                        severity="warning",
                        message=f"Cryptic reserve top-up shortfall: requested={len(target_dates)} created={inserted}",
                        details={
                            "gameType": game_type,
                            "jobId": job_id,
                            "today": today.isoformat(),
                            "requested": len(target_dates),
                            "created": inserted,
                            "shortfall": cryptic_shortfall_count,
                        },
                    )
                _complete_generation_job(
                    cur,
                    job_id=job_id,
                    status="succeeded",
                    logs=json.dumps(
                        {
                            "gameType": game_type,
                            "inserted": inserted,
                            "reserveCountBefore": reserve_count,
                            "reserveCountAfter": reserve_after,
                            "targetCount": target_count,
                            "rankerModelVersion": None,
                            "artifactRefs": puzzle_artifacts,
                            "qualityGate": {
                                "evaluated": quality_evaluated_count,
                                "averageAttempts": round(
                                    quality_attempts_total / max(quality_evaluated_count, 1),
                                    2,
                                )
                                if game_type == "crossword"
                                else None,
                                "fallbackCount": len(quality_fallbacks) if game_type == "crossword" else 0,
                                "fallbacks": quality_fallbacks if game_type == "crossword" else [],
                                "crypticShortfallCount": cryptic_shortfall_count if game_type == "cryptic" else 0,
                            },
                        }
                    ),
                )
            conn.commit()
    except Exception as exc:
        _mark_generation_job_failed(
            job_id=job_id,
            job_date=today,
            error_message=f"{type(exc).__name__}: {exc}",
            model_version=job_model_version,
        )
        raise

    if inserted > 0:
        try:
            cache = get_cache()
            keys = list(cache.scan_iter(match=f"puzzle:reserve:{game_type}:*"))
            if keys:
                cache.delete(*keys)
        except RuntimeError:
            pass

    if game_type == "crossword" and quality_fallbacks:
        notify_external_alert(
            event_type="crossword_quality_fallback",
            severity="warning",
            message=f"Crossword quality gate fallback used for {len(quality_fallbacks)} reserve puzzle(s)",
            details={
                "jobId": job_id,
                "today": today.isoformat(),
                "fallbacks": quality_fallbacks,
            },
        )

    return {
        "jobId": job_id,
        "gameType": game_type,
        "today": today.isoformat(),
        "targetCount": target_count,
        "reserveCountBefore": reserve_count,
        "reserveCountAfter": reserve_after,
        "inserted": inserted,
        "shortfallCount": cryptic_shortfall_count if game_type == "cryptic" else 0,
        "rankerModelVersion": None,
        "qualityFallbackCount": len(quality_fallbacks) if game_type == "crossword" else 0,
    }


def generate_puzzle_for_date(
    *,
    game_type: Literal["crossword", "cryptic", "connections"],
    target_date: date_type,
    timezone: str,
    force: bool = False,
) -> dict[str, Any]:
    job_id = f"job_generate_{game_type}_{uuid4().hex[:10]}"
    job_model_version = f"{GENERATOR_VERSION}:{game_type}"

    existing_puzzle_id: str | None = None
    generated_puzzle_id: str | None = None
    generated_artifact_ref: str | None = None
    quality_report: dict[str, Any] | None = None
    quality_bypassed = False
    quality_attempts_used = 0

    try:
        with get_db() as conn:
            cursor_kwargs = {"row_factory": dict_row} if dict_row is not None else {}
            with conn.cursor(**cursor_kwargs) as cur:
                _insert_generation_job(
                    cur,
                    job_id=job_id,
                    job_date=target_date,
                    model_version=job_model_version,
                    job_type="manual_generate",
                )

                cur.execute(
                    "SELECT id "
                    "FROM puzzles "
                    "WHERE game_type = %(game_type)s AND date = %(date)s AND published_at IS NULL "
                    "ORDER BY created_at DESC "
                    "LIMIT 1",
                    {"game_type": game_type, "date": target_date},
                )
                existing = cur.fetchone()
                if existing is not None:
                    existing_puzzle_id = str(existing["id"])
                    if not force:
                        _complete_generation_job(
                            cur,
                            job_id=job_id,
                            status="succeeded",
                            logs=json.dumps(
                                {
                                    "gameType": game_type,
                                    "date": target_date.isoformat(),
                                    "action": "existing_reused",
                                    "puzzleId": existing_puzzle_id,
                                    "rankerModelVersion": None,
                                    "artifactRefs": [],
                                }
                            ),
                        )
                        conn.commit()
                        return {
                            "jobId": job_id,
                            "status": "succeeded",
                            "gameType": game_type,
                            "date": target_date.isoformat(),
                            "action": "existing_reused",
                            "puzzleId": existing_puzzle_id,
                            "replacedPuzzleId": None,
                            "rankerModelVersion": None,
                        }

                    cur.execute(
                        "SELECT id FROM puzzles "
                        "WHERE game_type = %(game_type)s AND date = %(date)s AND published_at IS NULL",
                        {"game_type": game_type, "date": target_date},
                    )
                    stale_ids = [str(row["id"]) for row in cur.fetchall() if row.get("id")]
                    if stale_ids:
                        if game_type == "cryptic":
                            cur.execute(
                                "DELETE FROM cryptic_candidates WHERE puzzle_id = ANY(%(puzzle_ids)s)",
                                {"puzzle_ids": stale_ids},
                            )
                        cur.execute(
                            "DELETE FROM puzzles WHERE id = ANY(%(puzzle_ids)s)",
                            {"puzzle_ids": stale_ids},
                        )

                candidate: dict[str, Any] | None = None
                if game_type == "crossword":
                    crossword_lexicon = _load_crossword_csv_lexicon()
                    payload, quality_report, quality_bypassed, quality_attempts_used = _build_governed_crossword_puzzle_payload(
                        target_date=target_date,
                        timezone=timezone,
                        lexicon=crossword_lexicon,
                        seed_value=int(target_date.strftime("%Y%m%d")),
                    )
                elif game_type == "cryptic":
                    cur.execute(
                        "SELECT entries->0->>'answer' AS answer "
                        "FROM puzzles "
                        "WHERE game_type = %(game_type)s AND date >= %(today)s",
                        {"game_type": game_type, "today": datetime.now(ZoneInfo(timezone)).date()},
                    )
                    existing_answers = {row["answer"] for row in cur.fetchall() if row.get("answer")}
                    cryptic_lexicon = _load_cryptic_lexicon()
                    candidate = _select_cryptic_candidate_for_date(
                        cryptic_lexicon,
                        target_date=target_date,
                        excluded_answers=existing_answers,
                    )
                    if candidate is None:
                        raise RuntimeError("cryptic_candidate_pool_exhausted")
                    payload = _build_single_entry_puzzle_payload(
                        game_type=game_type,
                        target_date=target_date,
                        timezone=timezone,
                        answer=candidate["answer"],
                        clue=candidate["clue"],
                        display_name=candidate["display_name"],
                        source_ref=candidate["source_ref"],
                        mechanism=candidate.get("mechanism"),
                        enumeration=candidate.get("enumeration"),
                        wordplay_plan=candidate.get("wordplay_plan"),
                        wordplay_metadata=candidate.get("wordplay_metadata"),
                    )
                else:
                    payload, quality_report = _build_connections_puzzle_payload(
                        target_date=target_date,
                        timezone=timezone,
                        seed_value=int(target_date.strftime("%Y%m%d")),
                    )

                cur.execute(
                    "INSERT INTO puzzles "
                    "(id, date, game_type, title, published_at, timezone, grid, entries, metadata) "
                    "VALUES ("
                    "%(id)s, %(date)s, %(game_type)s, %(title)s, %(published_at)s, %(timezone)s, "
                    "%(grid)s::json, %(entries)s::json, %(metadata)s::json"
                    ")",
                    payload,
                )
                generated_puzzle_id = str(payload["id"])
                generated_artifact_ref = write_json_artifact(
                    artifact_type="puzzles",
                    object_id=generated_puzzle_id,
                    payload=_puzzle_payload_for_artifact(
                        payload=payload,
                        game_type=game_type,
                        job_id=job_id,
                    ),
                )

                if game_type == "cryptic":
                    if candidate is None:
                        raise RuntimeError("cryptic_candidate_unavailable")
                    _insert_cryptic_candidate_rows(
                        cur,
                        job_id=job_id,
                        puzzle_id=generated_puzzle_id,
                        target_date=target_date,
                        source_ref=candidate.get("source_ref", ""),
                        source_type=candidate.get("source_type", ""),
                        answer_key=candidate.get("answer", ""),
                        answer_display=candidate.get("display_name", ""),
                        clue_text=str(candidate.get("clue", "")),
                        mechanism=str(candidate.get("mechanism", "manual") or "manual"),
                        wordplay_plan=str(candidate.get("wordplay_plan", "") or ""),
                        wordplay_metadata=candidate.get("wordplay_metadata", {}),
                    )

                _complete_generation_job(
                    cur,
                    job_id=job_id,
                    status="succeeded",
                    logs=json.dumps(
                        {
                            "gameType": game_type,
                            "date": target_date.isoformat(),
                            "action": "generated",
                            "puzzleId": generated_puzzle_id,
                            "replacedPuzzleId": existing_puzzle_id if force else None,
                            "rankerModelVersion": None,
                            "artifactRefs": [generated_artifact_ref] if generated_artifact_ref else [],
                            "qualityGate": {
                                "attemptsUsed": quality_attempts_used if game_type == "crossword" else None,
                                "bypassed": quality_bypassed if game_type == "crossword" else False,
                                "score": quality_report.get("score") if quality_report else None,
                                "hardFailures": quality_report.get("hardFailures") if quality_report else [],
                            },
                        }
                    ),
                )
            conn.commit()
    except Exception as exc:
        _mark_generation_job_failed(
            job_id=job_id,
            job_date=target_date,
            error_message=f"{type(exc).__name__}: {exc}",
            model_version=job_model_version,
            job_type="manual_generate",
        )
        raise

    if game_type == "crossword" and quality_bypassed and quality_report is not None:
        notify_external_alert(
            event_type="crossword_quality_fallback",
            severity="warning",
            message=f"Manual crossword generation used governance fallback for {target_date.isoformat()}",
            details={
                "jobId": job_id,
                "date": target_date.isoformat(),
                "score": quality_report.get("score"),
                "hardFailures": quality_report.get("hardFailures", []),
                "warnings": quality_report.get("warnings", []),
            },
        )

    return {
        "jobId": job_id,
        "status": "succeeded",
        "gameType": game_type,
        "date": target_date.isoformat(),
        "action": "generated",
        "puzzleId": generated_puzzle_id,
        "replacedPuzzleId": existing_puzzle_id if force else None,
        "rankerModelVersion": None,
        "qualityBypassed": quality_bypassed if game_type == "crossword" else False,
        "qualityScore": quality_report.get("score") if quality_report else None,
        "qualityAttemptsUsed": quality_attempts_used if game_type == "crossword" else None,
    }
