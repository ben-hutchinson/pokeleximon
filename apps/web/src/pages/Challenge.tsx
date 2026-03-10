import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Layout from "../components/Layout";
import {
  getChallenge,
  joinChallenge,
  type ChallengeDetail,
  type ChallengeLeaderboardEntry,
  type CompetitiveGameType,
} from "../api/puzzles";

function formatSolveMs(value: number | null | undefined) {
  if (value === null || value === undefined) return "—";
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function formatGameLabel(gameType: CompetitiveGameType) {
  return gameType === "cryptic" ? "Cryptic" : "Crossword";
}

function puzzlePath(gameType: CompetitiveGameType, puzzleDate: string) {
  const params = new URLSearchParams({ date: puzzleDate });
  return gameType === "cryptic" ? `/cryptic?${params.toString()}` : `/daily?${params.toString()}`;
}

function sortRows(items: ChallengeLeaderboardEntry[]) {
  return items.slice().sort((a, b) => a.rank - b.rank);
}

export default function Challenge() {
  const { playerToken } = useAuth();
  const params = useParams();
  const challengeCode = (params.challengeCode ?? "").trim().toUpperCase();
  const [detail, setDetail] = useState<ChallengeDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [joining, setJoining] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([null]);

  const fetchPage = useMemo(
    () => async (cursor: string | null) => {
      if (!challengeCode) return;
      setLoading(true);
      setError(null);
      try {
        const item = await getChallenge({
          code: challengeCode,
          playerToken: playerToken || undefined,
          cursor: cursor ?? undefined,
          limit: 25,
        });
        setDetail(item);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load challenge.");
      } finally {
        setLoading(false);
      }
    },
    [challengeCode, playerToken],
  );

  useEffect(() => {
    setPage(0);
    setCursorHistory([null]);
    void fetchPage(null);
  }, [fetchPage]);

  const onJoin = async () => {
    if (!playerToken || !challengeCode) return;
    setJoining(true);
    setError(null);
    setStatus(null);
    try {
      const item = await joinChallenge({
        playerToken,
        code: challengeCode,
        limit: 25,
      });
      setDetail(item);
      setPage(0);
      setCursorHistory([null]);
      setStatus("You joined this challenge.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not join challenge.");
    } finally {
      setJoining(false);
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
    if (!detail?.hasMore || !detail.cursor) return;
    const nextCursor = detail.cursor;
    setCursorHistory((current) => {
      const copy = current.slice(0, page + 1);
      copy.push(nextCursor);
      return copy;
    });
    setPage((current) => current + 1);
    void fetchPage(nextCursor);
  };

  const rankedItems = sortRows(detail?.items ?? []);
  const challenge = detail?.challenge ?? null;
  const openPuzzleHref = challenge ? puzzlePath(challenge.gameType, challenge.puzzleDate) : "/daily";

  return (
    <Layout>
      <section className="page-section" aria-labelledby="challenge-heading" aria-busy={loading}>
        <div className="section-header">
          <h2 id="challenge-heading">Challenge</h2>
          <p>Compete with friends on the same puzzle and compare best completions.</p>
        </div>

        <div className="card challenge-shell">
          <div className="challenge-shell__meta">
            <div className="challenge-shell__code">Code: {challengeCode || "—"}</div>
            {challenge ? (
              <div className="challenge-shell__details">
                <span>{formatGameLabel(challenge.gameType)}</span>
                <span>Date: {challenge.puzzleDate}</span>
                <span>Members: {challenge.memberCount}</span>
              </div>
            ) : null}
          </div>
          <div className="challenge-shell__actions">
            {challenge ? (
              <Link className="button secondary" to={openPuzzleHref}>
                Open Puzzle
              </Link>
            ) : null}
            {detail && !detail.joined ? (
              <button className="button" type="button" onClick={onJoin} disabled={!playerToken || joining}>
                {joining ? "Joining..." : "Join Challenge"}
              </button>
            ) : null}
            <button className="button ghost" type="button" onClick={() => void fetchPage(cursorHistory[page] ?? null)} disabled={loading}>
              Refresh
            </button>
          </div>
          {detail?.joined ? <p className="panel__meta">You are in this challenge.</p> : null}
          {status ? <p className="panel__meta">{status}</p> : null}
        </div>

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        <div className="card">
          <div className="archive-footer">
            <span className="panel__meta">Page {page + 1}</span>
            <span className="panel__meta">{challenge ? `Challenge ${challenge.code}` : "Challenge standings"}</span>
          </div>
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Player</th>
                  <th>Solve Time</th>
                  <th>Assists</th>
                  <th>Reveals</th>
                </tr>
              </thead>
              <tbody>
                {rankedItems.map((item) => (
                  <tr key={`${item.playerToken}-${item.rank}`}>
                    <td>#{item.rank}</td>
                    <td>{item.publicSlug ? <Link to={`/players/${item.publicSlug}`}>{item.displayName}</Link> : item.displayName}</td>
                    <td>{formatSolveMs(item.solveTimeMs)}</td>
                    <td>{item.usedAssists ? "Yes" : "No"}</td>
                    <td>{item.usedReveals ? "Yes" : "No"}</td>
                  </tr>
                ))}
                {!loading && rankedItems.length === 0 ? (
                  <tr>
                    <td colSpan={5}>No completed solves submitted yet for this challenge.</td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <div className="archive-footer">
            <button className="button ghost" type="button" onClick={goPrevious} disabled={loading || page === 0}>
              Previous
            </button>
            <button className="button ghost" type="button" onClick={goNext} disabled={loading || !detail?.hasMore}>
              Next
            </button>
          </div>
        </div>
      </section>
    </Layout>
  );
}
