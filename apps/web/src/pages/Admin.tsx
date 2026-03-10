import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  approvePuzzle,
  clearAdminToken,
  generatePuzzle,
  getAdminToken,
  getAnalyticsSummary,
  getReserveStatus,
  listAlerts,
  listJobs,
  publishDaily,
  publishPuzzle,
  rollbackDailyPublish,
  rejectPuzzle,
  resolveAlert,
  setAdminToken,
  topUpReserve,
  type AdminAlert,
  type AdminAnalyticsSummary,
  type AdminJob,
  type AdminReserveItem,
} from "../api/admin";
import type { GameType } from "../api/puzzles";

function todayIso() {
  return new Date().toISOString().slice(0, 10);
}

function formatTimestamp(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function formatPercent(value: number | null) {
  if (value === null) return "—";
  return `${(value * 100).toFixed(1)}%`;
}

function formatDurationMs(value: number | null) {
  if (value === null) return "—";
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export default function Admin() {
  const [adminTokenInput, setAdminTokenInput] = useState(getAdminToken());
  const [gameType, setGameType] = useState<GameType>("crossword");
  const [date, setDate] = useState(todayIso());
  const [sourceDate, setSourceDate] = useState("");
  const [rollbackReason, setRollbackReason] = useState("manual rollback from admin-ui");
  const [contestMode, setContestMode] = useState(false);
  const [targetCount, setTargetCount] = useState(30);
  const [puzzleId, setPuzzleId] = useState("");
  const [reviewNote, setReviewNote] = useState("");
  const [regenerateOnReject, setRegenerateOnReject] = useState(false);
  const [includeResolvedAlerts, setIncludeResolvedAlerts] = useState(false);

  const [reserveItems, setReserveItems] = useState<AdminReserveItem[]>([]);
  const [jobs, setJobs] = useState<AdminJob[]>([]);
  const [alerts, setAlerts] = useState<AdminAlert[]>([]);
  const [analytics, setAnalytics] = useState<AdminAnalyticsSummary | null>(null);
  const [analyticsDays, setAnalyticsDays] = useState(30);

  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<string | null>(null);
  const [tokenStatus, setTokenStatus] = useState<string | null>(null);

  const refreshAll = useCallback(async () => {
    const token = getAdminToken();
    if (!token) {
      setLoading(false);
      setReserveItems([]);
      setJobs([]);
      setAlerts([]);
      setAnalytics(null);
      setError(null);
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const [reserve, jobsRes, alertsRes] = await Promise.all([
        getReserveStatus(),
        listJobs({ limit: 40 }),
        listAlerts({ includeResolved: includeResolvedAlerts, limit: 40 }),
      ]);
      setReserveItems(reserve.items);
      setJobs(jobsRes.items);
      setAlerts(alertsRes.items);
      try {
        const analyticsRes = await getAnalyticsSummary({ days: analyticsDays });
        setAnalytics(analyticsRes);
      } catch (analyticsErr) {
        const analyticsMessage = analyticsErr instanceof Error ? analyticsErr.message : "";
        if (analyticsMessage.includes("(404)")) {
          setAnalytics(null);
        } else {
          throw analyticsErr;
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load admin data");
    } finally {
      setLoading(false);
    }
  }, [analyticsDays, includeResolvedAlerts]);

  useEffect(() => {
    void refreshAll();
  }, [refreshAll]);

  const runAction = async (key: string, runner: () => Promise<unknown>) => {
    setBusyAction(key);
    setError(null);
    try {
      const result = await runner();
      setActionResult(JSON.stringify(result, null, 2));
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyAction(null);
    }
  };

  const hasAdminToken = Boolean(getAdminToken());

  return (
    <Layout>
      <section className="page-section" aria-labelledby="admin-heading">
        <div className="section-header">
          <h2 id="admin-heading">Admin Console</h2>
          <p>Operate generation, publishing, reserve health, jobs, and review actions.</p>
        </div>

        <div className="card admin-controls">
          <div className="admin-controls__grid">
            <label className="admin-field">
              <span>Admin Token</span>
              <input
                type="password"
                value={adminTokenInput}
                onChange={(event) => setAdminTokenInput(event.target.value)}
                placeholder="Paste admin token"
              />
            </label>
          </div>
          <div className="admin-actions">
            <button
              className="button"
              type="button"
              onClick={() => {
                const cleaned = adminTokenInput.trim();
                if (!cleaned) return;
                setAdminToken(cleaned);
                setTokenStatus("Admin token saved to this session.");
                void refreshAll();
              }}
            >
              Save Token
            </button>
            <button
              className="button ghost"
              type="button"
              onClick={() => {
                clearAdminToken();
                setAdminTokenInput("");
                setTokenStatus("Admin token cleared.");
                setReserveItems([]);
                setJobs([]);
                setAlerts([]);
                setAnalytics(null);
              }}
            >
              Clear Token
            </button>
            <span className="panel__meta">
              {hasAdminToken ? "Token loaded" : "Token required for admin endpoints"}
            </span>
          </div>
          {tokenStatus ? <p className="panel__meta">{tokenStatus}</p> : null}
        </div>

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        {!hasAdminToken ? (
          <div className="card">
            <p>Enter and save the admin token to load console data and run admin actions.</p>
          </div>
        ) : null}

        <div className="card admin-controls">
          <div className="admin-controls__grid">
            <label className="admin-field">
              <span>Game Type</span>
              <select value={gameType} onChange={(event) => setGameType(event.target.value as GameType)}>
                <option value="crossword">Crossword</option>
                <option value="cryptic">Cryptic</option>
                <option value="connections">Connections</option>
              </select>
            </label>
            <label className="admin-field">
              <span>Date</span>
              <input type="date" value={date} onChange={(event) => setDate(event.target.value)} />
            </label>
            <label className="admin-field">
              <span>Rollback Source Date</span>
              <input
                type="date"
                value={sourceDate}
                onChange={(event) => setSourceDate(event.target.value)}
                placeholder="optional"
              />
            </label>
            <label className="admin-field">
              <span>Rollback Reason</span>
              <input
                value={rollbackReason}
                onChange={(event) => setRollbackReason(event.target.value)}
                placeholder="manual rollback from admin-ui"
              />
            </label>
            <label className="admin-field">
              <span>Top-up Target</span>
              <input
                type="number"
                min={1}
                max={365}
                value={targetCount}
                onChange={(event) => setTargetCount(Number(event.target.value) || 30)}
              />
            </label>
            <label className="admin-checkbox admin-checkbox--inline">
              <input
                type="checkbox"
                checked={contestMode}
                onChange={(event) => setContestMode(event.target.checked)}
              />
              Contest mode
            </label>
          </div>
          <div className="admin-actions">
            <button
              className="button"
              disabled={busyAction !== null || !hasAdminToken}
              onClick={() => runAction("generate", () => generatePuzzle({ date, gameType, force: true }))}
            >
              Generate (Force)
            </button>
            <button
              className="button secondary"
              disabled={busyAction !== null || !hasAdminToken}
              onClick={() =>
                runAction("publish", () =>
                  publishPuzzle({
                    date,
                    gameType,
                    contestMode,
                  }),
                )
              }
            >
              Publish Date
            </button>
            <button
              className="button ghost"
              disabled={busyAction !== null || !hasAdminToken}
              onClick={() =>
                runAction("publish-daily", () =>
                  publishDaily({
                    gameType,
                    contestMode,
                  }),
                )
              }
            >
              Publish Daily (Now)
            </button>
            <button
              className="button ghost"
              disabled={busyAction !== null || !hasAdminToken}
              onClick={() =>
                runAction("rollback-daily", () =>
                  rollbackDailyPublish({
                    gameType,
                    date,
                    sourceDate: sourceDate.trim() || undefined,
                    reason: rollbackReason.trim() || undefined,
                  }),
                )
              }
            >
              Rollback Daily (One-click)
            </button>
            <button
              className="button ghost"
              disabled={busyAction !== null || !hasAdminToken}
              onClick={() => runAction("topup", () => topUpReserve({ gameType, targetCount }))}
            >
              Top-up Reserve
            </button>
            <button
              className="button ghost"
              disabled={busyAction !== null || loading || !hasAdminToken}
              onClick={() => void refreshAll()}
            >
              Refresh
            </button>
          </div>
        </div>

        <section className="card">
          <div className="admin-inline-header">
            <h3>Analytics (Crossword)</h3>
            <label className="admin-field admin-field--compact">
              <span>Window (days)</span>
              <input
                type="number"
                min={1}
                max={365}
                value={analyticsDays}
                onChange={(event) => setAnalyticsDays(Math.max(1, Math.min(365, Number(event.target.value) || 30)))}
              />
            </label>
          </div>
          {loading ? <p>Loading analytics…</p> : null}
          {analytics ? (
            <div className="admin-analytics-grid">
              <div className="admin-stat">
                <div className="admin-stat__title">DAU (Latest)</div>
                <div>{analytics.dailyActiveUsers.latest}</div>
              </div>
              <div className="admin-stat">
                <div className="admin-stat__title">DAU (Average)</div>
                <div>{analytics.dailyActiveUsers.average}</div>
              </div>
              <div className="admin-stat">
                <div className="admin-stat__title">Completion Rate</div>
                <div>{formatPercent(analytics.crossword.completionRate)}</div>
              </div>
              <div className="admin-stat">
                <div className="admin-stat__title">Median Solve Time</div>
                <div>{formatDurationMs(analytics.crossword.medianSolveTimeMs)}</div>
              </div>
              <div className="admin-stat admin-stat--wide">
                <div className="admin-stat__title">Drop-off (Uncompleted Sessions)</div>
                {analytics.crossword.dropoffByEventType.length === 0 ? (
                  <div>None in window.</div>
                ) : (
                  <ul className="admin-dropoff-list">
                    {analytics.crossword.dropoffByEventType.slice(0, 6).map((row) => (
                      <li key={row.eventType}>
                        <span>{row.eventType}</span>
                        <strong>{row.sessions}</strong>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>
          ) : loading ? null : (
            <p>Analytics endpoint unavailable in this backend build.</p>
          )}
        </section>

        <div className="admin-layout">
          <section className="card">
            <h3>Reserve</h3>
            {loading ? <p>Loading reserve…</p> : null}
            <div className="admin-list">
              {reserveItems.map((item) => (
                <div key={item.gameType} className={`admin-stat ${item.lowReserve ? "is-warning" : ""}`}>
                  <div className="admin-stat__title">{item.gameType}</div>
                  <div>Remaining: {item.remaining}</div>
                  <div>Threshold: {item.threshold}</div>
                  <div>Next date: {item.nextDate ?? "—"}</div>
                </div>
              ))}
            </div>
          </section>

          <section className="card">
            <div className="admin-inline-header">
              <h3>Alerts</h3>
              <label className="admin-checkbox">
                <input
                  type="checkbox"
                  checked={includeResolvedAlerts}
                  onChange={(event) => setIncludeResolvedAlerts(event.target.checked)}
                />
                Include resolved
              </label>
            </div>
            {loading ? <p>Loading alerts…</p> : null}
            <div className="admin-table-wrap">
              <table className="admin-table">
                <thead>
                  <tr>
                    <th>ID</th>
                    <th>Type</th>
                    <th>Game</th>
                    <th>Severity</th>
                    <th>Message</th>
                    <th>Created</th>
                    <th>Action</th>
                  </tr>
                </thead>
                <tbody>
                  {alerts.map((alert) => (
                    <tr key={alert.id}>
                      <td>{alert.id}</td>
                      <td>{alert.alertType}</td>
                      <td>{alert.gameType}</td>
                      <td>{alert.severity}</td>
                      <td>{alert.message}</td>
                      <td>{formatTimestamp(alert.createdAt)}</td>
                      <td>
                        {alert.resolvedAt ? (
                          "Resolved"
                        ) : (
                          <button
                            className="button ghost"
                            disabled={busyAction !== null || !hasAdminToken}
                            onClick={() => runAction(`resolve-${alert.id}`, () => resolveAlert(alert.id))}
                          >
                            Resolve
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <section className="card">
          <h3>Puzzle Review</h3>
          <div className="admin-controls__grid">
            <label className="admin-field">
              <span>Puzzle ID</span>
              <input value={puzzleId} onChange={(event) => setPuzzleId(event.target.value)} placeholder="puz_..." />
            </label>
            <label className="admin-field">
              <span>Review Note</span>
              <input value={reviewNote} onChange={(event) => setReviewNote(event.target.value)} placeholder="optional" />
            </label>
            <label className="admin-checkbox admin-checkbox--inline">
              <input
                type="checkbox"
                checked={regenerateOnReject}
                onChange={(event) => setRegenerateOnReject(event.target.checked)}
              />
              Regenerate on reject
            </label>
          </div>
          <div className="admin-actions">
            <button
              className="button secondary"
              disabled={busyAction !== null || !puzzleId.trim() || !hasAdminToken}
              onClick={() =>
                runAction("approve", () =>
                  approvePuzzle(puzzleId.trim(), {
                    note: reviewNote.trim() || undefined,
                  }),
                )
              }
            >
              Approve Puzzle
            </button>
            <button
              className="button clear"
              disabled={busyAction !== null || !puzzleId.trim() || !hasAdminToken}
              onClick={() =>
                runAction("reject", () =>
                  rejectPuzzle(puzzleId.trim(), {
                    note: reviewNote.trim() || undefined,
                    regenerate: regenerateOnReject,
                  }),
                )
              }
            >
              Reject Puzzle
            </button>
          </div>
        </section>

        <section className="card">
          <h3>Jobs</h3>
          {loading ? <p>Loading jobs…</p> : null}
          <div className="admin-table-wrap">
            <table className="admin-table">
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Type</th>
                  <th>Status</th>
                  <th>Date</th>
                  <th>Created</th>
                  <th>Finished</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <tr key={job.id}>
                    <td>{job.id}</td>
                    <td>{job.type}</td>
                    <td>{job.status}</td>
                    <td>{job.date ?? "—"}</td>
                    <td>{formatTimestamp(job.createdAt)}</td>
                    <td>{formatTimestamp(job.finishedAt)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {actionResult ? (
          <section className="card">
            <h3>Last Action Result</h3>
            <pre className="admin-result">{actionResult}</pre>
          </section>
        ) : null}
      </section>
    </Layout>
  );
}
