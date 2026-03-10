export type PuzzleCell = {
  x: number;
  y: number;
  isBlock: boolean;
  solution: string | null;
  entryIdAcross: string | null;
  entryIdDown: string | null;
};

export type PuzzleEntry = {
  id: string;
  direction: "across" | "down";
  number: number;
  answer: string;
  clue: string;
  length: number;
  cells: [number, number][];
  sourceRef?: string | null;
  mechanism?: string | null;
  enumeration?: string | null;
  wordplayPlan?: string | null;
  wordplayMetadata?: Record<string, unknown> | null;
};

export type Puzzle = {
  id: string;
  date: string;
  gameType: PuzzleGameType;
  title: string;
  publishedAt: string;
  timezone: string;
  grid: {
    width: number;
    height: number;
    cells: PuzzleCell[];
  };
  entries: PuzzleEntry[];
  metadata: {
    difficulty: "easy" | "medium" | "hard";
    themeTags: string[];
    source: "pokeapi" | "curated";
    generatorVersion?: string | null;
    contestMode?: boolean | null;
    byline?: string | null;
    constructor?: string | null;
    editor?: string | null;
    notes?: string | null;
    connections?: ConnectionsMetadata | null;
  };
};

export type ConnectionsTile = {
  id: string;
  label: string;
  groupId: string | null;
};

export type ConnectionsGroup = {
  id: string;
  title: string;
  difficulty: "yellow" | "green" | "blue" | "purple" | string;
  labels: string[];
};

export type ConnectionsMetadata = {
  version: number;
  tiles: ConnectionsTile[];
  groups: ConnectionsGroup[];
  difficultyOrder: string[];
};

export type PuzzleGameType = "crossword" | "cryptic" | "connections";
export type CompetitiveGameType = "crossword" | "cryptic";
export type GameType = PuzzleGameType;
export type ProgressGameType = PuzzleGameType;

export type PuzzleSummary = {
  id: string;
  date: string;
  gameType: PuzzleGameType;
  title: string;
  difficulty: "easy" | "medium" | "hard";
  publishedAt: string;
  noteSnippet?: string | null;
};

export type ArchivePage = {
  items: PuzzleSummary[];
  cursor: string | null;
  hasMore: boolean;
};

export type ArchiveGameType = PuzzleGameType | "all";
export type ArchiveDifficulty = "easy" | "medium" | "hard";

export type GetDailyPuzzleOptions = {
  date?: string;
  redactAnswers?: boolean;
};

export type PuzzleTextExportEntry = {
  id: string;
  number: number;
  direction: "across" | "down" | string;
  clue: string;
  length: number;
  enumeration: string;
  cells: [number, number][];
};

export type PuzzleTextExport = {
  id: string;
  date: string;
  gameType: CompetitiveGameType;
  title: string;
  timezone: string;
  metadata: {
    difficulty: "easy" | "medium" | "hard" | string;
    themeTags: string[];
    contestMode?: boolean;
    byline?: string | null;
    constructor?: string | null;
    editor?: string | null;
    notes?: string | null;
  };
  grid: {
    width: number;
    height: number;
    rows: string[];
  };
  entries: PuzzleTextExportEntry[];
  redactedAnswers: boolean;
};

export async function getDailyPuzzle(gameType: PuzzleGameType = "crossword", options: GetDailyPuzzleOptions = {}) {
  const params = new URLSearchParams({ gameType });
  if (options.date) params.set("date", options.date);
  if (typeof options.redactAnswers === "boolean") {
    params.set("redact_answers", String(options.redactAnswers));
  }
  const res = await fetch(`/api/v1/puzzles/daily?${params.toString()}`);
  if (!res.ok) {
    const payload = await res.json().catch(() => null);
    const detail = typeof payload?.detail === "string" ? ` ${payload.detail}` : "";
    throw new Error(`Puzzle fetch failed: ${res.status}${detail}`);
  }
  const json = await res.json();
  return json.data as Puzzle;
}

