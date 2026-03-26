import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { getPuzzleProgress, putPuzzleProgress, type Puzzle } from "../api/puzzles";

type CellPos = {
  x: number;
  y: number;
  key: string;
};

type GridSnapshot = {
  version: 2;
  updatedAt: string;
  values: Record<string, string>;
  pencilValues: Record<string, boolean>;
  pencilMode: boolean;
};

type CellInputMode = "append" | "replace";

const GRID_STORAGE_VERSION = 2;

export type Direction = "across" | "down";
export type GridAction =
  | { id: number; type: "check-entry"; entryId: string | null }
  | { id: number; type: "reveal-word"; entryId: string | null }
  | { id: number; type: "check-square" }
  | { id: number; type: "reveal-square" }
  | { id: number; type: "check-all" }
  | { id: number; type: "reveal-all" }
  | { id: number; type: "clear-all" };

export type GridFocusRequest = {
  id: number;
  entryId: string;
};

function normalizeCellValue(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalizeValueMap(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") return {};
  const next: Record<string, string> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    const normalized = normalizeCellValue(String(raw ?? ""));
    if (normalized) next[key] = normalized;
  }
  return next;
}

function normalizePencilMap(value: unknown): Record<string, boolean> {
  if (!value || typeof value !== "object") return {};
  const next: Record<string, boolean> = {};
  for (const [key, raw] of Object.entries(value as Record<string, unknown>)) {
    if (raw) next[key] = true;
  }
  return next;
}

function parseGridSnapshot(raw: string | null): GridSnapshot | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as
      | GridSnapshot
      | Record<string, string>
      | {
          version?: number;
          updatedAt?: string;
          values?: Record<string, string>;
          pencilValues?: Record<string, boolean>;
          pencilMode?: boolean;
        };

    if (parsed && typeof parsed === "object" && "version" in parsed && Number(parsed.version) >= GRID_STORAGE_VERSION) {
      return {
        version: 2,
        updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString(),
        values: normalizeValueMap(parsed.values),
        pencilValues: normalizePencilMap(parsed.pencilValues),
        pencilMode: Boolean(parsed.pencilMode),
      };
    }

    // Legacy shape: direct key -> value map.
    if (parsed && typeof parsed === "object") {
      return {
        version: 2,
        updatedAt: new Date().toISOString(),
        values: normalizeValueMap(parsed),
        pencilValues: {},
        pencilMode: false,
      };
    }

    return null;
  } catch {
    return null;
  }
}

