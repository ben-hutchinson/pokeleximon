from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Entry:
    id: str
    direction: str
    number: int
    cells: tuple[tuple[int, int], ...]

    @property
    def length(self) -> int:
        return len(self.cells)


class Grid:
    def __init__(self, width: int, height: int, blocks: set[tuple[int, int]]):
        self.width = width
        self.height = height
        self.blocks = blocks
        self.cells: dict[tuple[int, int], str | None] = {}
        for y in range(height):
            for x in range(width):
                if (x, y) in blocks:
                    continue
                self.cells[(x, y)] = None

    def is_block(self, x: int, y: int) -> bool:
        return (x, y) in self.blocks

    def get(self, x: int, y: int) -> str | None:
        return self.cells.get((x, y))

    def set(self, x: int, y: int, value: str | None) -> None:
        if (x, y) in self.blocks:
            return
        self.cells[(x, y)] = value

    def pattern_for(self, cells: list[tuple[int, int]]) -> str:
        chars = []
        for x, y in cells:
            value = self.get(x, y)
            chars.append(value if value else ".")
        return "".join(chars)

    def place_word(self, cells: list[tuple[int, int]], word: str) -> None:
        for (x, y), ch in zip(cells, word):
            self.set(x, y, ch)

    def remove_word(self, cells: list[tuple[int, int]], word: str) -> None:
        for (x, y), ch in zip(cells, word):
            current = self.get(x, y)
            if current == ch:
                self.set(x, y, None)


def parse_entries(width: int, height: int, blocks: set[tuple[int, int]]) -> list[Entry]:
    entries: list[Entry] = []
    number = 1

    def is_open(x: int, y: int) -> bool:
        return 0 <= x < width and 0 <= y < height and (x, y) not in blocks

    for y in range(height):
        for x in range(width):
            if (x, y) in blocks:
                continue
            starts_across = is_open(x, y) and not is_open(x - 1, y) and is_open(x + 1, y)
            starts_down = is_open(x, y) and not is_open(x, y - 1) and is_open(x, y + 1)
            if starts_across or starts_down:
                if starts_across:
                    cells: list[tuple[int, int]] = []
                    cx = x
                    while is_open(cx, y):
                        cells.append((cx, y))
                        cx += 1
                    entries.append(
                        Entry(
                            id=f"a{number}",
                            direction="across",
                            number=number,
                            cells=tuple(cells),
                        )
                    )
                if starts_down:
                    cells: list[tuple[int, int]] = []
                    cy = y
                    while is_open(x, cy):
                        cells.append((x, cy))
                        cy += 1
                    entries.append(
                        Entry(
                            id=f"d{number}",
                            direction="down",
                            number=number,
                            cells=tuple(cells),
                        )
                    )
                number += 1
    return entries
