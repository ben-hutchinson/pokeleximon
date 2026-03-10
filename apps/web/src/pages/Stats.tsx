import { useEffect, useMemo, useState } from "react";
import Layout from "../components/Layout";
import { getPersonalStats, type PersonalStats, type PersonalStatsBucket, type PuzzleGameType } from "../api/puzzles";

const SESSION_KEYS = ["crossword:session-id", "cryptic:session-id", "connections:session-id"];
const WINDOW_OPTIONS: Array<7 | 30 | 90> = [7, 30, 90];
const GAME_OPTIONS: Array<{ value: PuzzleGameType; label: string }> = [
  { value: "crossword", label: "Crossword" },
  { value: "cryptic", label: "Cryptic" },
  { value: "connections", label: "Connections" },
];

function loadSessionIds(): string[] {
  if (typeof window === "undefined") return [];
  return Array.from(
    new Set(
      SESSION_KEYS.map((key) => window.localStorage.getItem(key) ?? "")
        .map((value) => value.trim())
        .filter((value) => value.length > 0),
    ),
  );
}

function formatPercent(value: number | null) {
  if (value === null || Number.isNaN(value)) return "N/A";
  return `${Math.round(value * 1000) / 10}%`;
}

function formatDurationMs(value: number | null) {
  if (value === null || value <= 0) return "N/A";
  const totalSeconds = Math.floor(value / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function formatDay(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Stats() {
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [gameType, setGameType] = useState<PuzzleGameType>("crossword");
  const [sessionIds, setSessionIds] = useState<string[] | null>(null);
  const [stats, setStats] = useState<PersonalStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setSessionIds(loadSessionIds());
  }, []);

  useEffect(() => {
    if (sessionIds === null) return;
    setLoading(true);
    setError(null);
    getPersonalStats({ days, sessionIds })
      .then(setStats)
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [days, sessionIds]);

  const currentBucket = useMemo<PersonalStatsBucket | null>(() => {
    if (!stats) return null;
    return stats[gameType];
  }, [gameType, stats]);

  const currentHistory = useMemo(() => {
    if (!stats) return [];
    return stats.historyByGameType[gameType] ?? [];
  }, [gameType, stats]);

  const currentGameLabel = useMemo(
    () => GAME_OPTIONS.find((option) => option.value === gameType)?.label ?? "Crossword",
    [gameType],
  );

  const hasProgress = useMemo(() => {
    if (!currentBucket) return false;
    return currentBucket.pageViews > 0 || currentBucket.completions > 0;
  }, [currentBucket]);

  const maxCompletions = useMemo(() => {
    if (currentHistory.length === 0) return 1;
    return Math.max(1, ...currentHistory.map((day) => day.completions));
  }, [currentHistory]);

  return (
    <Layout>
      <section className="page-section" aria-labelledby="stats-heading" aria-busy={loading}>
        <div className="section-header">
          <h2 id="stats-heading">Your Stats</h2>
          <p>Personal performance metrics from your local session activity.</p>
        </div>

        <div className="stats-controls" role="group" aria-label="Stats game filter">
          {GAME_OPTIONS.map((option) => (
            <button
              key={option.value}
              className={`button ghost${gameType === option.value ? " is-active" : ""}`}
              type="button"
              onClick={() => setGameType(option.value)}
              aria-pressed={gameType === option.value}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div className="stats-controls" role="group" aria-label="Stats window filter">
          {WINDOW_OPTIONS.map((option) => (
            <button
              key={option}
              className={`button ghost${days === option ? " is-active" : ""}`}
              type="button"
              onClick={() => setDays(option)}
              aria-pressed={days === option}
            >
              {option} days
            </button>
          ))}
        </div>

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        {sessionIds !== null && sessionIds.length === 0 ? (
          <div className="card">No local sessions found yet. Play a puzzle first, then return to see your stats.</div>
        ) : null}

        {stats ? (
          <>
            <div className="stats-grid">
              <article className="card stats-card">
                <h3>Completion Rate</h3>
                <strong>{formatPercent(currentBucket?.completionRate ?? null)}</strong>
              </article>
              <article className="card stats-card">
                <h3>Median Solve Time</h3>
                <strong>{formatDurationMs(currentBucket?.medianSolveTimeMs ?? null)}</strong>
              </article>
              <article className="card stats-card">
                <h3>Clean-Solve Rate</h3>
                <strong>{formatPercent(currentBucket?.cleanSolveRate ?? null)}</strong>
              </article>
              <article className="card stats-card">
                <h3>Current Streak</h3>
                <strong>{currentBucket?.streakCurrent ?? 0}</strong>
              </article>
              <article className="card stats-card">
                <h3>Best Streak</h3>
                <strong>{currentBucket?.streakBest ?? 0}</strong>
              </article>
              <article className="card stats-card">
                <h3>Completions</h3>
                <strong>{currentBucket?.completions ?? 0}</strong>
              </article>
            </div>

            {!hasProgress ? (
              <div className="card">No {currentGameLabel.toLowerCase()} activity in this window yet. Try switching games or expanding the date range.</div>
            ) : (
              <section className="card stats-history" aria-label={`${currentGameLabel} history`}>
                <h3>{currentGameLabel} History</h3>
                <div className="stats-history__rows">
                  {currentHistory.map((day) => {
                    const width = Math.round((day.completions / maxCompletions) * 100);
                    return (
                      <div className="stats-history__row" key={day.date}>
                        <div className="stats-history__date">{formatDay(day.date)}</div>
                        <div className="stats-history__bar-wrap" aria-hidden="true">
                          <div className="stats-history__bar" style={{ width: `${width}%` }} />
                        </div>
                        <div className="stats-history__value">
                          {day.completions} solved
                          {day.cleanCompletions > 0 ? ` (${day.cleanCompletions} clean)` : ""}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </>
        ) : null}
      </section>
    </Layout>
  );
}
