from __future__ import annotations

from html import unescape
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, urlparse

import requests


TOKEN_RE = re.compile(r"[^A-Z0-9]")
WHITESPACE_RE = re.compile(r"\s+")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")
JAPANESE_PAREN_RE = re.compile(r"\([^)]*\bJapanese:\s*[^)]*\)", re.IGNORECASE)
JAPANESE_LABEL_RE = re.compile(r"(?i)\bJapanese:\s*[^.;:!?)]*")
POKEAPI_REF_RE = re.compile(r"(?i)\bPok[eé]?API\b[^.;:!?)]*")
SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1>")
BLOCK_TAG_RE = re.compile(
    r"(?i)</?(?:p|div|section|article|main|header|footer|aside|tr|table|thead|tbody|tfoot|h[1-6]|li|ul|ol|td|th|dl|dt|dd|br|hr)[^>]*>"
)
HTML_TAG_RE = re.compile(r"<[^>]+>")
WORD_RE = re.compile(r"[A-Z0-9]+", re.IGNORECASE)

SOURCE_REPLACEMENT = {
    "pokemon-species": "this Pokemon",
    "move": "this move",
    "ability": "this ability",
    "item": "this item",
    "location": "this location",
    "location-area": "this location",
    "type": "this type",
}

LOW_QUALITY_PATTERNS = (
    re.compile(r"(?i)redirects here"),
    re.compile(r"(?i)this article is about"),
    re.compile(r"(?i)may refer to"),
    re.compile(r"(?i)disambiguation"),
    re.compile(r"(?i)^for the"),
    re.compile(r"(?i)if you were looking for"),
    re.compile(r"(?i)for a list of"),
    re.compile(r"(?i)has several referrals"),
)

GENERIC_CLUE_PATTERNS = (
    re.compile(r"(?i)^this (?:pok[eé]mon|item|move|ability|type|location)\b"),
    re.compile(r"(?i)^location:\s*region\s"),
    re.compile(r"(?i)^type entry"),
    re.compile(r"(?i)^ability entry"),
    re.compile(r"(?i)^location entry"),
    re.compile(r"(?i)^.* item \(.*#\d+\)\.?$"),
    re.compile(r"(?i)^pok[eé]mon term from the csv lexicon\.?$"),
    re.compile(r"(?i)\bcatalog clue token\b"),
    re.compile(r"(?i)\brecord token\b"),
    re.compile(r"(?i)\bpok[eé]mon term from pokeapi data\b"),
    re.compile(r"(?i)^pok[eé]dex entry for #\d+\b"),
    re.compile(r"(?i)^details and added effects for the pok[eé]mon attack\.?$"),
    re.compile(r"(?i)including added effects and where to find it\.?$"),
    re.compile(r"(?i)and the list of pok[eé]mon that learn it\.?$"),
    re.compile(r"(?i)^this pok[eé]mon is an? [a-z0-9 /-]+ type pok[eé]mon introduced in generation \d+\.?$"),
    re.compile(r"(?i)^this type(?:'s)? strengths and weaknesses\b"),
    re.compile(r"(?i)^additional artwork\.?$"),
)

GENERIC_META_DESCRIPTION_PATTERNS = (
    re.compile(r"(?i)^pok[eé]dex entry for #\d+\b"),
    re.compile(r"(?i)\bcontaining stats, moves learned, evolution chain, location and more!?$"),
    re.compile(r"(?i)including added effects and where to find it\.?$"),
    re.compile(r"(?i)and the list of pok[eé]mon that learn it\.?$"),
    re.compile(r"(?i)^details and added effects for the pok[eé]mon attack\.?$"),
    re.compile(r"(?i)^the strengths and weaknesses of (?:the )?.+ type\b"),
    re.compile(r"(?i)\bpok[eé]dex:.*\bstats\b.*\bmoves\b"),
    re.compile(r"(?i)\battack\s*&\s*move listings for pok[eé]mon\b"),
    re.compile(r"(?i)\bdetails all stats for each move and each pok[eé]mon that can learn it\b"),
    re.compile(r"(?i)\bpok[eé]mon (?:items|abilities|moves) \| pok[eé]mon database\b"),
)

