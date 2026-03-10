from __future__ import annotations

from typing import Any


def _entry_enumeration(entry: dict[str, Any]) -> str:
    enumeration = str(entry.get("enumeration") or "").strip()
    if enumeration:
        return enumeration
    length = int(entry.get("length") or 0)
    return str(length) if length > 0 else "?"


def build_text_export_payload(puzzle: dict[str, Any]) -> dict[str, Any]:
    entries = puzzle.get("entries") if isinstance(puzzle.get("entries"), list) else []
    grid = puzzle.get("grid") if isinstance(puzzle.get("grid"), dict) else {}
    metadata = puzzle.get("metadata") if isinstance(puzzle.get("metadata"), dict) else {}

    width = int(grid.get("width") or 0)
    height = int(grid.get("height") or 0)
    cells = grid.get("cells") if isinstance(grid.get("cells"), list) else []
    cell_map: dict[tuple[int, int], dict[str, Any]] = {}
    for cell in cells:
        if not isinstance(cell, dict):
            continue
        x = int(cell.get("x") or 0)
        y = int(cell.get("y") or 0)
        cell_map[(x, y)] = cell

    rows: list[str] = []
    for y in range(max(0, height)):
        row_chars = []
        for x in range(max(0, width)):
            cell = cell_map.get((x, y), {})
            is_block = bool(cell.get("isBlock"))
            row_chars.append("#" if is_block else ".")
        rows.append("".join(row_chars))

    export_entries: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        export_entries.append(
            {
                "id": str(entry.get("id") or ""),
                "number": int(entry.get("number") or 0),
                "direction": str(entry.get("direction") or ""),
                "clue": str(entry.get("clue") or "").strip(),
                "length": int(entry.get("length") or 0),
                "enumeration": _entry_enumeration(entry),
                "cells": entry.get("cells") if isinstance(entry.get("cells"), list) else [],
            }
        )

    return {
        "id": str(puzzle.get("id") or ""),
        "date": str(puzzle.get("date") or ""),
        "gameType": str(puzzle.get("gameType") or ""),
        "title": str(puzzle.get("title") or ""),
        "timezone": str(puzzle.get("timezone") or ""),
        "metadata": {
            "difficulty": str(metadata.get("difficulty") or ""),
            "themeTags": metadata.get("themeTags") if isinstance(metadata.get("themeTags"), list) else [],
            "contestMode": bool(metadata.get("contestMode")),
            "byline": metadata.get("byline"),
            "constructor": metadata.get("constructor"),
            "editor": metadata.get("editor"),
            "notes": metadata.get("notes"),
        },
        "grid": {
            "width": width,
            "height": height,
            "rows": rows,
        },
        "entries": export_entries,
        "redactedAnswers": True,
    }


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap_line(text: str, max_chars: int = 92) -> list[str]:
    stripped = " ".join(text.split())
    if len(stripped) <= max_chars:
        return [stripped]
    words = stripped.split(" ")
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
    if current:
        lines.append(current)
    return lines


def build_pdf_export_bytes(payload: dict[str, Any]) -> bytes:
    game_type = str(payload.get("gameType") or "")
    date = str(payload.get("date") or "")
    title = str(payload.get("title") or "Puzzle Export")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    entries = payload.get("entries") if isinstance(payload.get("entries"), list) else []
    grid = payload.get("grid") if isinstance(payload.get("grid"), dict) else {}

    lines: list[str] = [
        title,
        f"Game: {game_type}   Date: {date}",
        f"Difficulty: {metadata.get('difficulty') or 'n/a'}",
        "Answers are intentionally omitted in this export.",
        "",
    ]

    if game_type == "crossword":
        width = int(grid.get("width") or 0)
        height = int(grid.get("height") or 0)
        lines.append(f"Grid: {width}x{height}")
        rows = grid.get("rows") if isinstance(grid.get("rows"), list) else []
        for row in rows[:20]:
            lines.append(f"  {row}")
        lines.append("")
        across = [entry for entry in entries if isinstance(entry, dict) and entry.get("direction") == "across"]
        down = [entry for entry in entries if isinstance(entry, dict) and entry.get("direction") == "down"]
        lines.append("Across")
        for entry in across:
            lines.extend(
                _wrap_line(
                    f"{entry.get('number')}. {entry.get('clue') or 'Clue unavailable.'} ({entry.get('enumeration') or '?'})"
                )
            )
        lines.append("")
        lines.append("Down")
        for entry in down:
            lines.extend(
                _wrap_line(
                    f"{entry.get('number')}. {entry.get('clue') or 'Clue unavailable.'} ({entry.get('enumeration') or '?'})"
                )
            )
    else:
        lines.append("Cryptic clue")
        for entry in entries[:1]:
            if not isinstance(entry, dict):
                continue
            lines.extend(_wrap_line(str(entry.get("clue") or "Clue unavailable.")))
            lines.append(f"Enumeration: ({entry.get('enumeration') or '?'})")
            break
        lines.append("")
        lines.append("Explanation and answer omitted in unsolved export.")

    lines_per_page = 48
    pages: list[list[str]] = []
    current_page: list[str] = []
    for line in lines:
        current_page.append(line)
        if len(current_page) >= lines_per_page:
            pages.append(current_page)
            current_page = []
    if current_page:
        pages.append(current_page)
    if not pages:
        pages = [["Puzzle export unavailable."]]

    objects: list[bytes] = []

    def add_object(data: str | bytes) -> int:
        obj_id = len(objects) + 1
        if isinstance(data, str):
            objects.append(data.encode("latin-1", errors="replace"))
        else:
            objects.append(data)
        return obj_id

    catalog_id = add_object("<< /Type /Catalog /Pages 2 0 R >>")
    assert catalog_id == 1
    pages_id = add_object("<< >>")
    assert pages_id == 2
    font_id = add_object("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    page_ids: list[int] = []
    for page_lines in pages:
        stream_lines = ["BT", "/F1 11 Tf", "50 795 Td", "14 TL"]
        for line in page_lines:
            stream_lines.append(f"({_pdf_escape(line)}) Tj")
            stream_lines.append("T*")
        stream_lines.append("ET")
        stream_data = "\n".join(stream_lines).encode("latin-1", errors="replace")
        content_id = add_object(
            b"<< /Length "
            + str(len(stream_data)).encode("ascii")
            + b" >>\nstream\n"
            + stream_data
            + b"\nendstream"
        )
        page_id = add_object(
            f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        )
        page_ids.append(page_id)

    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects[pages_id - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("latin-1")

    output = bytearray()
    output.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")

    xref_pos = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        (
            "trailer\n"
            f"<< /Size {len(objects) + 1} /Root {catalog_id} 0 R >>\n"
            "startxref\n"
            f"{xref_pos}\n"
            "%%EOF\n"
        ).encode("ascii")
    )
    return bytes(output)
