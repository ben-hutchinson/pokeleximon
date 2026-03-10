import { useCallback, useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Layout from "../components/Layout";
import PuzzleGrid from "../components/PuzzleGrid";
import ClueList from "../components/ClueList";
import {
  createChallenge,
  getDailyPuzzle,
  getOrCreatePlayerToken,
  getPuzzleProgress,
  postCrosswordTelemetry,
  submitLeaderboardResult,
  putPuzzleProgress,
  sendCrosswordTelemetryBeacon,
  type CrosswordTelemetryEventType,
  type GameType,
  type Puzzle,
} from "../api/puzzles";
import type { Direction, GridAction, GridFocusRequest } from "../components/PuzzleGrid";

type StoredTimerState = {
  elapsedMs: number;
  startedAtMs: number | null;
  isRunning: boolean;
};

type CrosswordCompletionRecord = {
  puzzleId: string;
  date: string;
  completedAt: string;
  solveMs: number;
  checkEntryCount: number;
  checkSquareCount: number;
  checkAllCount: number;
  revealWordCount: number;
  revealSquareCount: number;
  revealAllCount: number;
  clearAllCount: number;
};

type CrosswordProgressStore = {
  completedDates: string[];
  completionsByPuzzle: Record<string, CrosswordCompletionRecord>;
  updatedAt: string;
};

const TIMER_STORAGE_VERSION = "v1";
const CROSSWORD_PROGRESS_SCHEMA_VERSION = 2;
const CROSSWORD_SESSION_KEY = "crossword:session-id";
const CROSSWORD_PROGRESS_STORAGE_KEY = "crossword:progress:v2";
const CROSSWORD_PROGRESS_LEGACY_STORAGE_KEY = "crossword:progress:v1";
const CROSSWORD_AUTOCHECK_STORAGE_KEY = "crossword:settings:autocheck:v1";
const CROSSWORD_PENCIL_STORAGE_KEY = "crossword:settings:pencil:v1";
const CROSSWORD_PROFILE_PROGRESS_KEY = "crossword:profile";
const MS_PER_DAY = 24 * 60 * 60 * 1000;
const CELEBRATION_PARTICLES = Array.from({ length: 16 }, (_, index) => ({
  angle: `${index * 22.5}deg`,
  delay: `${(index % 4) * 35}ms`,
}));

function getOrCreateCrosswordSessionId() {
  const existing = localStorage.getItem(CROSSWORD_SESSION_KEY);
  if (existing) return existing;
  const next = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  localStorage.setItem(CROSSWORD_SESSION_KEY, next);
  return next;
}

function formatElapsed(ms: number) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function parseDateStamp(dateStr: string): number | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]) - 1;
  const day = Number(match[3]);
  return Math.floor(Date.UTC(year, month, day) / MS_PER_DAY);
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function normalizeCompletedDates(dates: string[]): string[] {
  const unique = Array.from(new Set(dates.filter((date) => parseDateStamp(date) !== null)));
  unique.sort((a, b) => {
    const aStamp = parseDateStamp(a) ?? 0;
    const bStamp = parseDateStamp(b) ?? 0;
    return aStamp - bStamp;
  });
  return unique;
}

function computeStreaks(dates: string[]) {
  if (dates.length === 0) {
    return { current: 0, best: 0 };
  }

  const stamps = normalizeCompletedDates(dates)
    .map((date) => parseDateStamp(date))
    .filter((stamp): stamp is number => stamp !== null);
  if (stamps.length === 0) {
    return { current: 0, best: 0 };
  }

  let best = 1;
  let run = 1;
  for (let index = 1; index < stamps.length; index += 1) {
    if (stamps[index] === stamps[index - 1] + 1) {
      run += 1;
      best = Math.max(best, run);
    } else if (stamps[index] !== stamps[index - 1]) {
      run = 1;
    }
  }

  let current = 1;
  for (let index = stamps.length - 1; index > 0; index -= 1) {
    if (stamps[index] === stamps[index - 1] + 1) {
      current += 1;
      continue;
    }
    break;
  }

  return { current, best };
}

function loadCrosswordProgress(): CrosswordProgressStore {
  if (typeof window === "undefined") {
    return { completedDates: [], completionsByPuzzle: {}, updatedAt: new Date().toISOString() };
  }
  const raw =
    window.localStorage.getItem(CROSSWORD_PROGRESS_STORAGE_KEY) ??
    window.localStorage.getItem(CROSSWORD_PROGRESS_LEGACY_STORAGE_KEY);
  if (!raw) return { completedDates: [], completionsByPuzzle: {}, updatedAt: new Date().toISOString() };
  try {
    const parsed = JSON.parse(raw) as Partial<CrosswordProgressStore>;
    return {
      completedDates: Array.isArray(parsed.completedDates) ? normalizeCompletedDates(parsed.completedDates) : [],
      completionsByPuzzle:
        parsed.completionsByPuzzle && typeof parsed.completionsByPuzzle === "object" ? parsed.completionsByPuzzle : {},
      updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString(),
    };
  } catch {
    return { completedDates: [], completionsByPuzzle: {}, updatedAt: new Date().toISOString() };
  }
}