NOISY_LINE_PATTERNS = (
    re.compile(r"(?i)^image:?"),
    re.compile(r"(?i)^picture$"),
    re.compile(r"(?i)^contents$"),
    re.compile(r"(?i)^info$"),
    re.compile(r"(?i)^general$"),
    re.compile(r"(?i)^normal$"),
    re.compile(r"(?i)^shiny$"),
    re.compile(r"(?i)^standard$"),
    re.compile(r"(?i)^galarian$"),
    re.compile(r"(?i)^other languages$"),
    re.compile(r"(?i)^locations?$"),
    re.compile(r"(?i)^attacks?$"),
    re.compile(r"(?i)^sprites$"),
    re.compile(r"(?i)^language$"),
    re.compile(r"(?i)^map$"),
    re.compile(r"(?i)^select$"),
    re.compile(r"(?i)^pok[eé]mon that can have .+$"),
    re.compile(r"(?i)^(?:#|national:)\s*[\d-]+$"),
    re.compile(r"(?i)^[\d\s./%,'()#:-]+$"),
    re.compile(r"(?i)^additional artwork\.?$"),
    re.compile(r"(?i)^game locations\b"),
    re.compile(r"(?i)^details all stats for each move and each pok[eé]mon that can learn it\.?$"),
)

SECTION_LABEL_PATTERNS = (
    re.compile(r"(?i)^game descriptions?$"),
    re.compile(r"(?i)^battle effect$"),
    re.compile(r"(?i)^in-depth effect$"),
    re.compile(r"(?i)^effects?$"),
    re.compile(r"(?i)^flavo[u]?r text$"),
    re.compile(r"(?i)^classification$"),
    re.compile(r"(?i)^species$"),
    re.compile(r"(?i)^pok[eé]dex entries$"),
    re.compile(r"(?i)^shopping details$"),
    re.compile(r"(?i)^event distributions$"),
    re.compile(r"(?i)^base stats$"),
    re.compile(r"(?i)^moves learned$"),
    re.compile(r"(?i)^weakness(?:es)?$"),
)

MOJIBAKE_REPLACEMENTS = {
    "Pok√©mon": "Pokémon",
    "PokÃ©mon": "Pokémon",
    "‚Äô": "’",
    "‚Äú": "“",
    "‚Äù": "”",
    "‚Äì": "–",
    "‚Äî": "—",
    "Ã—": "×",
    "√ó": "ó",
    "√©": "é",
}


@dataclass
class FetchResult:
    status: str
    provider: str
    url: str
    extract: str | None = None
    error: str | None = None


def clean_text(value: str) -> str:
    text = unescape(str(value or "")).replace("\n", " ").replace("\f", " ")
    for bad, good in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(bad, good)
    text = re.sub(r"(?i)pok[ée]mon", "Pokémon", text)
    return WHITESPACE_RE.sub(" ", text).strip()


def word_count(value: str) -> int:
    return len(WORD_RE.findall(clean_text(value)))


def as_sentence(value: str) -> str:
    text = clean_text(value)
    if text and text[-1] not in ".!?":
        text += "."
    return text


def normalize_answer(value: str) -> str:
    return TOKEN_RE.sub("", str(value).upper())


def clue_key(clue: str) -> str:
    return WHITESPACE_RE.sub(" ", str(clue).strip()).upper()


def answer_parts(display_answer: str) -> list[str]:
    return [part for part in str(display_answer).upper().split(" ") if part]


def answer_fragments(display_answer: str) -> list[str]:
    parts = answer_parts(display_answer)
    fragments: set[str] = set()
    for part in parts:
        if len(part) >= 2:
            fragments.add(part)
    joined = "".join(parts)
    spaced = " ".join(parts)
    hyphened = "-".join(parts)
    for value in (joined, spaced, hyphened):
        if len(value.replace(" ", "").replace("-", "")) >= 2:
            fragments.add(value)
    return sorted(fragments, key=len, reverse=True)


