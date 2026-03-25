import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { getPublicPlayerStats, type PersonalStats, type PersonalStatsBucket, type PuzzleGameType } from "../api/puzzles";
import Layout from "../components/Layout";
import ProfileAvatar from "../components/ProfileAvatar";

const WINDOW_OPTIONS: Array<7 | 30 | 90> = [7, 30, 90];
const GAME_OPTIONS: Array<{ value: PuzzleGameType; label: string }> = [
  { value: "crossword", label: "Crossword" },
  { value: "cryptic", label: "Cryptic" },
  { value: "connections", label: "Connections" },
];

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

export default function PlayerProfile() {
  const { publicSlug = "" } = useParams();
  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [gameType, setGameType] = useState<PuzzleGameType>("crossword");
  const [profile, setProfile] = useState<{ displayName: string; publicSlug: string; avatarPreset?: string | null } | null>(null);
  const [stats, setStats] = useState<PersonalStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!publicSlug) return;
    setLoading(true);
    setError(null);
    getPublicPlayerStats({ publicSlug, days })
      .then((item) => {
        setProfile(item.profile);
        setStats(item.stats);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load player profile."))
      .finally(() => setLoading(false));
  }, [days, publicSlug]);

  const currentBucket = useMemo<PersonalStatsBucket | null>(() => {
    if (!stats) return null;
    return stats[gameType];
  }, [gameType, stats]);

  const currentHistory = useMemo(() => {
    if (!stats) return [];
    return stats.historyByGameType[gameType] ?? [];
  }, [gameType, stats]);

  const maxCompletions = useMemo(() => {
    if (currentHistory.length === 0) return 1;
    return Math.max(1, ...currentHistory.map((day) => day.completions));
  }, [currentHistory]);

  const currentGameLabel = useMemo(
    () => GAME_OPTIONS.find((option) => option.value === gameType)?.label ?? "Crossword",
    [gameType],
  );

  return (
    <Layout>
      <section className="page-section profile-page" aria-labelledby="player-profile-heading" aria-busy={loading}>
        <div className="profile-page__header">
          <ProfileAvatar
            className="profile-page__avatar"
            displayName={profile?.displayName ?? "Player Profile"}
            avatarPreset={profile?.avatarPreset ?? null}
            size="lg"
          />
          <div className="section-header">
            <h2 id="player-profile-heading">{profile?.displayName ?? "Player Profile"}</h2>
            <p>Public stats page for @{profile?.publicSlug ?? publicSlug}.</p>
          </div>
        </div>

        <div className="stats-controls" role="group" aria-label="Public stats game filter">
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

        <div className="stats-controls" role="group" aria-label="Public stats window filter">
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

        {error ? <div className="error" role="alert">{error}</div> : null}

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
          </>
        ) : null}
      </section>
    </Layout>
  );
}
