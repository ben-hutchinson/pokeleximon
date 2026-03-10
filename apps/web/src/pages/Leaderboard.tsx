import { useEffect, useMemo, useState } from "react";
import Layout from "../components/Layout";
import {
  getLeaderboard,
  getOrCreatePlayerToken,
  getPlayerProfile,
  putPlayerProfile,
  type CompetitiveGameType,
  type GlobalLeaderboardPage,
  type PlayerProfile,
} from "../api/puzzles";

function formatSolveMs(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

export default function Leaderboard() {
  const [playerToken, setPlayerToken] = useState("");
  const [profile, setProfile] = useState<PlayerProfile | null>(null);
  const [displayNameDraft, setDisplayNameDraft] = useState("");
  const [visibilityDraft, setVisibilityDraft] = useState(true);
  const [profileStatus, setProfileStatus] = useState<string | null>(null);
  const [pageData, setPageData] = useState<GlobalLeaderboardPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [gameType, setGameType] = useState<CompetitiveGameType>("crossword");
  const [scope, setScope] = useState<"daily" | "weekly">("daily");
  const [date, setDate] = useState(todayIso());
  const [page, setPage] = useState(0);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([null]);

  useEffect(() => {
    setPlayerToken(getOrCreatePlayerToken());
  }, []);

  useEffect(() => {
    if (!playerToken) return;
    getPlayerProfile({ playerToken })
      .then((item) => {
        setProfile(item);
        setDisplayNameDraft(item.displayName);
        setVisibilityDraft(item.leaderboardVisible);
      })
      .catch(() => {
        setProfileStatus("Could not load profile settings.");
      });
  }, [playerToken]);

  const fetchPage = useMemo(
    () => async (cursor: string | null) => {
      setLoading(true);
      setError(null);
      try {
        const item = await getLeaderboard({
          gameType,
          scope,
          date,
          cursor: cursor ?? undefined,
          limit: 20,
        });
        setPageData(item);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load leaderboard.");
      } finally {
        setLoading(false);
      }
    },
    [date, gameType, scope],
  );

  useEffect(() => {
    setPage(0);
    setCursorHistory([null]);
    void fetchPage(null);
  }, [fetchPage]);

  const onSaveProfile = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!playerToken) return;
    try {
      const item = await putPlayerProfile({
        playerToken,
        displayName: displayNameDraft,
        leaderboardVisible: visibilityDraft,
      });
      setProfile(item);
      setDisplayNameDraft(item.displayName);
      setVisibilityDraft(item.leaderboardVisible);
      setProfileStatus("Privacy settings saved.");
    } catch {
      setProfileStatus("Could not save profile settings.");
    }
  };

  const goPrevious = () => {
    if (page <= 0) return;
    const prevPage = page - 1;
    const prevCursor = cursorHistory[prevPage] ?? null;
    setPage(prevPage);
    void fetchPage(prevCursor);
  };

  const goNext = () => {
    if (!pageData?.hasMore || !pageData.cursor) return;
    const nextCursor = pageData.cursor;
    setCursorHistory((current) => {
      const copy = current.slice(0, page + 1);
      copy.push(nextCursor);
      return copy;
    });
    setPage((current) => current + 1);
    void fetchPage(nextCursor);
  };

  return (
    <Layout>
      <section className="page-section" aria-labelledby="leaderboard-heading" aria-busy={loading}>
        <div className="section-header">
          <h2 id="leaderboard-heading">Leaderboard</h2>
          <p>Compare completion performance for daily and weekly windows.</p>
        </div>
        <form className="card leaderboard-profile" onSubmit={onSaveProfile}>
          <h3>Your Ranking Privacy</h3>
          <label>
            <span>Display Name</span>
            <input value={displayNameDraft} onChange={(event) => setDisplayNameDraft(event.target.value)} maxLength={40} />
          </label>
          <label className="archive-checkbox">
            <input
              type="checkbox"
              checked={visibilityDraft}
              onChange={(event) => setVisibilityDraft(event.target.checked)}
            />
            <span>Show me in leaderboards</span>
          </label>
          <div className="leaderboard-profile__actions">
            <button className="button" type="submit" disabled={!playerToken}>
              Save Privacy
            </button>
            {profile ? <span className="panel__meta">Current: {profile.displayName}</span> : null}
          </div>
          {profileStatus ? <p className="panel__meta">{profileStatus}</p> : null}
        </form>
        <div className="card leaderboard-controls">
          <label>
            <span>Game</span>
            <select value={gameType} onChange={(event) => setGameType(event.target.value as CompetitiveGameType)}>
              <option value="crossword">Crossword</option>
              <option value="cryptic">Cryptic</option>
            </select>
          </label>
          <label>
            <span>Scope</span>
            <select value={scope} onChange={(event) => setScope(event.target.value as "daily" | "weekly")}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </select>
          </label>
          <label>
            <span>Date</span>
            <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
          </label>
        </div>

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        <div className="card">
          <div className="archive-footer">
            <span className="panel__meta">
              Window: {pageData?.dateFrom ?? "—"} to {pageData?.dateTo ?? "—"}
            </span>
            <span className="panel__meta">Page {page + 1}</span>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Player</th>
                  <th>Completions</th>
                  <th>Average</th>
                  <th>Best</th>
                </tr>
              </thead>
              <tbody>
                {(pageData?.items ?? []).map((item) => (
                  <tr key={`${item.playerToken}-${item.rank}`}>
                    <td>#{item.rank}</td>
                    <td>{item.displayName}</td>
                    <td>{item.completions}</td>
                    <td>{formatSolveMs(item.averageSolveTimeMs)}</td>
                    <td>{formatSolveMs(item.bestSolveTimeMs)}</td>
                  </tr>
                ))}
                {!loading && (pageData?.items ?? []).length === 0 ? (
                  <tr>
                    <td colSpan={5}>No ranked completions in this window yet.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="archive-footer">
            <button className="button ghost" type="button" onClick={goPrevious} disabled={loading || page === 0}>
              Previous
            </button>
            <button className="button ghost" type="button" onClick={goNext} disabled={loading || !pageData?.hasMore}>
              Next
            </button>
          </div>
        </div>
      </section>
    </Layout>
  );
}