def clue_contains_answer_fragment(clue: str, display_answer: str) -> bool:
    for fragment in answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        if pattern.search(clue):
            return True
    return False


def is_low_quality_clue(clue: str) -> bool:
    text = clean_text(clue)
    if not text:
        return True
    if len(text) < 8:
        return True
    if word_count(text) < 2:
        return True
    return any(pattern.search(text) for pattern in LOW_QUALITY_PATTERNS)


def is_generic_clue(clue: str) -> bool:
    text = clean_text(clue)
    if not text:
        return True
    return any(pattern.search(text) for pattern in GENERIC_CLUE_PATTERNS)


def strip_answer_fragments(clue: str, display_answer: str, source_type: str) -> str:
    out = clue
    replacement = SOURCE_REPLACEMENT.get(source_type, "this entry")
    for fragment in answer_fragments(display_answer):
        pattern = re.compile(rf"(?i)(?<![A-Z0-9]){re.escape(fragment)}(?![A-Z0-9])")
        out = pattern.sub(replacement, out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    return as_sentence(out)


def strip_disallowed_metadata(clue: str) -> str:
    out = clean_text(clue)
    if not out:
        return ""
    out = JAPANESE_PAREN_RE.sub("", out)
    out = JAPANESE_LABEL_RE.sub("", out)
    out = POKEAPI_REF_RE.sub("", out)
    out = re.sub(r"\([^)]*\)", "", out)
    out = re.sub(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]+", "", out)
    out = out.replace("(", "").replace(")", "")
    out = re.sub(r"\(\s*\)", "", out)
    out = re.sub(r"\s{2,}", " ", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r"\s*-\s*", " ", out)
    out = out.strip(" ;,")
    return as_sentence(out)


def salvage_placeholder_surface(clue: str, source_type: str) -> str:
    text = clean_text(clue)
    if not text:
        return ""
    if source_type == "pokemon-species":
        match = re.match(r"(?i)^this pok[eé]mon is an? [a-z0-9 /-]+ type pok[eé]mon (?P<tail>.+)$", text)
        if match:
            tail = clean_text(match.group("tail")).strip(" ,.;:")
            if not tail or re.match(r"(?i)^introduced in generation\s+\d+\b", tail):
                return ""
            if tail.lower().startswith("that "):
                tail = tail[5:]
            elif tail.lower().startswith("which "):
                tail = tail[6:]
            return as_sentence(tail)
    return text


def extract_candidate_sentences(extract: str, max_sentences: int = 5) -> list[str]:
    text = clean_text(extract)
    if not text:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for sentence in SENTENCE_SPLIT_RE.split(text):
        cleaned = as_sentence(sentence)
        key = clue_key(cleaned)
        if not cleaned or key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= max_sentences:
            break
    return out


def sanitize_external_candidate(candidate: str, answer_display: str, source_type: str) -> str | None:
    cleaned = strip_answer_fragments(candidate, answer_display, source_type)
    cleaned = strip_disallowed_metadata(cleaned)
    cleaned = salvage_placeholder_surface(cleaned, source_type)
    if not cleaned:
        return None
    if is_low_quality_clue(cleaned):
        return None
    if is_generic_clue(cleaned):
        return None
    if clue_contains_answer_fragment(cleaned, answer_display):
        return None
    return cleaned


def refine_provider_extract(extract: str, answer_display: str) -> str:
    text = clean_text(extract)
    if not text:
        return ""
    answer_tokens = [fragment.lower() for fragment in answer_fragments(answer_display) if len(fragment) >= 3]
    best_index = -1
    for token in answer_tokens:
        idx = text.lower().rfind(token)
        if idx > best_index:
            best_index = idx
    if best_index > 0 and len(text) - best_index >= 32:
        text = text[best_index:]
    return clean_text(text)

def _html_paragraphs(html: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", html):
        text = clean_text(re.sub(r"<[^>]+>", " ", str(match or "")))
        if not text:
            continue
        key = clue_key(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
    return out


def _html_lines(html: str) -> list[str]:
    text = SCRIPT_STYLE_RE.sub(" ", html)
    text = BLOCK_TAG_RE.sub("\n", text)
    text = HTML_TAG_RE.sub(" ", text)
    text = unescape(text)
    lines: list[str] = []
    seen: set[str] = set()
    for raw_line in text.splitlines():
        cleaned = clean_text(raw_line)
        if not cleaned:
            continue
        key = clue_key(cleaned)
        if key in seen:
            continue
        seen.add(key)
        lines.append(cleaned)
    return lines


def _label_key(value: str) -> str:
    return clean_text(value).lower().rstrip(":")


def _is_noisy_line(value: str) -> bool:
    text = clean_text(value)
    if not text:
        return True
    if len(text) <= 2:
        return True
    return any(pattern.search(text) for pattern in NOISY_LINE_PATTERNS)


def _looks_like_section_heading(value: str) -> bool:
    text = clean_text(value)
    if not text:
        return False
    return any(pattern.search(text.rstrip(":")) for pattern in SECTION_LABEL_PATTERNS)


def _extract_labeled_lines(lines: list[str], labels: list[str], max_matches: int = 2, max_scan: int = 12) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    label_keys = {_label_key(label) for label in labels}
    for idx, line in enumerate(lines):
        line_key = _label_key(line)
        matched_label = line_key if line_key in label_keys else None
        inline_value = ""
        if matched_label is None and ":" in line:
            left, right = line.split(":", 1)
            if _label_key(left) in label_keys:
                matched_label = _label_key(left)
                inline_value = clean_text(right)
        if matched_label is None:
            continue
        if inline_value and not _is_noisy_line(inline_value):
            key = clue_key(inline_value)
            if key not in seen:
                seen.add(key)
                out.append(inline_value)
        for candidate in lines[idx + 1 : idx + 1 + max_scan]:
            if _looks_like_section_heading(candidate):
                break
            if _is_noisy_line(candidate):
                continue
            key = clue_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
            break
        if len(out) >= max_matches:
            break
    return out


def _extract_labeled_lines_matching(
    lines: list[str],
    labels: list[str],
    include_patterns: list[re.Pattern[str]],
    *,
    max_matches: int = 1,
    max_scan: int = 20,
) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    label_keys = {_label_key(label) for label in labels}
    for idx, line in enumerate(lines):
        if _label_key(line) not in label_keys:
            continue
        for candidate in lines[idx + 1 : idx + 1 + max_scan]:
            if _looks_like_section_heading(candidate):
                continue
            if _is_noisy_line(candidate):
                continue
            if include_patterns and not any(pattern.search(candidate) for pattern in include_patterns):
                continue
            key = clue_key(candidate)
            if key in seen:
                continue
            seen.add(key)
            out.append(candidate)
            break
        if len(out) >= max_matches:
            break
    return out


def _extract_heading_paragraphs(html: str, headings: list[str], max_matches: int = 2) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    heading_pattern = "|".join(re.escape(heading) for heading in headings)
    pattern = re.compile(
        rf"(?is)<h[1-6][^>]*>\s*(?:{heading_pattern})\s*</h[1-6]>\s*(?:<(?!h[1-6])[^>]+>\s*)*<p[^>]*>(.*?)</p>"
    )
    for match in pattern.findall(html):
        text = clean_text(re.sub(r"<[^>]+>", " ", str(match or "")))
        if not text:
            continue
        key = clue_key(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= max_matches:
            break
    return out


def _extract_table_row_values(html: str, labels: list[str], max_matches: int = 2) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for label in labels:
        pattern = re.compile(
            rf"(?is)<(?:th|td)[^>]*>\s*{re.escape(label)}\s*:?\s*</(?:th|td)>\s*<(?:td|th)[^>]*>(.*?)</(?:td|th)>"
        )
        for match in pattern.findall(html):
            text = clean_text(re.sub(r"<[^>]+>", " ", str(match or "")))
            if not text or _is_noisy_line(text):
                continue
            key = clue_key(text)
            if key in seen:
                continue
            seen.add(key)
            out.append(text)
            if len(out) >= max_matches:
                return out
    return out


def _combine_extract_snippets(snippets: list[str], max_snippets: int = 4) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for snippet in snippets:
        text = clean_text(snippet)
        if not text:
            continue
        if any(pattern.search(text) for pattern in GENERIC_META_DESCRIPTION_PATTERNS):
            continue
        key = clue_key(text)
        if key in seen:
            continue
        seen.add(key)
        out.append(as_sentence(text))
        if len(out) >= max_snippets:
            break
    return " ".join(out).strip()


def _extract_pokemondb_body_text(html: str, url: str) -> str:
    lines = _html_lines(html)
    paragraphs = _html_paragraphs(html)
    path = urlparse(url).path.lower()
    snippets: list[str] = []
    if "/pokedex/" in path:
        snippets.extend(_extract_table_row_values(html, ["Species"]))
        snippets.extend(
            _extract_labeled_lines_matching(
                lines,
                ["Species", "Pokédex entries", "Pokedex entries"],
                [re.compile(r"(?i)Pok[eé]mon"), re.compile(r"[.!?]$")],
            )
        )
    elif "/move/" in path:
        snippets.extend(_extract_heading_paragraphs(html, ["Effect", "Effects"]))
        snippets.extend(_extract_labeled_lines(lines, ["Effects", "Effect", "Battle Effect", "Game descriptions"]))
    elif "/ability/" in path:
        snippets.extend(_extract_heading_paragraphs(html, ["Effect", "Effects"]))
        snippets.extend(_extract_labeled_lines(lines, ["Effects", "Effect", "Game descriptions"]))
    elif "/item/" in path:
        snippets.extend(_extract_heading_paragraphs(html, ["Effect", "Effects"]))
        snippets.extend(_extract_labeled_lines(lines, ["Effects", "Effect", "Game descriptions"]))
    elif "/type/" in path:
        snippets.extend(_extract_labeled_lines(lines, ["Pokédex entries", "Pokedex entries"]))
    snippets.extend(paragraphs[:3])
    return _combine_extract_snippets(snippets)


def _extract_serebii_body_text(html: str, url: str) -> str:
    lines = _html_lines(html)
    path = urlparse(url).path.lower()
    snippets: list[str] = []
    if "/pokedex-" in path:
        snippets.extend(_extract_table_row_values(html, ["Classification"]))
        snippets.extend(
            _extract_labeled_lines_matching(
                lines,
                ["Classification"],
                [re.compile(r"(?i)Pok[eé]mon")],
            )
        )
        snippets.extend(
            _extract_labeled_lines_matching(
                lines,
                ["Flavor Text", "Flavour Text"],
                [re.compile(r"[.!?]$")],
            )
        )
    elif "/attackdex" in path:
        snippets.extend(_extract_labeled_lines(lines, ["Battle Effect", "In-Depth Effect", "Game's Text"]))
    elif "/abilitydex/" in path:
        snippets.extend(_extract_labeled_lines(lines, ["Game's Text", "In-Depth Effect", "Effect"]))
    elif "/itemdex/" in path:
        snippets.extend(_extract_labeled_lines(lines, ["In-Depth Effect", "Game's Text", "Flavour Text", "Flavor Text"]))
    return _combine_extract_snippets(snippets)


def _fetch_html_description(
    url: str,
    timeout_seconds: float,
    provider: str,
    *,
    body_extractor: Any | None = None,
) -> FetchResult:
    try:
        response = requests.get(
            url,
            timeout=timeout_seconds,
            headers={"User-Agent": "pokeleximon-clue-agents/0.1"},
        )
        response.raise_for_status()
        html = response.text
    except requests.Timeout:
        return FetchResult(status="timeout", provider=provider, url=url, error="timeout")
    except requests.ConnectionError as exc:
        return FetchResult(status="connection_error", provider=provider, url=url, error=str(exc))
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "http"
        return FetchResult(status=f"http_{code}", provider=provider, url=url, error=str(exc))
    except requests.RequestException as exc:
        return FetchResult(status="request_error", provider=provider, url=url, error=str(exc))

    meta_match = re.search(
        r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if meta_match:
        extract = clean_text(meta_match.group(1))
        if extract and not any(pattern.search(extract) for pattern in GENERIC_META_DESCRIPTION_PATTERNS):
            return FetchResult(status="ok", provider=provider, url=url, extract=extract)

    if callable(body_extractor):
        extract = clean_text(body_extractor(html, url))
        if extract:
            return FetchResult(status="ok", provider=provider, url=url, extract=extract)

    paragraph_extract = _combine_extract_snippets(_html_paragraphs(html))
    if paragraph_extract:
        return FetchResult(status="ok", provider=provider, url=url, extract=paragraph_extract)
    return FetchResult(status="not_found", provider=provider, url=url)


def slug_variants(answer_display: str, canonical_slug: str | None) -> list[str]:
    seen: set[str] = set()
    variants: list[str] = []
    for seed in (canonical_slug, answer_display):
        raw = str(seed or "").strip().lower().replace("_", "-")
        raw = raw.replace("é", "e")
        parts = re.findall(r"[a-z0-9]+", raw)
        if not parts:
            continue
        for variant in ("-".join(parts), "".join(parts)):
            if variant and variant not in seen:
                seen.add(variant)
                variants.append(variant)
    return variants or ["".join(part.lower() for part in answer_display.split())]


def slug_candidate(answer_display: str, canonical_slug: str | None) -> str:
    return slug_variants(answer_display, canonical_slug)[0]


def _dedupe_urls(urls: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def serebii_url_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    variants = slug_variants(answer_display, canonical_slug)
    compact = [variant for variant in variants if "-" not in variant]
    hyphenated = [variant for variant in variants if "-" in variant]
    search_query = quote_plus(str(canonical_slug or answer_display).strip())
    urls: list[str] = []
    if source_type == "move":
        urls.extend(f"https://www.serebii.net/attackdex-sv/{slug}.shtml" for slug in compact + hyphenated)
    elif source_type == "ability":
        urls.extend(f"https://www.serebii.net/abilitydex/{slug}.shtml" for slug in compact + hyphenated)
    elif source_type == "item":
        urls.extend(f"https://www.serebii.net/itemdex/{slug}.shtml" for slug in compact + hyphenated)
    elif source_type == "pokemon-species":
        for slug in hyphenated + compact:
            urls.append(f"https://www.serebii.net/pokedex-sv/{slug}")
            urls.append(f"https://www.serebii.net/pokedex-sv/{slug}/")
    urls.append(f"https://www.serebii.net/search.shtml?query={search_query}")
    return _dedupe_urls(urls)


def pokemondb_url_candidates(answer_display: str, source_type: str, canonical_slug: str | None) -> list[str]:
    variants = slug_variants(answer_display, canonical_slug)
    hyphenated = [variant for variant in variants if "-" in variant]
    compact = [variant for variant in variants if "-" not in variant]
    query = quote_plus(str(canonical_slug or answer_display).strip())
    urls: list[str] = []
    if source_type == "pokemon-species":
        urls.extend(f"https://pokemondb.net/pokedex/{slug}" for slug in hyphenated + compact)
    elif source_type == "move":
        urls.extend(f"https://pokemondb.net/move/{slug}" for slug in hyphenated + compact)
    elif source_type == "ability":
        urls.extend(f"https://pokemondb.net/ability/{slug}" for slug in hyphenated + compact)
    elif source_type == "item":
        urls.extend(f"https://pokemondb.net/item/{slug}" for slug in hyphenated + compact)
    elif source_type == "type":
        urls.extend(f"https://pokemondb.net/type/{slug}" for slug in hyphenated + compact)
    urls.append(f"https://pokemondb.net/search?q={query}")
    return _dedupe_urls(urls)


def fetch_serebii_description(url: str, timeout_seconds: float) -> FetchResult:
    return _fetch_html_description(url, timeout_seconds, "serebii", body_extractor=_extract_serebii_body_text)


def fetch_pokemondb_description(url: str, timeout_seconds: float) -> FetchResult:
    return _fetch_html_description(url, timeout_seconds, "pokemondb", body_extractor=_extract_pokemondb_body_text)