function saveCrosswordProgress(progress: CrosswordProgressStore) {
  if (typeof window === "undefined") return;
  const normalized = {
    completedDates: normalizeCompletedDates(progress.completedDates),
    completionsByPuzzle: progress.completionsByPuzzle ?? {},
    updatedAt: progress.updatedAt || new Date().toISOString(),
  };
  window.localStorage.setItem(CROSSWORD_PROGRESS_STORAGE_KEY, JSON.stringify(normalized));
}

function normalizeCrosswordProgressStore(value: unknown): CrosswordProgressStore {
  const base = {
    completedDates: [] as string[],
    completionsByPuzzle: {} as Record<string, CrosswordCompletionRecord>,
    updatedAt: new Date().toISOString(),
  };
  if (!value || typeof value !== "object") return base;
  const parsed = value as Partial<CrosswordProgressStore>;
  return {
    completedDates: Array.isArray(parsed.completedDates) ? normalizeCompletedDates(parsed.completedDates) : [],
    completionsByPuzzle:
      parsed.completionsByPuzzle && typeof parsed.completionsByPuzzle === "object" ? parsed.completionsByPuzzle : {},
    updatedAt: typeof parsed.updatedAt === "string" ? parsed.updatedAt : new Date().toISOString(),
  };
}

function mergeCrosswordProgress(localProgress: CrosswordProgressStore, remoteProgress: CrosswordProgressStore): CrosswordProgressStore {
  const mergedCompletions: Record<string, CrosswordCompletionRecord> = { ...localProgress.completionsByPuzzle };
  for (const [puzzleId, remoteRecordRaw] of Object.entries(remoteProgress.completionsByPuzzle)) {
    const remoteRecord = normalizeCompletionRecord(remoteRecordRaw);
    const localRecord = mergedCompletions[puzzleId];
    if (!localRecord) {
      mergedCompletions[puzzleId] = remoteRecord;
      continue;
    }
    const localCompletedTs = parseTimestamp(localRecord.completedAt);
    const remoteCompletedTs = parseTimestamp(remoteRecord.completedAt);
    if (remoteCompletedTs >= localCompletedTs) {
      mergedCompletions[puzzleId] = remoteRecord;
    }
  }

  const mergedDates = normalizeCompletedDates([
    ...localProgress.completedDates,
    ...remoteProgress.completedDates,
    ...Object.values(mergedCompletions).map((record) => record.date),
  ]);

  const updatedAt =
    parseTimestamp(remoteProgress.updatedAt) > parseTimestamp(localProgress.updatedAt)
      ? remoteProgress.updatedAt
      : localProgress.updatedAt;

  return {
    completedDates: mergedDates,
    completionsByPuzzle: mergedCompletions,
    updatedAt,
  };
}

function normalizeCompletionRecord(record: CrosswordCompletionRecord): CrosswordCompletionRecord {
  return {
    ...record,
    checkSquareCount: Number(record.checkSquareCount ?? 0),
    revealWordCount: Number(record.revealWordCount ?? 0),
    revealSquareCount: Number(record.revealSquareCount ?? 0),
  };
}

function saveCrosswordCompletion(record: CrosswordCompletionRecord) {
  const normalizedRecord = normalizeCompletionRecord(record);
  const progress = loadCrosswordProgress();
  const completedDates = normalizeCompletedDates([...progress.completedDates, normalizedRecord.date]);
  const next: CrosswordProgressStore = {
    completedDates,
    completionsByPuzzle: {
      ...progress.completionsByPuzzle,
      [normalizedRecord.puzzleId]: normalizedRecord,
    },
    updatedAt: new Date().toISOString(),
  };
  saveCrosswordProgress(next);
  const streaks = computeStreaks(next.completedDates);
  return { streaks, completion: normalizedRecord, progress: next };
}

function isCleanSolve(record: CrosswordCompletionRecord | null): boolean {
  if (!record) return false;
  const checksUsed = record.checkEntryCount + record.checkSquareCount + record.checkAllCount;
  const revealsUsed = record.revealWordCount + record.revealSquareCount + record.revealAllCount;
  return revealsUsed === 0 && checksUsed <= 2;
}