export async function getPuzzleTextExport(options: { gameType: CompetitiveGameType; date?: string; puzzleId?: string }) {
  const params = new URLSearchParams({ gameType: options.gameType });
  if (options.date) params.set("date", options.date);
  if (options.puzzleId) params.set("puzzleId", options.puzzleId);
  const res = await fetch(`/api/v1/puzzles/export/text?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Text export fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as PuzzleTextExport;
}

export type GetArchiveOptions = {
  cursor?: string;
  limit?: number;
  difficulty?: ArchiveDifficulty;
  query?: string;
  themeTags?: string[];
  dateFrom?: string;
  dateTo?: string;
};

export async function getArchive(gameType: ArchiveGameType = "all", options: GetArchiveOptions = {}) {
  const params = new URLSearchParams();
  if (gameType !== "all") params.set("gameType", gameType);
  if (options.cursor) params.set("cursor", options.cursor);
  if (typeof options.limit === "number") params.set("limit", String(options.limit));
  if (options.difficulty) params.set("difficulty", options.difficulty);
  if (options.query) params.set("q", options.query);
  if (options.dateFrom) params.set("dateFrom", options.dateFrom);
  if (options.dateTo) params.set("dateTo", options.dateTo);
  for (const tag of options.themeTags ?? []) {
    if (tag.trim()) params.append("themeTag", tag.trim());
  }
  const res = await fetch(`/api/v1/puzzles/archive?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Archive fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as ArchivePage;
}

export type PersonalStatsDay = {
  date: string;
  pageViews: number;
  completions: number;
  cleanCompletions: number;
};

export type PersonalStatsBucket = {
  pageViews: number;
  completions: number;
  completionRate: number | null;
  medianSolveTimeMs: number | null;
  cleanSolveRate: number | null;
  streakCurrent: number;
  streakBest: number;
};

export type PersonalStats = {
  sessionIds: string[];
  windowDays: number;
  timezone: string;
  crossword: PersonalStatsBucket;
  cryptic: PersonalStatsBucket;
  connections: PersonalStatsBucket;
  historyByGameType: Record<PuzzleGameType, PersonalStatsDay[]>;
};

export async function getPersonalStats(options: { days?: 7 | 30 | 90; sessionIds?: string[] } = {}) {
  const params = new URLSearchParams();
  params.set("days", String(options.days ?? 30));
  for (const sessionId of options.sessionIds ?? []) {
    if (sessionId.trim()) params.append("sessionId", sessionId.trim());
  }
  const res = await fetch(`/api/v1/puzzles/stats/personal?${params.toString()}`);
  if (!res.ok) {
    throw new Error(`Personal stats fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as PersonalStats;
}

const PLAYER_TOKEN_STORAGE_KEY = "player:token:v1";

function generateToken() {
  const randomPart =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID().replace(/-/g, "")
      : `${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`;
  return `anon_${randomPart.slice(0, 24)}`;
}

export function getOrCreatePlayerToken() {
  if (typeof window === "undefined") return "";
  const existing = window.localStorage.getItem(PLAYER_TOKEN_STORAGE_KEY)?.trim() ?? "";
  if (existing) return existing;
  const next = generateToken();
  window.localStorage.setItem(PLAYER_TOKEN_STORAGE_KEY, next);
  return next;
}

export type PuzzleProgressRecord = {
  id: number;
  playerToken: string;
  key: string;
  gameType?: ProgressGameType | null;
  puzzleId?: string | null;
  progress: Record<string, unknown>;
  clientUpdatedAt?: string | null;
  updatedAt?: string | null;
  createdAt?: string | null;
};

export async function getPuzzleProgress(params: { key: string; playerToken: string }) {
  const query = new URLSearchParams({ key: params.key });
  const res = await fetch(`/api/v1/puzzles/progress?${query.toString()}`, {
    headers: {
      "X-Player-Token": params.playerToken,
    },
  });
  if (!res.ok) {
    throw new Error(`Progress fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return (json.data ?? null) as PuzzleProgressRecord | null;
}

export async function putPuzzleProgress(params: {
  key: string;
  gameType?: ProgressGameType | null;
  puzzleId?: string | null;
  progress: Record<string, unknown>;
  clientUpdatedAt?: string;
  playerToken: string;
}) {
  const res = await fetch("/api/v1/puzzles/progress", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Player-Token": params.playerToken,
    },
    body: JSON.stringify({
      key: params.key,
      gameType: params.gameType ?? null,
      puzzleId: params.puzzleId ?? null,
      progress: params.progress,
      clientUpdatedAt: params.clientUpdatedAt ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Progress save failed: ${res.status}`);
  }
  const json = await res.json();
  return (json.data ?? null) as PuzzleProgressRecord | null;
}

export type PlayerProfile = {
  playerToken: string;
  displayName: string;
  leaderboardVisible: boolean;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export async function getPlayerProfile(params: { playerToken: string }) {
  const query = new URLSearchParams({ playerToken: params.playerToken });
  const res = await fetch(`/api/v1/puzzles/profile?${query.toString()}`, {
    headers: {
      "X-Player-Token": params.playerToken,
    },
  });
  if (!res.ok) {
    throw new Error(`Profile fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as PlayerProfile;
}

export async function putPlayerProfile(params: {
  playerToken: string;
  displayName?: string;
  leaderboardVisible?: boolean;
}) {
  const res = await fetch("/api/v1/puzzles/profile", {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
      "X-Player-Token": params.playerToken,
    },
    body: JSON.stringify({
      displayName: params.displayName,
      leaderboardVisible: params.leaderboardVisible,
    }),
  });
  if (!res.ok) {
    throw new Error(`Profile update failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as PlayerProfile;
}

export type ChallengeRecord = {
  id: number;
  code: string;
  gameType: CompetitiveGameType;
  puzzleId: string;
  puzzleDate: string;
  createdByToken: string;
  memberCount: number;
  createdAt?: string | null;
};

export type ChallengeLeaderboardEntry = {
  rank: number;
  playerToken: string;
  displayName: string;
  solveTimeMs?: number | null;
  completed: boolean;
  usedAssists: boolean;
  usedReveals: boolean;
  updatedAt?: string | null;
};

export type ChallengeDetail = {
  challenge: ChallengeRecord;
  joined: boolean;
  items: ChallengeLeaderboardEntry[];
  cursor: string | null;
  hasMore: boolean;
};

export async function createChallenge(params: {
  playerToken: string;
  gameType: CompetitiveGameType;
  puzzleId?: string;
  date?: string;
}) {
  const res = await fetch("/api/v1/puzzles/challenges", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Player-Token": params.playerToken,
    },
    body: JSON.stringify({
      gameType: params.gameType,
      puzzleId: params.puzzleId ?? null,
      date: params.date ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Challenge create failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as ChallengeRecord;
}

export async function joinChallenge(params: { playerToken: string; code: string; limit?: number }) {
  const query = new URLSearchParams();
  query.set("limit", String(params.limit ?? 25));
  const res = await fetch(`/api/v1/puzzles/challenges/${encodeURIComponent(params.code)}/join?${query.toString()}`, {
    method: "POST",
    headers: {
      "X-Player-Token": params.playerToken,
    },
  });
  if (!res.ok) {
    throw new Error(`Challenge join failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as ChallengeDetail;
}

export async function getChallenge(params: { code: string; playerToken?: string; cursor?: string; limit?: number }) {
  const query = new URLSearchParams();
  if (params.cursor) query.set("cursor", params.cursor);
  query.set("limit", String(params.limit ?? 25));
  if (params.playerToken) query.set("playerToken", params.playerToken);
  const res = await fetch(`/api/v1/puzzles/challenges/${encodeURIComponent(params.code)}?${query.toString()}`, {
    headers: params.playerToken
      ? {
          "X-Player-Token": params.playerToken,
        }
      : undefined,
  });
  if (!res.ok) {
    throw new Error(`Challenge fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as ChallengeDetail;
}

export type LeaderboardSubmission = {
  id: number;
  playerToken: string;
  gameType: CompetitiveGameType;
  puzzleId: string;
  puzzleDate: string;
  completed: boolean;
  solveTimeMs?: number | null;
  usedAssists: boolean;
  usedReveals: boolean;
  sessionId?: string | null;
  submittedAt?: string | null;
  updatedAt?: string | null;
};

export async function submitLeaderboardResult(params: {
  playerToken: string;
  gameType: CompetitiveGameType;
  puzzleId: string;
  puzzleDate: string;
  completed: boolean;
  solveTimeMs?: number;
  usedAssists?: boolean;
  usedReveals?: boolean;
  sessionId?: string | null;
}) {
  const res = await fetch("/api/v1/puzzles/leaderboard/submit", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Player-Token": params.playerToken,
    },
    body: JSON.stringify({
      gameType: params.gameType,
      puzzleId: params.puzzleId,
      puzzleDate: params.puzzleDate,
      completed: params.completed,
      solveTimeMs: params.solveTimeMs ?? null,
      usedAssists: params.usedAssists ?? false,
      usedReveals: params.usedReveals ?? false,
      sessionId: params.sessionId ?? null,
    }),
  });
  if (!res.ok) {
    throw new Error(`Leaderboard submit failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as LeaderboardSubmission;
}

export type GlobalLeaderboardEntry = {
  rank: number;
  playerToken: string;
  displayName: string;
  completions: number;
  averageSolveTimeMs?: number | null;
  bestSolveTimeMs?: number | null;
};

export type GlobalLeaderboardPage = {
  scope: "daily" | "weekly";
  gameType: CompetitiveGameType;
  dateFrom: string;
  dateTo: string;
  items: GlobalLeaderboardEntry[];
  cursor: string | null;
  hasMore: boolean;
};

export async function getLeaderboard(params: {
  gameType: CompetitiveGameType;
  scope: "daily" | "weekly";
  date?: string;
  cursor?: string;
  limit?: number;
}) {
  const query = new URLSearchParams({
    gameType: params.gameType,
    scope: params.scope,
    limit: String(params.limit ?? 25),
  });
  if (params.date) query.set("date", params.date);
  if (params.cursor) query.set("cursor", params.cursor);
  const res = await fetch(`/api/v1/puzzles/leaderboard?${query.toString()}`);
  if (!res.ok) {
    throw new Error(`Leaderboard fetch failed: ${res.status}`);
  }
  const json = await res.json();
  return json.data as GlobalLeaderboardPage;
}

export type CrypticTelemetryEventType =
  | "page_view"
  | "clue_view"
  | "guess_submit"
  | "check_click"
  | "hint_click"
  | "reveal_click"
  | "abandon";

export type CrypticTelemetryPayload = {
  puzzleId: string;
  eventType: CrypticTelemetryEventType;
  sessionId?: string | null;
  candidateId?: number | null;
  eventValue?: Record<string, unknown>;
  clientTs?: string;
};

export type CrypticClueRating = "up" | "down";

export type CrypticClueFeedbackPayload = {
  puzzleId: string;
  entryId: string;
  rating: CrypticClueRating;
  reasonTags?: string[];
  sessionId: string;
  candidateId?: number | null;
  mechanism?: string | null;
  clueText?: string | null;
  clientTs?: string;
};

export async function postCrypticTelemetry(payload: CrypticTelemetryPayload) {
  const res = await fetch("/api/v1/puzzles/cryptic/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Telemetry failed: ${res.status}`);
  }
  return res.json() as Promise<{
    data: {
      id: number;
      puzzleId: string;
      eventType: string;
      createdAt: string;
    };
  }>;
}

export async function postCrypticClueFeedback(payload: CrypticClueFeedbackPayload) {
  const res = await fetch("/api/v1/puzzles/cryptic/clue-feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Clue feedback failed: ${res.status}`);
  }
  return res.json() as Promise<{
    data: {
      id: number;
      puzzleId: string;
      eventType: string;
      createdAt: string;
    };
    duplicate: boolean;
  }>;
}

export type CrosswordTelemetryEventType =
  | "page_view"
  | "clue_view"
  | "first_input"
  | "check_entry"
  | "check_square"
  | "reveal_word"
  | "reveal_square"
  | "check_all"
  | "reveal_all"
  | "clear_all"
  | "autocheck_toggle"
  | "completed"
  | "abandon";

export type CrosswordTelemetryPayload = {
  puzzleId: string;
  eventType: CrosswordTelemetryEventType;
  sessionId?: string | null;
  eventValue?: Record<string, unknown>;
  clientTs?: string;
};

export async function postCrosswordTelemetry(payload: CrosswordTelemetryPayload) {
  const res = await fetch("/api/v1/puzzles/crossword/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Telemetry failed: ${res.status}`);
  }
  return res.json() as Promise<{
    data: {
      id: number;
      puzzleId: string;
      eventType: string;
      createdAt: string;
    };
  }>;
}

export function sendCrosswordTelemetryBeacon(payload: CrosswordTelemetryPayload): boolean {
  if (!("sendBeacon" in navigator)) return false;
  try {
    const blob = new Blob([JSON.stringify(payload)], { type: "application/json" });
    return navigator.sendBeacon("/api/v1/puzzles/crossword/telemetry", blob);
  } catch {
    return false;
  }
}

export type ConnectionsTelemetryEventType =
  | "page_view"
  | "tile_select"
  | "tile_deselect"
  | "submit_group"
  | "one_away"
  | "solve_group"
  | "mistake"
  | "shuffle"
  | "completed"
  | "abandon";

export type ConnectionsTelemetryPayload = {
  puzzleId: string;
  eventType: ConnectionsTelemetryEventType;
  sessionId?: string | null;
  eventValue?: Record<string, unknown>;
  clientTs?: string;
};

export async function postConnectionsTelemetry(payload: ConnectionsTelemetryPayload) {
  const res = await fetch("/api/v1/puzzles/connections/telemetry", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    throw new Error(`Connections telemetry failed: ${res.status}`);
  }
  return res.json() as Promise<{
    data: {
      id: number;
      puzzleId: string;
      eventType: string;
      createdAt: string;
    };
  }>;
}
