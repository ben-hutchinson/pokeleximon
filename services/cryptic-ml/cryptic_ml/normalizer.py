from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r"[^A-Z0-9]")
SPLIT_RE = re.compile(r"[-_\s]+")

LOCATION_SUFFIXES = {"CITY", "TOWN", "VILLAGE", "AREA"}
SPECIES_HONORIFICS = {"MR", "MRS", "JR", "SR"}


@dataclass(frozen=True)
class Canonicalization:
    answer_tokens: tuple[str, ...]
    normalization_rule: str

    @property
    def answer(self) -> str:
        return " ".join(self.answer_tokens)

    @property
    def answer_key(self) -> str:
        return "".join(self.answer_tokens)

    @property
    def enumeration(self) -> str:
        return ",".join(str(len(t)) for t in self.answer_tokens)


def _clean_token(token: str) -> str:
    return TOKEN_RE.sub("", token.upper())


def split_slug(slug: str) -> list[str]:
    return [t for t in (_clean_token(tok) for tok in SPLIT_RE.split(slug)) if t]


def _is_noisy(source_type: str, tokens: list[str]) -> bool:
    if not tokens:
        return True

    # Exclude machine code-like payloads that generate poor clues.
    if source_type == "item" and len(tokens) >= 2 and tokens[0] == "DYNAMAX" and tokens[1] == "CRYSTAL":
        return True

    if source_type == "item" and any(any(ch.isdigit() for ch in t) for t in tokens):
        return True

    if len("".join(tokens)) < 4:
        return True

    return False


def canonicalize(source_type: str, source_slug: str) -> Canonicalization | None:
    tokens = split_slug(source_slug)
    if _is_noisy(source_type, tokens):
        return None

    rule = "identity"

    if source_type in {"location", "location-area"}:
        trimmed = list(tokens)
        while len(trimmed) > 1 and trimmed[-1] in LOCATION_SUFFIXES:
            trimmed.pop()
            rule = "drop_location_suffix"
        tokens = trimmed

    if source_type == "pokemon-species" and len(tokens) > 1 and tokens[0] in SPECIES_HONORIFICS:
        # Explicitly preserve e.g. MR MIME.
        rule = "preserve_species_honorific"

    if not tokens or len("".join(tokens)) < 4:
        return None

    return Canonicalization(answer_tokens=tuple(tokens), normalization_rule=rule)