export default function Daily() {
  const [searchParams] = useSearchParams();
  const [puzzle, setPuzzle] = useState<Puzzle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [direction, setDirection] = useState<Direction>("across");
  const [activeEntryId, setActiveEntryId] = useState<string | null>(null);
  const [actionId, setActionId] = useState(0);
  const [gridAction, setGridAction] = useState<GridAction | null>(null);
  const [gridFocusRequest, setGridFocusRequest] = useState<GridFocusRequest | null>(null);
  const [checkedEntryIds, setCheckedEntryIds] = useState<string[]>([]);
  const [activeCellKey, setActiveCellKey] = useState<string | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [startedAtMs, setStartedAtMs] = useState<number | null>(null);
  const [isTimerRunning, setIsTimerRunning] = useState(false);
  const [tickMs, setTickMs] = useState(Date.now());
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isCelebrating, setIsCelebrating] = useState(false);
  const [celebrationKey, setCelebrationKey] = useState(0);
  const [isSolved, setIsSolved] = useState(false);
  const [checkEntryCount, setCheckEntryCount] = useState(0);
  const [checkSquareCount, setCheckSquareCount] = useState(0);
  const [checkAllCount, setCheckAllCount] = useState(0);
  const [revealWordCount, setRevealWordCount] = useState(0);
  const [revealSquareCount, setRevealSquareCount] = useState(0);
  const [revealAllCount, setRevealAllCount] = useState(0);
  const [clearAllCount, setClearAllCount] = useState(0);
  const [autoCheckEnabled, setAutoCheckEnabled] = useState(false);
  const [pencilModeEnabled, setPencilModeEnabled] = useState(false);
  const [playerToken, setPlayerToken] = useState("");
  const [currentStreak, setCurrentStreak] = useState(0);
  const [bestStreak, setBestStreak] = useState(0);
  const [completionRecord, setCompletionRecord] = useState<CrosswordCompletionRecord | null>(null);
  const [shareStatus, setShareStatus] = useState<string | null>(null);
  const [challengeStatus, setChallengeStatus] = useState<string | null>(null);
  const [creatingChallenge, setCreatingChallenge] = useState(false);
  const [progressRefreshKey, setProgressRefreshKey] = useState(0);
  const gameTypeParam = searchParams.get("gameType");
  const selectedGameType: GameType = gameTypeParam === "cryptic" ? "cryptic" : "crossword";
  const selectedDate = searchParams.get("date") ?? undefined;
  const puzzleId = puzzle?.id ?? null;
  const puzzleGameType = puzzle?.gameType ?? null;
  const trackedPuzzleId = useRef<string | null>(null);
  const trackedClueIds = useRef<Set<string>>(new Set());
  const hasSentCompleted = useRef(false);
  const hasSentAbandon = useRef(false);
  const latestSolveMs = useRef(0);
  const latestCheckedCount = useRef(0);
  const celebrationTimeoutRef = useRef<number | null>(null);
  const shareStatusTimeoutRef = useRef<number | null>(null);
  const challengeStatusTimeoutRef = useRef<number | null>(null);

  const contestModeEnabled = Boolean(puzzle?.metadata.contestMode);

  const track = useCallback(
    async (eventType: CrosswordTelemetryEventType, eventValue: Record<string, unknown> = {}) => {
      if (!puzzle || puzzle.gameType !== "crossword") return;
      try {
        await postCrosswordTelemetry({
          puzzleId: puzzle.id,
          eventType,
          sessionId,
          eventValue: {
            contestMode: contestModeEnabled,
            ...eventValue,
          },
          clientTs: new Date().toISOString(),
        });
      } catch {
        // Telemetry should not block gameplay.
      }
    },
    [contestModeEnabled, puzzle, sessionId],
  );

  const issueAction = (type: GridAction["type"]) => {
    const blockedByContest =
      contestModeEnabled &&
      (type === "check-entry" ||
        type === "check-square" ||
        type === "check-all" ||
        type === "reveal-word" ||
        type === "reveal-square" ||
        type === "reveal-all");
    if (blockedByContest) return;

    const nextId = actionId + 1;
    setActionId(nextId);

    if (type === "check-entry") setCheckEntryCount((current) => current + 1);
    if (type === "check-square") setCheckSquareCount((current) => current + 1);
    if (type === "check-all") setCheckAllCount((current) => current + 1);
    if (type === "reveal-word") setRevealWordCount((current) => current + 1);
    if (type === "reveal-square") setRevealSquareCount((current) => current + 1);
    if (type === "reveal-all") setRevealAllCount((current) => current + 1);
    if (type === "clear-all") setClearAllCount((current) => current + 1);

    const eventMap: Record<GridAction["type"], CrosswordTelemetryEventType> = {
      "check-entry": "check_entry",
      "check-square": "check_square",
      "check-all": "check_all",
      "reveal-word": "reveal_word",
      "reveal-square": "reveal_square",
      "reveal-all": "reveal_all",
      "clear-all": "clear_all",
    };

    if (type === "check-entry" || type === "reveal-word") {
      void track(eventMap[type], {
        entryId: activeEntryId,
      });
    } else if (type === "check-square" || type === "reveal-square") {
      void track(eventMap[type], {
        cellKey: activeCellKey,
      });
    } else {
      void track(eventMap[type], {});
    }

    if (type === "check-entry" || type === "reveal-word") {
      setGridAction({ id: nextId, type, entryId: activeEntryId });
      return;
    }
    setGridAction({ id: nextId, type });
  };

  const onSelectClueEntry = (entryId: string, nextDirection: Direction) => {
    setDirection(nextDirection);
    setActiveEntryId(entryId);
    setGridFocusRequest((current) => ({ id: (current?.id ?? 0) + 1, entryId }));
  };

  const syncCrosswordProfileToCloud = useCallback(
    async (progress: CrosswordProgressStore) => {
      const token = playerToken.trim();
      if (!token) return;
      try {
        await putPuzzleProgress({
          key: CROSSWORD_PROFILE_PROGRESS_KEY,
          gameType: "crossword",
          puzzleId: null,
          progress: {
            version: CROSSWORD_PROGRESS_SCHEMA_VERSION,
            updatedAt: progress.updatedAt,
            completedDates: progress.completedDates,
            completionsByPuzzle: progress.completionsByPuzzle,
          },
          clientUpdatedAt: progress.updatedAt,
          playerToken: token,
        });
      } catch {
        // Keep local profile if cloud sync fails.
      }
    },
    [playerToken],
  );

  useEffect(() => {
    setSessionId(getOrCreateCrosswordSessionId());
    setPlayerToken(getOrCreatePlayerToken());
  }, []);

  useEffect(() => {
    const stored = localStorage.getItem(CROSSWORD_AUTOCHECK_STORAGE_KEY);
    setAutoCheckEnabled(stored === "1");
    const storedPencil = localStorage.getItem(CROSSWORD_PENCIL_STORAGE_KEY);
    setPencilModeEnabled(storedPencil === "1");
  }, []);

  useEffect(() => {
    localStorage.setItem(CROSSWORD_AUTOCHECK_STORAGE_KEY, autoCheckEnabled ? "1" : "0");
  }, [autoCheckEnabled]);

  useEffect(() => {
    localStorage.setItem(CROSSWORD_PENCIL_STORAGE_KEY, pencilModeEnabled ? "1" : "0");
  }, [pencilModeEnabled]);

  useEffect(() => {
    if (!playerToken.trim()) return;
    let cancelled = false;
    const hydrate = async () => {
      const localProgress = loadCrosswordProgress();
      let merged = localProgress;

      try {
        const remote = await getPuzzleProgress({
          key: CROSSWORD_PROFILE_PROGRESS_KEY,
          playerToken: playerToken.trim(),
        });
        if (cancelled) return;
        const remoteProgress = normalizeCrosswordProgressStore(remote?.progress);
        if (remoteProgress.completedDates.length > 0 || Object.keys(remoteProgress.completionsByPuzzle).length > 0) {
          merged = mergeCrosswordProgress(localProgress, remoteProgress);
        }
      } catch {
        // Fallback to local-only progress.
      }

      if (cancelled) return;
      saveCrosswordProgress(merged);
      const streaks = computeStreaks(merged.completedDates);
      setCurrentStreak(streaks.current);
      setBestStreak(streaks.best);
      setProgressRefreshKey((current) => current + 1);
      void syncCrosswordProfileToCloud(merged);
    };

    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [playerToken, syncCrosswordProfileToCloud]);

  useEffect(() => {
    return () => {
      if (celebrationTimeoutRef.current !== null) {
        window.clearTimeout(celebrationTimeoutRef.current);
      }
      if (shareStatusTimeoutRef.current !== null) {
        window.clearTimeout(shareStatusTimeoutRef.current);
      }
      if (challengeStatusTimeoutRef.current !== null) {
        window.clearTimeout(challengeStatusTimeoutRef.current);
      }
    };
  }, []);

  const triggerCelebration = useCallback(() => {
    setCelebrationKey((current) => current + 1);
    setIsCelebrating(true);
    if (celebrationTimeoutRef.current !== null) {
      window.clearTimeout(celebrationTimeoutRef.current);
    }
    celebrationTimeoutRef.current = window.setTimeout(() => {
      setIsCelebrating(false);
    }, 1300);
  }, []);

  useEffect(() => {
    setPuzzle(null);
    setError(null);
    setCheckedEntryIds([]);
    setActiveCellKey(null);
    setIsSolved(false);
    setCheckEntryCount(0);
    setCheckSquareCount(0);
    setCheckAllCount(0);
    setRevealWordCount(0);
    setRevealSquareCount(0);
    setRevealAllCount(0);
    setClearAllCount(0);
    setCompletionRecord(null);
    setShareStatus(null);
    setChallengeStatus(null);
    trackedPuzzleId.current = null;
    trackedClueIds.current = new Set();
    hasSentCompleted.current = false;
    hasSentAbandon.current = false;
    getDailyPuzzle(selectedGameType, { date: selectedDate })
      .then(setPuzzle)
      .catch((err) => setError(err.message));
  }, [selectedGameType, selectedDate]);

  useEffect(() => {
    if (!puzzle?.id) {
      setElapsedMs(0);
      setStartedAtMs(null);
      setIsTimerRunning(false);
      return;
    }
    const key = `puzzle:${puzzle.id}:timer:${TIMER_STORAGE_VERSION}`;
    const raw = localStorage.getItem(key);
    if (!raw) {
      setElapsedMs(0);
      setStartedAtMs(Date.now());
      setIsTimerRunning(true);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as StoredTimerState;
      setElapsedMs(Math.max(0, Number(parsed.elapsedMs) || 0));
      setStartedAtMs(typeof parsed.startedAtMs === "number" ? parsed.startedAtMs : null);
      setIsTimerRunning(Boolean(parsed.isRunning));
    } catch {
      setElapsedMs(0);
      setStartedAtMs(Date.now());
      setIsTimerRunning(true);
    }
  }, [puzzle?.id]);

  useEffect(() => {
    const progress = loadCrosswordProgress();
    const streaks = computeStreaks(progress.completedDates);
    setCurrentStreak(streaks.current);
    setBestStreak(streaks.best);

    if (!puzzleId || puzzleGameType !== "crossword") {
      return;
    }
    const previousCompletionRaw = progress.completionsByPuzzle[puzzleId] ?? null;
    const previousCompletion = previousCompletionRaw ? normalizeCompletionRecord(previousCompletionRaw) : null;
    if (!previousCompletion) return;
    setCompletionRecord(previousCompletion);
    setIsSolved(true);
    setElapsedMs(previousCompletion.solveMs);
    setStartedAtMs(null);
    setIsTimerRunning(false);
    setCheckEntryCount(previousCompletion.checkEntryCount);
    setCheckSquareCount(previousCompletion.checkSquareCount);
    setCheckAllCount(previousCompletion.checkAllCount);
    setRevealWordCount(previousCompletion.revealWordCount);
    setRevealSquareCount(previousCompletion.revealSquareCount);
    setRevealAllCount(previousCompletion.revealAllCount);
    setClearAllCount(previousCompletion.clearAllCount);
  }, [puzzleId, puzzleGameType, progressRefreshKey]);

  useEffect(() => {
    if (!puzzle?.id) return;
    const key = `puzzle:${puzzle.id}:timer:${TIMER_STORAGE_VERSION}`;
    const payload: StoredTimerState = {
      elapsedMs,
      startedAtMs,
      isRunning: isTimerRunning,
    };
    localStorage.setItem(key, JSON.stringify(payload));
  }, [puzzle?.id, elapsedMs, startedAtMs, isTimerRunning]);

  useEffect(() => {
    if (!isTimerRunning) return;
    const interval = window.setInterval(() => {
      setTickMs(Date.now());
    }, 1000);
    return () => window.clearInterval(interval);
  }, [isTimerRunning]);

  const displayMs = elapsedMs + (isTimerRunning && startedAtMs ? Math.max(0, tickMs - startedAtMs) : 0);
  const timerLabel = formatElapsed(displayMs);

  useEffect(() => {
    latestSolveMs.current = displayMs;
  }, [displayMs]);

  useEffect(() => {
    latestCheckedCount.current = checkedEntryIds.length;
  }, [checkedEntryIds.length]);

  useEffect(() => {
    if (!puzzle || puzzle.gameType !== "crossword" || trackedPuzzleId.current === puzzle.id) return;
    trackedPuzzleId.current = puzzle.id;
    trackedClueIds.current = new Set();
    hasSentCompleted.current = false;
    hasSentAbandon.current = false;
    void track("page_view", {
      title: puzzle.title,
      date: puzzle.date,
    });
  }, [puzzle, track]);

  useEffect(() => {
    if (!puzzle || puzzle.gameType !== "crossword" || !activeEntryId) return;
    if (trackedClueIds.current.has(activeEntryId)) return;
    const entry = puzzle.entries.find((item) => item.id === activeEntryId);
    if (!entry) return;
    trackedClueIds.current.add(activeEntryId);
    void track("clue_view", {
      entryId: entry.id,
      direction: entry.direction,
      number: entry.number,
      length: entry.length,
    });
  }, [activeEntryId, puzzle, track]);

  useEffect(() => {
    if (!puzzle || puzzle.gameType !== "crossword") return;
    const onPageHide = () => {
      if (hasSentCompleted.current || hasSentAbandon.current) return;
      hasSentAbandon.current = true;
      sendCrosswordTelemetryBeacon({
        puzzleId: puzzle.id,
        eventType: "abandon",
        sessionId,
        eventValue: {
          contestMode: contestModeEnabled,
          solveMs: latestSolveMs.current,
          checkedEntries: latestCheckedCount.current,
        },
        clientTs: new Date().toISOString(),
      });
    };
    window.addEventListener("pagehide", onPageHide);
    return () => window.removeEventListener("pagehide", onPageHide);
  }, [contestModeEnabled, puzzle, sessionId]);

  const toggleTimer = () => {
    if (isTimerRunning) {
      const now = Date.now();
      setElapsedMs((current) => current + (startedAtMs ? Math.max(0, now - startedAtMs) : 0));
      setStartedAtMs(null);
      setIsTimerRunning(false);
      return;
    }
    setStartedAtMs(Date.now());
    setIsTimerRunning(true);
  };

  const resetTimer = () => {
    setElapsedMs(0);
    setStartedAtMs(isTimerRunning ? Date.now() : null);
    setTickMs(Date.now());
  };

  const toggleAutoCheck = () => {
    if (contestModeEnabled) return;
    const next = !autoCheckEnabled;
    setAutoCheckEnabled(next);
    void track("autocheck_toggle", { enabled: next });
  };

  const togglePencilMode = () => {
    setPencilModeEnabled((current) => !current);
  };

  useEffect(() => {
    if (!contestModeEnabled) return;
    setAutoCheckEnabled(false);
  }, [contestModeEnabled]);

  const submitCrosswordLeaderboard = useCallback(
    async (params: { completed: boolean; solveMs: number | null; usedAssists: boolean; usedReveals: boolean }) => {
      if (!puzzle || puzzle.gameType !== "crossword") return;
      const token = playerToken.trim();
      if (!token) return;
      try {
        await submitLeaderboardResult({
          playerToken: token,
          gameType: "crossword",
          puzzleId: puzzle.id,
          puzzleDate: puzzle.date,
          completed: params.completed,
          solveTimeMs: params.solveMs ?? undefined,
          usedAssists: params.usedAssists,
          usedReveals: params.usedReveals,
          sessionId,
        });
      } catch {
        // Do not interrupt the solve flow when leaderboard sync fails.
      }
    },
    [playerToken, puzzle, sessionId],
  );

  const createCrosswordChallenge = useCallback(async () => {
    if (!puzzle || puzzle.gameType !== "crossword" || creatingChallenge) return;
    const token = playerToken.trim();
    if (!token) {
      setChallengeStatus("Missing player token. Reload and try again.");
      return;
    }

    setCreatingChallenge(true);
    try {
      const item = await createChallenge({
        playerToken: token,
        gameType: "crossword",
        puzzleId: puzzle.id,
      });
      const shareUrl = `${window.location.origin}/challenge/${item.code}`;
      let copied = false;
      if (navigator.clipboard?.writeText) {
        try {
          await navigator.clipboard.writeText(shareUrl);
          copied = true;
        } catch {
          copied = false;
        }
      }
      if (!copied) {
        const el = document.createElement("textarea");
        el.value = shareUrl;
        el.setAttribute("readonly", "true");
        el.style.position = "absolute";
        el.style.left = "-9999px";
        document.body.appendChild(el);
        el.select();
        copied = document.execCommand("copy");
        document.body.removeChild(el);
      }
      setChallengeStatus(copied ? `Challenge created: ${item.code}. Link copied.` : `Challenge created: ${shareUrl}`);
    } catch {
      setChallengeStatus("Challenge creation failed. Please try again.");
    } finally {
      setCreatingChallenge(false);
      if (challengeStatusTimeoutRef.current !== null) {
        window.clearTimeout(challengeStatusTimeoutRef.current);
      }
      challengeStatusTimeoutRef.current = window.setTimeout(() => {
        setChallengeStatus(null);
      }, 3200);
    }
  }, [creatingChallenge, playerToken, puzzle]);

  const copyShareText = useCallback(async () => {
    if (!puzzle || puzzle.gameType !== "crossword" || !completionRecord) return;

    const checksUsed =
      completionRecord.checkEntryCount + completionRecord.checkSquareCount + completionRecord.checkAllCount;
    const revealsUsed =
      completionRecord.revealWordCount + completionRecord.revealSquareCount + completionRecord.revealAllCount;
    const cleanSolve = isCleanSolve(completionRecord);
    const puzzleUrl = `${window.location.origin}/daily?date=${puzzle.date}`;
    const shareLines = [
      `POKELEXIMON ${puzzle.date}`,
      `Solved in ${formatElapsed(completionRecord.solveMs)}`,
      `Grid ${puzzle.grid.width}x${puzzle.grid.height} • ${puzzle.entries.length} clues`,
      `Checks ${checksUsed} • Reveals ${revealsUsed}`,
      cleanSolve ? "Badge: Clean Solve" : null,
      `Streak ${currentStreak} (best ${bestStreak})`,
      puzzleUrl,
    ].filter((line): line is string => Boolean(line));
    const text = shareLines.join("\n");

    let copied = false;
    if (navigator.clipboard?.writeText) {
      try {
        await navigator.clipboard.writeText(text);
        copied = true;
      } catch {
        copied = false;
      }
    }

    if (!copied) {
      const el = document.createElement("textarea");
      el.value = text;
      el.setAttribute("readonly", "true");
      el.style.position = "absolute";
      el.style.left = "-9999px";
      document.body.appendChild(el);
      el.select();
      copied = document.execCommand("copy");
      document.body.removeChild(el);
    }

    setShareStatus(copied ? "Result copied to clipboard." : "Copy failed. You can copy from browser permissions.");
    if (shareStatusTimeoutRef.current !== null) {
      window.clearTimeout(shareStatusTimeoutRef.current);
    }
    shareStatusTimeoutRef.current = window.setTimeout(() => {
      setShareStatus(null);
    }, 2800);
  }, [bestStreak, completionRecord, currentStreak, puzzle]);

  const checksUsed = checkEntryCount + checkSquareCount + checkAllCount;
  const revealsUsed = revealWordCount + revealSquareCount + revealAllCount;
  const recapSolveLabel = completionRecord ? formatElapsed(completionRecord.solveMs) : timerLabel;
  const hasCleanSolveBadge = isCleanSolve(completionRecord);
  const puzzleByline = puzzle?.metadata.byline?.trim() ?? "";
  const puzzleConstructor = puzzle?.metadata.constructor?.trim() ?? "";
  const puzzleEditor = puzzle?.metadata.editor?.trim() ?? "";
  const puzzleNotes = puzzle?.metadata.notes?.trim() ?? "";
  const puzzleBylineLabel = puzzleByline || (puzzleConstructor ? `By ${puzzleConstructor}` : "");
  const hasPuzzleEditorial = Boolean(puzzleBylineLabel || puzzleEditor || puzzleNotes);
  const exportParams = new URLSearchParams({ gameType: "crossword" });
  if (puzzle?.date) exportParams.set("date", puzzle.date);
  const pdfExportHref = `/api/v1/puzzles/export/pdf?${exportParams.toString()}`;
  const textOnlyHref = `/text-only?${exportParams.toString()}`;

  return (
    <Layout>
      <section className="page-section" aria-labelledby="daily-puzzle-heading" aria-busy={!puzzle}>
        <h2 id="daily-puzzle-heading" className="sr-only">
          Daily crossword puzzle
        </h2>
        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}
        {!puzzle ? (
          <div className="split split--loading" role="status" aria-live="polite">
            <div className="card panel skeleton-card" aria-label="Loading crossword grid">
              <div className="skeleton-line skeleton-line--title" />
              <div className="skeleton-grid" />
              <div className="skeleton-row">
                <div className="skeleton-line skeleton-line--chip" />
                <div className="skeleton-line skeleton-line--chip" />
                <div className="skeleton-line skeleton-line--chip" />
              </div>
            </div>
            <aside aria-label="Loading clues">
              <div className="clue-list clue-list--loading">
                <section className="card skeleton-card">
                  <div className="skeleton-line skeleton-line--heading" />
                  <div className="skeleton-line" />
                  <div className="skeleton-line" />
                  <div className="skeleton-line skeleton-line--short" />
                  <div className="skeleton-line" />
                </section>
                <section className="card skeleton-card">
                  <div className="skeleton-line skeleton-line--heading" />
                  <div className="skeleton-line" />
                  <div className="skeleton-line" />
                  <div className="skeleton-line skeleton-line--short" />
                  <div className="skeleton-line" />
                </section>
              </div>
            </aside>
          </div>
        ) : (
          <div className="split">
            <div className="card panel" aria-label="Crossword grid and puzzle controls">
              {isCelebrating ? (
                <div key={celebrationKey} className="celebration-burst" aria-hidden="true">
                  {CELEBRATION_PARTICLES.map((particle, index) => (
                    <span
                      key={index}
                      className="celebration-burst__piece"
                      style={
                        {
                          "--burst-angle": particle.angle,
                          "--burst-delay": particle.delay,
                        } as CSSProperties
                      }
                    />
                  ))}
                </div>
              ) : null}
              <div className="panel__header">
                <div className="panel__title">Grid</div>
                <div className="panel__header-right">
                  <div className="timer-chip" role="status" aria-live="polite">
                    <span className="timer-chip__label">Timer</span>
                    <span className="timer-chip__value">{timerLabel}</span>
                  </div>
                  <div className="streak-chip" role="status" aria-live="polite">
                    <span className="streak-chip__label">Streak</span>
                    <span className="streak-chip__value">{currentStreak}</span>
                  </div>
                  <div className="timer-actions">
                    <button className="button ghost" onClick={toggleTimer} aria-pressed={isTimerRunning}>
                      {isTimerRunning ? "Pause" : "Resume"}
                    </button>
                    <button className="button ghost" onClick={resetTimer}>
                      Reset
                    </button>
                  </div>
                  <div className="panel__meta" role="status" aria-live="polite">
                    Direction: {direction}
                  </div>
                </div>
              </div>
              {hasPuzzleEditorial ? (
                <section className="puzzle-editorial" aria-label="Puzzle editorial metadata">
                  {(puzzleBylineLabel || puzzleEditor) && (
                    <div className="puzzle-editorial__meta">
                      {puzzleBylineLabel ? <span>{puzzleBylineLabel}</span> : null}
                      {puzzleEditor ? <span>Editor: {puzzleEditor}</span> : null}
                    </div>
                  )}
                  {puzzleNotes ? <p className="puzzle-editorial__notes">{puzzleNotes}</p> : null}
                </section>
              ) : null}
              {contestModeEnabled ? (
                <div className="contest-banner" role="status" aria-live="polite">
                  Contest mode: check and reveal assists are locked for this puzzle.
                </div>
              ) : null}
              <div className="export-tools no-print" aria-label="Puzzle export controls">
                <button className="button secondary" type="button" onClick={() => window.print()}>
                  Print Puzzle
                </button>
                <a className="button secondary" href={pdfExportHref}>
                  Download PDF
                </a>
                <a className="button ghost" href={textOnlyHref}>
                  Text-Only View
                </a>
                <button className="button ghost" type="button" onClick={() => void createCrosswordChallenge()} disabled={creatingChallenge}>
                  {creatingChallenge ? "Creating..." : "Create Challenge"}
                </button>
                <Link className="button ghost" to="/leaderboard">
                  Leaderboard
                </Link>
              </div>
              {challengeStatus ? (
                <div className="panel__meta" role="status" aria-live="polite">
                  {challengeStatus}
                </div>
              ) : null}
              <PuzzleGrid
                puzzle={puzzle}
                onDirectionChange={setDirection}
                onActiveEntryChange={setActiveEntryId}
                onCheckedEntryChange={setCheckedEntryIds}
                onFirstInput={() => {
                  void track("first_input", {
                    activeEntryId,
                    direction,
                  });
                }}
                onCompleted={() => {
                  if (hasSentCompleted.current) return;
                  hasSentCompleted.current = true;
                  hasSentAbandon.current = true;
                  triggerCelebration();
                  const solveMs = latestSolveMs.current;
                  const completion: CrosswordCompletionRecord = {
                    puzzleId: puzzle.id,
                    date: puzzle.date,
                    completedAt: new Date().toISOString(),
                    solveMs,
                    checkEntryCount,
                    checkSquareCount,
                    checkAllCount,
                    revealWordCount,
                    revealSquareCount,
                    revealAllCount,
                    clearAllCount,
                  };
                  const progressUpdate = saveCrosswordCompletion(completion);
                  setCompletionRecord(progressUpdate.completion);
                  setCurrentStreak(progressUpdate.streaks.current);
                  setBestStreak(progressUpdate.streaks.best);
                  void syncCrosswordProfileToCloud(progressUpdate.progress);
                  setElapsedMs(solveMs);
                  setStartedAtMs(null);
                  setIsTimerRunning(false);
                  setIsSolved(true);
                  void submitCrosswordLeaderboard({
                    completed: true,
                    solveMs,
                    usedAssists: checkEntryCount + checkSquareCount + checkAllCount > 0,
                    usedReveals: revealWordCount + revealSquareCount + revealAllCount > 0,
                  });
                  void track("completed", {
                    solveMs,
                    checkedEntries: latestCheckedCount.current,
                    totalEntries: puzzle.entries.length,
                    checkEntryCount,
                    checkSquareCount,
                    checkAllCount,
                    revealWordCount,
                    revealSquareCount,
                    revealAllCount,
                    clearAllCount,
                  });
                }}
                action={gridAction}
                focusRequest={gridFocusRequest}
                onSelectedCellChange={setActiveCellKey}
                autoCheck={!contestModeEnabled && autoCheckEnabled}
                pencilMode={pencilModeEnabled}
                onPencilModeChange={setPencilModeEnabled}
                playerToken={playerToken}
              />
              <div className="action-box">
                <div className="action-box__title">Puzzle Actions</div>
                <div className="action-box__row">
                  <button
                    className="button check"
                    onClick={() => issueAction("check-entry")}
                    disabled={contestModeEnabled || !activeEntryId}
                  >
                    Check Entry
                  </button>
                  <button
                    className="button reveal"
                    onClick={() => issueAction("reveal-word")}
                    disabled={contestModeEnabled || !activeEntryId}
                  >
                    Reveal Word
                  </button>
                  <button
                    className="button check"
                    onClick={() => issueAction("check-square")}
                    disabled={contestModeEnabled || !activeCellKey}
                  >
                    Check Square
                  </button>
                  <button
                    className="button reveal"
                    onClick={() => issueAction("reveal-square")}
                    disabled={contestModeEnabled || !activeCellKey}
                  >
                    Reveal Square
                  </button>
                  <button className="button check" onClick={() => issueAction("check-all")} disabled={contestModeEnabled}>
                    Check All
                  </button>
                  <button className="button reveal" onClick={() => issueAction("reveal-all")} disabled={contestModeEnabled}>
                    Reveal All
                  </button>
                  <button className="button clear" onClick={() => issueAction("clear-all")}>
                    Clear Board
                  </button>
                </div>
                <div className="action-box__toggles">
                  <label className="action-box__toggle">
                    <input
                      type="checkbox"
                      checked={autoCheckEnabled}
                      onChange={toggleAutoCheck}
                      disabled={contestModeEnabled}
                    />
                    <span>Autocheck letters while typing</span>
                  </label>
                  <label className="action-box__toggle">
                    <input
                      type="checkbox"
                      checked={pencilModeEnabled}
                      onChange={togglePencilMode}
                    />
                    <span>Pencil mode (tentative fills)</span>
                  </label>
                </div>
                <div className="action-box__hint" role="status" aria-live="polite">
                  {contestModeEnabled
                    ? "Contest mode is active. Check and reveal actions are disabled."
                    : activeEntryId || activeCellKey
                    ? `Current entry: ${activeEntryId ?? "none"} • Current square: ${activeCellKey ?? "none"}`
                    : "Select an entry or square in the grid to use granular assists."}
                </div>
              </div>
              {isSolved && completionRecord ? (
                <section className="solve-recap" aria-label="Post solve recap">
                  <div className="solve-recap__header">
                    <h3>Puzzle Recap</h3>
                    <div className="solve-recap__header-tags">
                      <span className="tag">Completed</span>
                      {hasCleanSolveBadge ? <span className="tag tag--clean">Clean Solve</span> : null}
                    </div>
                  </div>
                  <div className="solve-recap__stats">
                    <div className="solve-recap__stat">
                      <span className="solve-recap__label">Solve Time</span>
                      <strong>{recapSolveLabel}</strong>
                    </div>
                    <div className="solve-recap__stat">
                      <span className="solve-recap__label">Checks</span>
                      <strong>{checksUsed}</strong>
                    </div>
                    <div className="solve-recap__stat">
                      <span className="solve-recap__label">Reveals</span>
                      <strong>{revealsUsed}</strong>
                    </div>
                    <div className="solve-recap__stat">
                      <span className="solve-recap__label">Best Streak</span>
                      <strong>{bestStreak}</strong>
                    </div>
                  </div>
                  <div className="solve-recap__actions">
                    <button className="button secondary" type="button" onClick={() => void copyShareText()}>
                      Share Result
                    </button>
                    {shareStatus ? (
                      <p className="solve-recap__status" role="status" aria-live="polite">
                        {shareStatus}
                      </p>
                    ) : null}
                  </div>
                </section>
              ) : null}
            </div>
            <aside aria-label="Clues">
              <ClueList
                entries={puzzle.entries}
                activeEntryId={activeEntryId}
                checkedEntryIds={checkedEntryIds}
                onSelectEntry={onSelectClueEntry}
              />
            </aside>
          </div>
        )}
      </section>
    </Layout>
  );
}
