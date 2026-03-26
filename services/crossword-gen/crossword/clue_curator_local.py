from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from crossword.clue_fact_extractor import extract_clue_facts
from crossword.clue_surface_generator import generate_curated_payload

CURATOR_VERSION = "local-curator-v23"


def cache_path(cache_dir: Path, answer_key: str) -> Path:
    return cache_dir / f"{str(answer_key or '').upper()}.json"


def load_cached_response(cache_dir: Path, answer_key: str) -> dict[str, Any] | None:
    path = cache_path(cache_dir, answer_key)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def curate_clues_locally(
    *,
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
    cache_dir: Path,
) -> dict[str, Any]:
    answer_key = str(answer_row.get("answerKey") or "").upper()
    evidence_revision = (evidence or {}).get("pageRevisionId")
    evidence_pass_mode = str((evidence or {}).get("passMode") or "first_pass")
    cached = load_cached_response(cache_dir, answer_key)
    if (
        cached is not None
        and cached.get("evidenceRevisionId") == evidence_revision
        and cached.get("evidencePassMode") == evidence_pass_mode
        and cached.get("curatorVersion") == CURATOR_VERSION
    ):
        return cached

    fact_profile = extract_clue_facts(answer_row=answer_row, evidence=evidence, structured_facts=structured_facts)
    response = generate_curated_payload(source_type=str(fact_profile.get("sourceType") or ""), facts=list(fact_profile.get("facts") or []))
    payload = {
        "answerKey": answer_key,
        "status": "ok" if response.get("crossword_candidates") else "no_candidates",
        "schemaValid": True,
        "mode": "local",
        "curatorVersion": CURATOR_VERSION,
        "evidenceRevisionId": evidence_revision,
        "evidencePassMode": evidence_pass_mode,
        "response": response,
        "updatedAt": int(time.time()),
    }
    path = cache_path(cache_dir, answer_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return payload
