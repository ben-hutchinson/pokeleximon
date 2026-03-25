from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import requests


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4.1-mini"


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


def _response_schema() -> dict[str, Any]:
    return {
        "name": "clue_curator_response",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "fact_nuggets": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "text": {"type": "string"},
                            "evidence_ref": {"type": "string"},
                            "specificity": {"type": "number"},
                        },
                        "required": ["text", "evidence_ref", "specificity"],
                    },
                },
                "crossword_candidates": {
                    "type": "array",
                    "minItems": 3,
                    "maxItems": 12,
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "text": {"type": "string"},
                            "evidence_ref": {"type": "string"},
                            "mystery_score": {"type": "number"},
                            "specificity_score": {"type": "number"},
                            "style": {"type": "string"},
                        },
                        "required": ["text", "evidence_ref", "mystery_score", "specificity_score", "style"],
                    },
                },
                "cryptic_definition_seeds": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 6,
                    "items": {"type": "string"},
                },
                "connections_descriptors": {
                    "type": "array",
                    "minItems": 2,
                    "maxItems": 8,
                    "items": {"type": "string"},
                },
                "risk_flags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "confidence": {"type": "number"},
            },
            "required": [
                "fact_nuggets",
                "crossword_candidates",
                "cryptic_definition_seeds",
                "connections_descriptors",
                "risk_flags",
                "confidence",
            ],
        },
    }


def _prompt_payload(
    *,
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
) -> dict[str, Any]:
    return {
        "answer": {
            "answerKey": answer_row.get("answerKey"),
            "answerDisplay": answer_row.get("answerDisplay"),
            "sourceType": answer_row.get("sourceType"),
            "sourceRef": answer_row.get("sourceRef"),
        },
        "bulbapediaEvidence": {
            "pageTitle": (evidence or {}).get("pageTitle"),
            "pageUrl": (evidence or {}).get("pageUrl"),
            "leadText": (evidence or {}).get("leadText"),
            "sections": (evidence or {}).get("sections", []),
        },
        "structuredFacts": structured_facts,
        "instructions": {
            "goal": "Generate indirect but solvable clue candidates for a Pokemon crossword game.",
            "constraints": [
                "Do not quote source text verbatim.",
                "Avoid answer leakage or close paraphrase leakage.",
                "Make crossword clues short, mysterious, and specific.",
                "Use evidence_ref values of 'lead' or exact section titles from the evidence payload.",
                "Prefer clue ideas that make the solver think rather than restating category labels.",
                "Cryptic definition seeds must be short noun phrases, not full sentences.",
                "Connections descriptors must be concise group titles, 2-6 words long.",
            ],
        },
    }


def _developer_prompt() -> str:
    return (
        "You are an editorial clue curator for a Pokemon-themed crossword app. "
        "Read the provided evidence, extract clue-worthy facts, and write original clue candidates. "
        "Return valid JSON only, following the provided schema exactly. "
        "Never copy source text verbatim. "
        "Prefer clues that are specific, indirect, and solvable by a knowledgeable player."
    )


def _validate_schema(payload: dict[str, Any]) -> tuple[bool, list[str]]:
    issues: list[str] = []
    required = [
        "fact_nuggets",
        "crossword_candidates",
        "cryptic_definition_seeds",
        "connections_descriptors",
        "risk_flags",
        "confidence",
    ]
    for key in required:
        if key not in payload:
            issues.append(f"missing_{key}")
    if issues:
        return False, issues
    if not isinstance(payload.get("fact_nuggets"), list):
        issues.append("invalid_fact_nuggets")
    if not isinstance(payload.get("crossword_candidates"), list):
        issues.append("invalid_crossword_candidates")
    if not isinstance(payload.get("cryptic_definition_seeds"), list):
        issues.append("invalid_cryptic_definition_seeds")
    if not isinstance(payload.get("connections_descriptors"), list):
        issues.append("invalid_connections_descriptors")
    if not isinstance(payload.get("risk_flags"), list):
        issues.append("invalid_risk_flags")
    confidence = payload.get("confidence")
    if not isinstance(confidence, (int, float)):
        issues.append("invalid_confidence")
    return len(issues) == 0, issues


def _extract_message_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


def call_curator(
    *,
    answer_row: dict[str, Any],
    evidence: dict[str, Any] | None,
    structured_facts: dict[str, Any],
    cache_dir: Path,
    cache_only: bool = False,
    timeout_seconds: float = 30.0,
    model: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    answer_key = str(answer_row.get("answerKey") or "").upper()
    cached = load_cached_response(cache_dir, answer_key)
    evidence_revision = (evidence or {}).get("pageRevisionId")
    if cached is not None and cached.get("evidenceRevisionId") == evidence_revision:
        return cached
    if cache_only:
        return {
            "answerKey": answer_key,
            "status": "cache_miss",
            "schemaValid": False,
            "errors": ["cache_miss"],
        }

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return {
            "answerKey": answer_key,
            "status": "api_key_missing",
            "schemaValid": False,
            "errors": ["api_key_missing"],
        }

    payload = {
        "model": model or os.getenv("OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        "messages": [
            {"role": "developer", "content": _developer_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    _prompt_payload(answer_row=answer_row, evidence=evidence, structured_facts=structured_facts),
                    ensure_ascii=False,
                ),
            },
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": _response_schema(),
        },
    }
    request_url = (base_url or os.getenv("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL)).rstrip("/") + "/chat/completions"
    try:
        response = requests.post(
            request_url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json()
    except (requests.RequestException, ValueError) as exc:
        response_body = ""
        if isinstance(exc, requests.RequestException) and exc.response is not None:
            try:
                response_body = exc.response.text[:4000]
            except Exception:
                response_body = ""
        return {
            "answerKey": answer_key,
            "status": "request_error",
            "schemaValid": False,
            "errors": [str(exc)] + ([response_body] if response_body else []),
        }

    content = _extract_message_content(raw)
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {
            "answerKey": answer_key,
            "status": "invalid_json",
            "schemaValid": False,
            "errors": ["invalid_json"],
            "rawContent": content,
        }

    ok, issues = _validate_schema(parsed if isinstance(parsed, dict) else {})
    cached_payload = {
        "answerKey": answer_key,
        "status": "ok" if ok else "invalid_schema",
        "schemaValid": ok,
        "errors": issues,
        "model": payload["model"],
        "evidenceRevisionId": evidence_revision,
        "response": parsed if isinstance(parsed, dict) else {},
        "updatedAt": int(time.time()),
    }
    path = cache_path(cache_dir, answer_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cached_payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return cached_payload