export default function PuzzleGrid({
  puzzle,
  onDirectionChange,
  onActiveEntryChange,
  onSelectedCellChange,
  onCheckedEntryChange,
  onFirstInput,
  onCompleted,
  action,
  focusRequest,
  autoCheck = false,
  pencilMode,
  onPencilModeChange,
  playerToken,
}: {
  puzzle: Puzzle;
  onDirectionChange?: (direction: Direction) => void;
  onActiveEntryChange?: (entryId: string | null) => void;
  onSelectedCellChange?: (cellKey: string | null) => void;
  onCheckedEntryChange?: (entryIds: string[]) => void;
  onFirstInput?: () => void;
  onCompleted?: () => void;
  action?: GridAction | null;
  focusRequest?: GridFocusRequest | null;
  autoCheck?: boolean;
  pencilMode?: boolean;
  onPencilModeChange?: (enabled: boolean) => void;
  playerToken?: string | null;
}) {
  const { width, height, cells } = puzzle.grid;
  const cellMap = useMemo(() => new Map(cells.map((cell) => [`${cell.x},${cell.y}`, cell])), [cells]);
  const [selected, setSelected] = useState<CellPos | null>(null);
  const [direction, setDirection] = useState<Direction>("across");
  const [values, setValues] = useState<Record<string, string>>({});
  const [pencilValues, setPencilValues] = useState<Record<string, boolean>>({});
  const [checkedEntryIds, setCheckedEntryIds] = useState<string[]>([]);
  const [hasTrackedFirstInput, setHasTrackedFirstInput] = useState(false);
  const [hasTrackedCompletion, setHasTrackedCompletion] = useState(false);
  const [internalPencilMode, setInternalPencilMode] = useState(false);
  const [progressUpdatedAt, setProgressUpdatedAt] = useState(new Date().toISOString());

  const skipProgressBumpRef = useRef(false);
  const hydratedRef = useRef(false);
  const cloudSaveTimeoutRef = useRef<number | null>(null);
  const cellInputRefs = useRef(new Map<string, HTMLInputElement>());

  const effectivePencilMode = pencilMode ?? internalPencilMode;

  const applyPencilMode = useCallback(
    (enabled: boolean) => {
      if (onPencilModeChange) {
        onPencilModeChange(enabled);
        return;
      }
      setInternalPencilMode(enabled);
    },
    [onPencilModeChange],
  );

  const gridCells = useMemo(() => {
    return Array.from({ length: width * height }, (_, idx) => {
      const x = idx % width;
      const y = Math.floor(idx / width);
      return { x, y, key: `${x},${y}` };
    });
  }, [width, height]);

  const firstFocusableKey = useMemo(() => {
    for (const pos of gridCells) {
      const cell = cellMap.get(pos.key);
      if (cell && !cell.isBlock) return pos.key;
    }
    return null;
  }, [cellMap, gridCells]);

  const clueNumbers = useMemo(() => {
    const map = new Map<string, number>();
    for (const entry of puzzle.entries) {
      const [x, y] = entry.cells[0];
      const key = `${x},${y}`;
      if (!map.has(key)) {
        map.set(key, entry.number);
      }
    }
    return map;
  }, [puzzle.entries]);

  const isBlock = useCallback(
    (pos: CellPos) => {
      const cell = cellMap.get(pos.key);
      return !cell || cell.isBlock;
    },
    [cellMap],
  );

  const entryMaps = useMemo(() => {
    const byCellAcross = new Map<string, string>();
    const byCellDown = new Map<string, string>();
    const entryCells = new Map<string, string[]>();

    for (const entry of puzzle.entries) {
      const sortedCells = [...entry.cells].sort((a, b) => {
        if (entry.direction === "across") return a[0] - b[0] || a[1] - b[1];
        return a[1] - b[1] || a[0] - b[0];
      });
      const keys = sortedCells.map(([x, y]) => `${x},${y}`);
      entryCells.set(entry.id, keys);
      for (const key of keys) {
        if (entry.direction === "across") byCellAcross.set(key, entry.id);
        else byCellDown.set(key, entry.id);
      }
    }

    return { byCellAcross, byCellDown, entryCells };
  }, [puzzle.entries]);

  const cellSolutions = useMemo(() => {
    const map = new Map<string, string>();

    // Prefer explicit grid cell solutions where present (supports rebus).
    for (const cell of puzzle.grid.cells) {
      if (cell.isBlock) continue;
      const token = normalizeCellValue(String(cell.solution ?? ""));
      if (!token) continue;
      map.set(`${cell.x},${cell.y}`, token);
    }

    for (const entry of puzzle.entries) {
      const sortedCells = [...entry.cells].sort((a, b) => {
        if (entry.direction === "across") return a[0] - b[0] || a[1] - b[1];
        return a[1] - b[1] || a[0] - b[0];
      });
      const keys = sortedCells.map(([x, y]) => `${x},${y}`);

      const rebusMapRaw = (entry as unknown as { rebus?: Record<string, string> | null }).rebus;
      const rebusMap = rebusMapRaw && typeof rebusMapRaw === "object" ? rebusMapRaw : null;

      for (let index = 0; index < keys.length; index += 1) {
        const key = keys[index];
        const rebusToken = rebusMap ? normalizeCellValue(String(rebusMap[String(index)] ?? "")) : "";
        if (rebusToken) {
          map.set(key, rebusToken);
          continue;
        }
        if (map.has(key)) continue;
        const answerToken = normalizeCellValue(entry.answer[index] ?? "");
        if (answerToken) map.set(key, answerToken);
      }
    }
    return map;
  }, [puzzle.entries, puzzle.grid.cells]);

  const isRebusCell = useCallback(
    (key: string) => {
      const expected = cellSolutions.get(key) ?? "";
      return expected.length > 1;
    },
    [cellSolutions],
  );

  const resolveDirectionForCell = useCallback(
    (key: string, preferred: Direction): Direction => {
      const hasAcross = entryMaps.byCellAcross.has(key);
      const hasDown = entryMaps.byCellDown.has(key);
      if (preferred === "across" && hasAcross) return "across";
      if (preferred === "down" && hasDown) return "down";
      if (hasAcross) return "across";
      if (hasDown) return "down";
      return preferred;
    },
    [entryMaps],
  );

  const isEntryCorrect = useCallback(
    (entryId: string, candidateValues: Record<string, string>): boolean => {
      const entryKeys = entryMaps.entryCells.get(entryId) ?? [];
      if (entryKeys.length === 0) return false;
      for (const key of entryKeys) {
        const solution = normalizeCellValue(cellSolutions.get(key) ?? "");
        const value = normalizeCellValue(candidateValues[key] ?? "");
        if (!solution || value !== solution) return false;
      }
      return true;
    },
    [entryMaps.entryCells, cellSolutions],
  );

  const recomputeCheckedEntries = useCallback(
    (candidateValues: Record<string, string>) => {
      const nextChecked = puzzle.entries.filter((entry) => isEntryCorrect(entry.id, candidateValues)).map((entry) => entry.id);
      setCheckedEntryIds(nextChecked);
    },
    [isEntryCorrect, puzzle.entries],
  );

  const activeEntryKeys = useMemo(() => {
    if (!selected) return new Set<string>();
    const key = selected.key;
    const entryId = direction === "across" ? entryMaps.byCellAcross.get(key) : entryMaps.byCellDown.get(key);
    const fallback = direction === "across" ? entryMaps.byCellDown.get(key) : entryMaps.byCellAcross.get(key);
    const finalEntryId = entryId ?? fallback;
    if (!finalEntryId) return new Set<string>();
    const keys = entryMaps.entryCells.get(finalEntryId) ?? [];
    return new Set(keys);
  }, [selected, direction, entryMaps]);

  const activeEntryId = useMemo(() => {
    if (!selected) return null;
    const key = selected.key;
    const entryId = direction === "across" ? entryMaps.byCellAcross.get(key) : entryMaps.byCellDown.get(key);
    const fallback = direction === "across" ? entryMaps.byCellDown.get(key) : entryMaps.byCellAcross.get(key);
    return entryId ?? fallback ?? null;
  }, [selected, direction, entryMaps]);

  const orderAcross = useMemo(() => {
    return gridCells.filter((pos) => !isBlock(pos)).map((pos) => pos.key);
  }, [gridCells, isBlock]);

  const orderDown = useMemo(() => {
    return [...gridCells]
      .sort((a, b) => a.x - b.x || a.y - b.y)
      .filter((pos) => !isBlock(pos))
      .map((pos) => pos.key);
  }, [gridCells, isBlock]);

  const registerCellInputRef = useCallback((key: string, element: HTMLInputElement | null) => {
    if (element) {
      cellInputRefs.current.set(key, element);
      return;
    }
    cellInputRefs.current.delete(key);
  }, []);

  const focusCell = useCallback((key: string) => {
    requestAnimationFrame(() => {
      const input = cellInputRefs.current.get(key);
      if (!input) return;
      input.focus();
      try {
        const cursorPos = input.value.length;
        input.setSelectionRange(cursorPos, cursorPos);
      } catch {
        // Ignore browsers that reject manual selection for this input type.
      }
    });
  }, []);

  const clearCellValue = useCallback((key: string) => {
    setValues((prev) => ({ ...prev, [key]: "" }));
    setPencilValues((prev) => {
      const next = { ...prev };
      delete next[key];
      return next;
    });
  }, []);

  const moveSelection = useCallback(
    (dx: number, dy: number) => {
      if (!selected) return;
      let nx = selected.x + dx;
      let ny = selected.y + dy;
      while (nx >= 0 && ny >= 0 && nx < width && ny < height) {
        const key = `${nx},${ny}`;
        const cell = cellMap.get(key);
        if (cell && !cell.isBlock) {
          setSelected({ x: nx, y: ny, key });
          focusCell(key);
          return;
        }
        nx += dx;
        ny += dy;
      }
    },
    [selected, width, height, cellMap, focusCell],
  );

  const moveNextInEntry = useCallback(
    (pos: CellPos) => {
      const key = pos.key;
      const activeDirection = resolveDirectionForCell(key, direction);
      const entryId = activeDirection === "across" ? entryMaps.byCellAcross.get(key) : entryMaps.byCellDown.get(key);
      const fallbackEntryId = activeDirection === "across" ? entryMaps.byCellDown.get(key) : entryMaps.byCellAcross.get(key);
      const targetEntryId = entryId ?? fallbackEntryId;
      if (!targetEntryId) return;
      const keys = entryMaps.entryCells.get(targetEntryId) ?? [];
      const index = keys.indexOf(key);
      if (index >= 0 && index < keys.length - 1) {
        const nextKey = keys[index + 1];
        const [x, y] = nextKey.split(",").map(Number);
        setSelected({ x, y, key: nextKey });
        focusCell(nextKey);
        return;
      }
      const order = activeDirection === "across" ? orderAcross : orderDown;
      const orderIndex = order.indexOf(key);
      const nextKey = orderIndex >= 0 ? order[(orderIndex + 1) % order.length] : order[0];
      if (!nextKey) return;
      const [x, y] = nextKey.split(",").map(Number);
      setSelected({ x, y, key: nextKey });
      focusCell(nextKey);
    },
    [direction, entryMaps, orderAcross, orderDown, focusCell, resolveDirectionForCell],
  );

  const movePrevInEntry = useCallback(
    (pos: CellPos) => {
      const key = pos.key;
      const activeDirection = resolveDirectionForCell(key, direction);
      const entryId = activeDirection === "across" ? entryMaps.byCellAcross.get(key) : entryMaps.byCellDown.get(key);
      const fallbackEntryId = activeDirection === "across" ? entryMaps.byCellDown.get(key) : entryMaps.byCellAcross.get(key);
      const targetEntryId = entryId ?? fallbackEntryId;
      const order = activeDirection === "across" ? orderAcross : orderDown;

      let prevKey: string | null = null;
      if (targetEntryId) {
        const keys = entryMaps.entryCells.get(targetEntryId) ?? [];
        const index = keys.indexOf(key);
        if (index > 0) {
          prevKey = keys[index - 1];
        }
      }

      if (!prevKey) {
        const orderIndex = order.indexOf(key);
        if (orderIndex > 0) {
          prevKey = order[orderIndex - 1];
        } else if (order.length > 0) {
          prevKey = order[order.length - 1];
        }
      }

      if (!prevKey) return;
      const [x, y] = prevKey.split(",").map(Number);
      setSelected({ x, y, key: prevKey });
      focusCell(prevKey);
      clearCellValue(prevKey);
    },
    [clearCellValue, direction, entryMaps, orderAcross, orderDown, focusCell, resolveDirectionForCell],
  );

  const commitCellInput = useCallback(
    (pos: CellPos, rawValue: string, mode: CellInputMode) => {
      const expected = normalizeCellValue(cellSolutions.get(pos.key) ?? "");
      const rebus = expected.length > 1;
      const currentValue = normalizeCellValue(values[pos.key] ?? "");
      const maxLen = Math.max(1, expected.length || 6);
      const normalizedRawValue = normalizeCellValue(rawValue);

      let nextValue = "";
      if (mode === "append") {
        const baseValue = rebus && currentValue.length < maxLen ? currentValue : "";
        nextValue = normalizeCellValue(`${baseValue}${normalizedRawValue}`).slice(0, maxLen);
      } else if (rebus) {
        nextValue = normalizedRawValue.slice(0, maxLen);
      } else {
        nextValue = normalizedRawValue.slice(-1);
      }

      if (!nextValue) {
        if (currentValue) {
          clearCellValue(pos.key);
        }
        return;
      }

      if (!hasTrackedFirstInput) {
        setHasTrackedFirstInput(true);
        onFirstInput?.();
      }

      if (autoCheck && expected) {
        if (rebus) {
          if (!expected.startsWith(nextValue)) {
            return;
          }
        } else if (nextValue !== expected) {
          clearCellValue(pos.key);
          return;
        }
      }

      setValues((prev) => ({ ...prev, [pos.key]: nextValue }));
      setPencilValues((prev) => ({ ...prev, [pos.key]: effectivePencilMode }));

      if (!rebus || (expected && nextValue.length >= expected.length)) {
        moveNextInEntry(pos);
      }
    },
    [
      autoCheck,
      cellSolutions,
      clearCellValue,
      effectivePencilMode,
      hasTrackedFirstInput,
      moveNextInEntry,
      onFirstInput,
      values,
    ],
  );

  const handleKey = useCallback(
    (event: React.KeyboardEvent<HTMLInputElement>, pos: CellPos) => {
      const key = event.key;
      if (key === " ") {
        event.preventDefault();
        const hasAcross = entryMaps.byCellAcross.has(pos.key);
        const hasDown = entryMaps.byCellDown.has(pos.key);
        if (hasAcross && hasDown) {
          setDirection((prev) => (prev === "across" ? "down" : "across"));
        }
        return;
      }
      if (key === "ArrowUp") {
        event.preventDefault();
        setDirection("down");
        moveSelection(0, -1);
        return;
      }
      if (key === "ArrowDown") {
        event.preventDefault();
        setDirection("down");
        moveSelection(0, 1);
        return;
      }
      if (key === "ArrowLeft") {
        event.preventDefault();
        setDirection("across");
        moveSelection(-1, 0);
        return;
      }
      if (key === "ArrowRight") {
        event.preventDefault();
        setDirection("across");
        moveSelection(1, 0);
        return;
      }
      if (key === "Backspace" || key === "Delete") {
        event.preventDefault();
        const currentValue = normalizeCellValue(values[pos.key] ?? "");
        if (currentValue.length > 1) {
          const trimmed = currentValue.slice(0, -1);
          setValues((prev) => ({ ...prev, [pos.key]: trimmed }));
          return;
        }
        if (currentValue.length === 1) {
          clearCellValue(pos.key);
          return;
        }
        movePrevInEntry(pos);
        return;
      }
      if (key === "Tab") return;

      if (/^[a-zA-Z0-9]$/.test(key)) {
        event.preventDefault();
        commitCellInput(pos, key, "append");
      }
    },
    [
      clearCellValue,
      commitCellInput,
      moveSelection,
      movePrevInEntry,
      entryMaps,
      values,
    ],
  );

  const handleCellInputChange = useCallback(
    (event: React.ChangeEvent<HTMLInputElement>, pos: CellPos) => {
      commitCellInput(pos, event.target.value, "replace");
    },
    [commitCellInput],
  );

  useEffect(() => {
    if (!puzzle.id) return;
    const localKey = `puzzle:${puzzle.id}:grid:v${GRID_STORAGE_VERSION}`;
    const legacyKey = `puzzle:${puzzle.id}:values`;
    let cancelled = false;

    setSelected(null);
    setDirection("across");
    setCheckedEntryIds([]);
    setHasTrackedFirstInput(false);
    setHasTrackedCompletion(false);
    hydratedRef.current = false;

    const applySnapshot = (snapshot: GridSnapshot) => {
      skipProgressBumpRef.current = true;
      setValues(snapshot.values);
      setPencilValues(snapshot.pencilValues);
      applyPencilMode(snapshot.pencilMode);
      setProgressUpdatedAt(snapshot.updatedAt || new Date().toISOString());
    };

    const localSnapshot = parseGridSnapshot(localStorage.getItem(localKey)) ?? parseGridSnapshot(localStorage.getItem(legacyKey));
    if (localSnapshot) {
      applySnapshot(localSnapshot);
    } else {
      applySnapshot({
        version: 2,
        updatedAt: new Date().toISOString(),
        values: {},
        pencilValues: {},
        pencilMode: false,
      });
    }

    const sync = async () => {
      if (!playerToken?.trim()) {
        hydratedRef.current = true;
        return;
      }
      const cloudKey = `crossword:puzzle:${puzzle.id}`;
      try {
        const remote = await getPuzzleProgress({ key: cloudKey, playerToken: playerToken.trim() });
        if (cancelled) return;

        const remoteProgress = remote?.progress ?? null;
        const parsedRemote = remoteProgress
          ? parseGridSnapshot(JSON.stringify({
              version: GRID_STORAGE_VERSION,
              updatedAt: remote?.clientUpdatedAt ?? (remoteProgress.updatedAt as string | undefined) ?? new Date().toISOString(),
              values: (remoteProgress.values as Record<string, string> | undefined) ?? {},
              pencilValues: (remoteProgress.pencilValues as Record<string, boolean> | undefined) ?? {},
              pencilMode: Boolean(remoteProgress.pencilMode),
            }))
          : null;

        const localTs = parseTimestamp(localSnapshot?.updatedAt);
        const remoteTs = parseTimestamp(parsedRemote?.updatedAt);

        if (parsedRemote && remoteTs > localTs) {
          applySnapshot(parsedRemote);
        } else if (localSnapshot) {
          await putPuzzleProgress({
            key: cloudKey,
            gameType: "crossword",
            puzzleId: puzzle.id,
            progress: {
              version: GRID_STORAGE_VERSION,
              updatedAt: localSnapshot.updatedAt,
              values: localSnapshot.values,
              pencilValues: localSnapshot.pencilValues,
              pencilMode: localSnapshot.pencilMode,
            },
            clientUpdatedAt: localSnapshot.updatedAt,
            playerToken: playerToken.trim(),
          });
        }
      } catch {
        // Network or server failures should keep local progress usable.
      } finally {
        if (!cancelled) hydratedRef.current = true;
      }
    };

    void sync();

    return () => {
      cancelled = true;
    };
  }, [puzzle.id, playerToken, applyPencilMode]);

  useEffect(() => {
    if (!hydratedRef.current) return;
    if (skipProgressBumpRef.current) {
      skipProgressBumpRef.current = false;
      return;
    }
    setProgressUpdatedAt(new Date().toISOString());
  }, [values, pencilValues, effectivePencilMode]);

  useEffect(() => {
    if (!puzzle.id || !hydratedRef.current) return;

    const snapshot: GridSnapshot = {
      version: 2,
      updatedAt: progressUpdatedAt,
      values,
      pencilValues,
      pencilMode: effectivePencilMode,
    };

    const localKey = `puzzle:${puzzle.id}:grid:v${GRID_STORAGE_VERSION}`;
    localStorage.setItem(localKey, JSON.stringify(snapshot));

    if (!playerToken?.trim()) return;

    if (cloudSaveTimeoutRef.current !== null) {
      window.clearTimeout(cloudSaveTimeoutRef.current);
    }
    cloudSaveTimeoutRef.current = window.setTimeout(() => {
      void putPuzzleProgress({
        key: `crossword:puzzle:${puzzle.id}`,
        gameType: "crossword",
        puzzleId: puzzle.id,
        progress: snapshot,
        clientUpdatedAt: snapshot.updatedAt,
        playerToken: playerToken.trim(),
      }).catch(() => {
        // Keep local progress; retry on next state change.
      });
    }, 650);
  }, [values, pencilValues, effectivePencilMode, progressUpdatedAt, puzzle.id, playerToken]);

  useEffect(() => {
    return () => {
      if (cloudSaveTimeoutRef.current !== null) {
        window.clearTimeout(cloudSaveTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (onDirectionChange) onDirectionChange(direction);
  }, [direction, onDirectionChange]);

  useEffect(() => {
    if (onActiveEntryChange) onActiveEntryChange(activeEntryId);
  }, [activeEntryId, onActiveEntryChange]);

  useEffect(() => {
    if (onSelectedCellChange) onSelectedCellChange(selected?.key ?? null);
  }, [onSelectedCellChange, selected]);

  useEffect(() => {
    if (onCheckedEntryChange) onCheckedEntryChange(checkedEntryIds);
  }, [checkedEntryIds, onCheckedEntryChange]);

  useEffect(() => {
    recomputeCheckedEntries(values);
  }, [values, recomputeCheckedEntries]);

  useEffect(() => {
    if (hasTrackedCompletion || puzzle.entries.length === 0) return;
    const solved = puzzle.entries.every((entry) => isEntryCorrect(entry.id, values));
    if (!solved) return;
    setHasTrackedCompletion(true);
    onCompleted?.();
  }, [hasTrackedCompletion, isEntryCorrect, onCompleted, puzzle.entries, values]);

  useEffect(() => {
    if (!focusRequest?.entryId) return;
    const target = puzzle.entries.find((entry) => entry.id === focusRequest.entryId);
    if (!target) return;

    const startCell = [...target.cells].sort((a, b) => {
      if (target.direction === "across") return a[0] - b[0] || a[1] - b[1];
      return a[1] - b[1] || a[0] - b[0];
    })[0];
    if (!startCell) return;

    const [x, y] = startCell;
    const key = `${x},${y}`;
    setDirection(target.direction);
    setSelected({ x, y, key });
    focusCell(key);
  }, [focusRequest?.id, focusRequest?.entryId, focusCell, puzzle.entries]);

  useEffect(() => {
    if (!action) return;
    if (action.type === "clear-all") {
      setValues({});
      setPencilValues({});
      setCheckedEntryIds([]);
      return;
    }

    if (action.type === "reveal-all") {
      const next: Record<string, string> = {};
      for (const [key, token] of cellSolutions.entries()) {
        next[key] = normalizeCellValue(token);
      }
      setValues(next);
      setPencilValues({});
      recomputeCheckedEntries(next);
      return;
    }

    if (action.type === "check-all") {
      const next = { ...values };
      const nextPencil = { ...pencilValues };
      for (const [key, value] of Object.entries(next)) {
        const token = normalizeCellValue(value);
        const solution = normalizeCellValue(cellSolutions.get(key) ?? "");
        if (!solution || !token) continue;
        if (token !== solution) {
          next[key] = "";
          delete nextPencil[key];
        } else {
          next[key] = solution;
        }
      }
      setValues(next);
      setPencilValues(nextPencil);
      recomputeCheckedEntries(next);
      return;
    }

    if (action.type === "check-square") {
      const selectedKey = selected?.key;
      if (!selectedKey) return;
      const current = normalizeCellValue(values[selectedKey] ?? "");
      const solution = normalizeCellValue(cellSolutions.get(selectedKey) ?? "");
      if (!current || !solution) return;
      const next = { ...values };
      const nextPencil = { ...pencilValues };
      if (current !== solution) {
        next[selectedKey] = "";
        delete nextPencil[selectedKey];
      } else {
        next[selectedKey] = solution;
      }
      setValues(next);
      setPencilValues(nextPencil);
      recomputeCheckedEntries(next);
      return;
    }

    if (action.type === "reveal-square") {
      const selectedKey = selected?.key;
      if (!selectedKey) return;
      const solution = normalizeCellValue(cellSolutions.get(selectedKey) ?? "");
      if (!solution) return;
      const next = { ...values, [selectedKey]: solution };
      const nextPencil = { ...pencilValues };
      delete nextPencil[selectedKey];
      setValues(next);
      setPencilValues(nextPencil);
      recomputeCheckedEntries(next);
      return;
    }

    if (action.type === "reveal-word" && action.entryId) {
      const entryKeys = entryMaps.entryCells.get(action.entryId) ?? [];
      if (entryKeys.length === 0) return;
      const next = { ...values };
      const nextPencil = { ...pencilValues };
      for (const key of entryKeys) {
        const solution = normalizeCellValue(cellSolutions.get(key) ?? "");
        if (!solution) continue;
        next[key] = solution;
        delete nextPencil[key];
      }
      setValues(next);
      setPencilValues(nextPencil);
      recomputeCheckedEntries(next);
      return;
    }

    if (action.type === "check-entry" && action.entryId) {
      const entryKeys = entryMaps.entryCells.get(action.entryId) ?? [];
      if (entryKeys.length === 0) return;
      const next = { ...values };
      const nextPencil = { ...pencilValues };
      for (const key of entryKeys) {
        const token = normalizeCellValue(next[key] ?? "");
        const solution = normalizeCellValue(cellSolutions.get(key) ?? "");
        if (!solution || !token) continue;
        if (token !== solution) {
          next[key] = "";
          delete nextPencil[key];
        } else {
          next[key] = solution;
        }
      }
      setValues(next);
      setPencilValues(nextPencil);
      recomputeCheckedEntries(next);
    }
  }, [action, cellSolutions, entryMaps.entryCells, recomputeCheckedEntries, selected?.key, values, pencilValues]);

  const gridDescriptionId = `grid-description-${puzzle.id}`;

  return (
    <div className="grid-wrap" aria-label="Crossword grid">
      <p id={gridDescriptionId} className="sr-only">
        Crossword grid. Use arrow keys to move between cells and type letters to fill answers. Multi-letter rebus cells
        are supported. Press Tab to leave the grid and continue to clues and controls.
      </p>
      <div
        className="grid-frame"
        style={
          {
            "--grid-ratio": `${width} / ${height}`,
          } as CSSProperties
        }
      >
        <div
          className="crossword-grid"
          style={{
            gridTemplateColumns: `repeat(${width}, minmax(0, 1fr))`,
            gridTemplateRows: `repeat(${height}, minmax(0, 1fr))`,
          }}
          role="grid"
          aria-label="Crossword puzzle grid"
          aria-rowcount={height}
          aria-colcount={width}
          aria-describedby={gridDescriptionId}
        >
          {gridCells.map((pos) => {
            const blocked = isBlock(pos);
            const value = normalizeCellValue(values[pos.key] ?? "");
            const selectedKey = selected?.key === pos.key;
            const activeWord = activeEntryKeys.has(pos.key);
            const clueNumber = clueNumbers.get(pos.key);
            const isTabStop = !blocked && (selected ? selected.key === pos.key : pos.key === firstFocusableKey);
            const pencil = Boolean(pencilValues[pos.key]);
            const rebusCell = isRebusCell(pos.key);
            const cellLabel = blocked
              ? `Blocked cell at row ${pos.y + 1}, column ${pos.x + 1}`
              : `Row ${pos.y + 1}, column ${pos.x + 1}${clueNumber ? `, clue ${clueNumber}` : ""}${
                  value ? `, entry ${value}` : ", empty"
                }${pencil ? ", pencil" : ""}${rebusCell ? ", rebus cell" : ""}`;
            return (
              <div
                key={pos.key}
                className={`crossword-cell ${blocked ? "is-block" : ""} ${
                  selectedKey ? "is-selected" : ""
                } ${value ? "is-filled" : ""} ${activeWord ? "is-active" : ""} ${pencil ? "is-pencil" : ""} ${
                  rebusCell || value.length > 1 ? "is-rebus" : ""
                }`}
                role="gridcell"
                aria-label={cellLabel}
                aria-rowindex={pos.y + 1}
                aria-colindex={pos.x + 1}
                aria-selected={!blocked ? selectedKey : undefined}
                data-cell={pos.key}
                onClick={() => {
                  if (!blocked) {
                    setDirection((prev) => resolveDirectionForCell(pos.key, prev));
                    setSelected(pos);
                    focusCell(pos.key);
                  }
                }}
                onFocus={() => {
                  if (!blocked) {
                    setDirection((prev) => resolveDirectionForCell(pos.key, prev));
                    setSelected(pos);
                  }
                }}
              >
                {!blocked ? (
                  <input
                    ref={(element) => registerCellInputRef(pos.key, element)}
                    className="crossword-cell__input"
                    type="text"
                    inputMode="text"
                    autoCapitalize="characters"
                    autoComplete="off"
                    autoCorrect="off"
                    spellCheck={false}
                    enterKeyHint="next"
                    aria-label={cellLabel}
                    aria-describedby={gridDescriptionId}
                    value={value}
                    tabIndex={isTabStop ? 0 : -1}
                    data-cell-input={pos.key}
                    onKeyDown={(event) => handleKey(event, pos)}
                    onChange={(event) => handleCellInputChange(event, pos)}
                  />
                ) : null}
                {!blocked && clueNumbers.has(pos.key) ? <span className="cell-number">{clueNumbers.get(pos.key)}</span> : null}
                {!blocked ? <span className="cell-value">{value}</span> : null}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
