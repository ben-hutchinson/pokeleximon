import type { GameType } from "./puzzles";

type ReserveGameType = Extract<GameType, "connections">;

type AdminFetchOptions = RequestInit & {
  query?: Record<string, string | number | boolean | null | undefined>;
};

const ADMIN_TOKEN_STORAGE_KEY = "admin:api-token";

export function getAdminToken() {
  if (typeof window === "undefined") return "";
  const fromStorage = window.sessionStorage.getItem(ADMIN_TOKEN_STORAGE_KEY)?.trim() ?? "";
  if (fromStorage) return fromStorage;
  return (import.meta.env.VITE_ADMIN_API_TOKEN ?? "").trim();
}

export function setAdminToken(token: string) {
  if (typeof window === "undefined") return;
  window.sessionStorage.setItem(ADMIN_TOKEN_STORAGE_KEY, token.trim());
}

export function clearAdminToken() {
  if (typeof window === "undefined") return;
  window.sessionStorage.removeItem(ADMIN_TOKEN_STORAGE_KEY);
}

async function adminFetch<T>(path: string, options: AdminFetchOptions = {}) {
  const params = new URLSearchParams();
  if (options.query) {
    for (const [key, value] of Object.entries(options.query)) {
      if (value === null || value === undefined || value === "") continue;
      params.set(key, String(value));
    }
  }
  const url = `/api/v1/admin${path}${params.toString() ? `?${params.toString()}` : ""}`;
  const token = getAdminToken();
  const authHeaders: Record<string, string> = {};
  if (token) {
    authHeaders["X-Admin-Token"] = token;
  }
  const res = await fetch(url, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...(options.headers ?? {}),
    },
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Admin request failed (${res.status}): ${text}`);
  }
  return (await res.json()) as T;
}

export type AdminReserveItem = {
  gameType: ReserveGameType;
  today: string;
  remaining: number;
  threshold: number;
  lowReserve: boolean;
  nextDate: string | null;
};

export type AdminJob = {
  id: string;
  type: string;
  date: string | null;
  status: string;
  startedAt: string | null;
  finishedAt: string | null;
  logs: string | null;
  modelVersion: string | null;
  createdAt: string | null;
};

export type AdminAlert = {
  id: number;
  alertType: string;
  gameType: string;
  severity: string;
  message: string;
  details: Record<string, unknown>;
  dedupeKey: string;
  resolvedAt: string | null;
  resolvedBy: string | null;
  resolutionNote: string | null;
  createdAt: string | null;
};

export type AnalyticsDailyUsersPoint = {
  date: string | null;
  users: number;
};

export type AdminAnalyticsSummary = {
  windowDays: number;
  timezone: string;
  dailyActiveUsers: {
    latest: number;
    average: number;
    series: AnalyticsDailyUsersPoint[];
  };
  crossword: {
    pageViewSessions: number;
    completedSessions: number;
    completionRate: number | null;
    medianSolveTimeMs: number | null;
    dropoffByEventType: Array<{
      eventType: string;
      sessions: number;
    }>;
  };
};

export type AdminDraftPuzzle = {
  id: string;
  date: string;
  gameType: GameType;
  title: string;
  publishedAt: string | null;
  timezone: string;
  grid: {
    width: number;
    height: number;
    cells: Array<Record<string, unknown>>;
  };
  entries: Array<{
    id: string;
    direction: "across" | "down";
    number: number;
    answer: string;
    clue: string;
    length: number;
    cells: Array<[number, number]>;
    sourceRef?: string | null;
    mechanism?: string | null;
    enumeration?: string | null;
    wordplayPlan?: string | null;
    wordplayMetadata?: Record<string, unknown> | null;
  }>;
  metadata: Record<string, unknown>;
};

export type AdminDraftValidationResult = {
  isPublishable: boolean;
  score?: number | null;
  hardFailures: string[];
  warnings: string[];
  metrics?: Record<string, unknown>;
};

export async function generatePuzzle(params: { date: string; gameType: ReserveGameType; force?: boolean }) {
  return adminFetch<{ jobId: string; status: string }>("/generate", {
    method: "POST",
    query: {
      date: params.date,
      gameType: params.gameType,
      force: params.force ?? false,
    },
  });
}

export async function generateDraft(params: { date?: string; gameType: Extract<GameType, "crossword" | "cryptic"> }) {
  return adminFetch<Record<string, unknown>>("/drafts/generate", {
    method: "POST",
    query: {
      date: params.date,
      gameType: params.gameType,
    },
  });
}

export async function getDraft(params: { date?: string; gameType: Extract<GameType, "crossword" | "cryptic"> }) {
  return adminFetch<{ item: AdminDraftPuzzle }>("/drafts", {
    query: {
      date: params.date,
      gameType: params.gameType,
    },
  });
}

export async function saveDraft(params: {
  puzzleId: string;
  entries: Array<{ id: string; clue: string }>;
  metadata?: { editor?: string; notes?: string };
}) {
  return adminFetch<{ item: AdminDraftPuzzle }>(`/drafts/${params.puzzleId}`, {
    method: "PUT",
    body: JSON.stringify({
      entries: params.entries,
      metadata: params.metadata ?? {},
    }),
  });
}

export async function validateDraft(puzzleId: string) {
  return adminFetch<{ item: AdminDraftPuzzle; validation: AdminDraftValidationResult }>(`/drafts/${puzzleId}/validate`, {
    method: "POST",
  });
}

export async function publishDraft(params: { puzzleId: string; contestMode?: boolean }) {
  return adminFetch<{ item: AdminDraftPuzzle; validation: AdminDraftValidationResult }>(`/drafts/${params.puzzleId}/publish`, {
    method: "POST",
    query: {
      contestMode: params.contestMode,
    },
  });
}

export async function publishPuzzle(params: { date: string; gameType: ReserveGameType; contestMode?: boolean }) {
  return adminFetch<Record<string, unknown>>("/publish", {
    method: "POST",
    query: {
      date: params.date,
      gameType: params.gameType,
      contestMode: params.contestMode,
    },
  });
}

export async function publishDaily(params: { gameType: ReserveGameType; date?: string; contestMode?: boolean }) {
  return adminFetch<Record<string, unknown>>("/publish/daily", {
    method: "POST",
    query: {
      gameType: params.gameType,
      date: params.date,
      contestMode: params.contestMode,
    },
  });
}

export async function rollbackDailyPublish(params: {
  gameType: ReserveGameType;
  date?: string;
  sourceDate?: string;
  reason?: string;
}) {
  return adminFetch<Record<string, unknown>>("/publish/rollback", {
    method: "POST",
    query: {
      gameType: params.gameType,
      date: params.date,
      sourceDate: params.sourceDate,
      reason: params.reason ?? "manual rollback from admin-ui",
      executedBy: "admin-ui",
    },
  });
}

export async function getReserveStatus(gameType?: ReserveGameType) {
  return adminFetch<{ items: AdminReserveItem[]; timezone: string }>("/reserve", {
    query: { gameType },
  });
}

export async function topUpReserve(params: { gameType?: ReserveGameType; targetCount?: number }) {
  return adminFetch<{ items: Record<string, unknown>[]; errors: Record<string, unknown>[]; timezone: string }>(
    "/reserve/topup",
    {
      method: "POST",
      query: {
        gameType: params.gameType,
        targetCount: params.targetCount,
      },
    },
  );
}

export async function listJobs(params: { status?: string; type?: string; date?: string; limit?: number } = {}) {
  return adminFetch<{ items: AdminJob[] }>("/jobs", {
    query: {
      status: params.status,
      type: params.type,
      date: params.date,
      limit: params.limit ?? 40,
    },
  });
}

export async function listAlerts(params: {
  gameType?: GameType;
  alertType?: string;
  includeResolved?: boolean;
  limit?: number;
} = {}) {
  return adminFetch<{ items: AdminAlert[] }>("/alerts", {
    query: {
      gameType: params.gameType,
      alertType: params.alertType,
      includeResolved: params.includeResolved ?? false,
      limit: params.limit ?? 40,
    },
  });
}

export async function resolveAlert(alertId: number, params: { resolvedBy?: string; note?: string } = {}) {
  return adminFetch<{ item: AdminAlert }>(`/alerts/${alertId}/resolve`, {
    method: "POST",
    query: {
      resolvedBy: params.resolvedBy ?? "admin-ui",
      note: params.note,
    },
  });
}

export async function getAnalyticsSummary(params: { days?: number } = {}) {
  return adminFetch<AdminAnalyticsSummary>("/analytics/summary", {
    query: {
      days: params.days ?? 30,
    },
  });
}

export async function approvePuzzle(
  puzzleId: string,
  params: {
    reviewedBy?: string;
    note?: string;
  } = {},
) {
  return adminFetch<Record<string, unknown>>(`/puzzles/${puzzleId}/approve`, {
    method: "POST",
    query: {
      reviewedBy: params.reviewedBy ?? "admin-ui",
      note: params.note,
    },
  });
}

export async function rejectPuzzle(
  puzzleId: string,
  params: {
    reviewedBy?: string;
    note?: string;
    regenerate?: boolean;
  } = {},
) {
  return adminFetch<Record<string, unknown>>(`/puzzles/${puzzleId}/reject`, {
    method: "POST",
    query: {
      reviewedBy: params.reviewedBy ?? "admin-ui",
      note: params.note,
      regenerate: params.regenerate ?? false,
    },
  });
}
