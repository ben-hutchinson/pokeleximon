import { useCallback, useEffect, useState } from "react";
import Layout from "../components/Layout";
import {
  approvePuzzle,
  clearAdminToken,
  generateDraft,
  generatePuzzle,
  getDraft,
  getAdminToken,
  getAnalyticsSummary,
  getReserveStatus,
  listAlerts,
  listJobs,
  publishDraft,
  publishDaily,
  publishPuzzle,
  rollbackDailyPublish,
  rejectPuzzle,
  resolveAlert,
  saveDraft,
  setAdminToken,
  topUpReserve,
  validateDraft,
  type AdminAlert,
  type AdminAnalyticsSummary,
  type AdminDraftPuzzle,
  type AdminDraftValidationResult,
  type AdminJob,
  type AdminReserveItem,
} from "../api/admin";
import type { GameType } from "../api/puzzles";
import { todayIsoInTimezone } from "../utils/date";

type DraftGameType = Extract<GameType, "crossword" | "cryptic">;

function todayIso() {
  return todayIsoInTimezone();
}

function tomorrowIso() {
  const base = new Date(`${todayIso()}T00:00:00Z`);
  base.setUTCDate(base.getUTCDate() + 1);
  return base.toISOString().slice(0, 10);
}

function isDraftGameType(value: GameType): value is DraftGameType {
  return value === "crossword" || value === "cryptic";
}

function isReserveGameType(value: GameType): value is "connections" {
  return value === "connections";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function bulbapediaSearchUrl(answer: string) {
  return `https://bulbapedia.bulbagarden.net/wiki/Special:Search?search=${encodeURIComponent(
    answer.replace(/\s+/g, "_"),
  )}`;
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

function summarizeDraftPuzzleForActionResult(puzzle: AdminDraftPuzzle) {
  return {
    id: puzzle.id,
    date: puzzle.date,
    gameType: puzzle.gameType,
    title: puzzle.title,
    publishedAt: puzzle.publishedAt,
    entryCount: puzzle.entries.length,
    grid: {
      width: puzzle.grid.width,
      height: puzzle.grid.height,
    },
  };
}

function formatActionResult(result: unknown) {
  const replacer = (_key: string, value: unknown) => {
    if (isRecord(value)) {
      const item = value.item;
      if (item && isRecord(item) && Array.isArray(item.entries) && isRecord(item.grid)) {
        return {
          ...value,
          item: summarizeDraftPuzzleForActionResult(item as unknown as AdminDraftPuzzle),
        };
      }
      const draft = value.draft;
      if (draft && isRecord(draft) && Array.isArray(draft.entries) && isRecord(draft.grid)) {
        return {
          ...value,
          draft: summarizeDraftPuzzleForActionResult(draft as unknown as AdminDraftPuzzle),
        };
      }
    }
    return value;
  };

  const serialized = JSON.stringify(result, replacer, 2);
  if (!serialized) return "null";
  return serialized.length > 6000 ? `${serialized.slice(0, 6000)}\n…` : serialized;
}

function isDraftValidationResult(value: unknown): value is AdminDraftValidationResult {
  return (
    isRecord(value) &&
    typeof value.isPublishable === "boolean" &&
    Array.isArray(value.hardFailures) &&
    Array.isArray(value.warnings)
  );
}

function extractDraftValidation(value: unknown): AdminDraftValidationResult | null {
  if (isDraftValidationResult(value)) return value;
  if (isRecord(value) && isDraftValidationResult(value.structuralQuality)) {
    return value.structuralQuality;
  }
  return null;
}

export default function Admin() {
  const [adminTokenInput, setAdminTokenInput] = useState(getAdminToken());
  const [gameType, setGameType] = useState<GameType>("crossword");
  const [date, setDate] = useState(todayIso());
  const [draftDate, setDraftDate] = useState(tomorrowIso());
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
  const [draftPuzzle, setDraftPuzzle] = useState<AdminDraftPuzzle | null>(null);
  const [draftValidation, setDraftValidation] = useState<AdminDraftValidationResult | null>(null);
  const [draftEditor, setDraftEditor] = useState("");
  const [draftNotes, setDraftNotes] = useState("");
  const [draftClues, setDraftClues] = useState<Record<string, string>>({});

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
        getReserveStatus("connections"),
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
      setActionResult(formatActionResult(result));
      await refreshAll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusyAction(null);
    }
  };

  const hasAdminToken = Boolean(getAdminToken());
  const draftModeEnabled = isDraftGameType(gameType);
  const activeDraftGameType: DraftGameType | null = draftModeEnabled ? gameType : null;
  const reserveModeEnabled = isReserveGameType(gameType);

  const syncDraft = useCallback((item: AdminDraftPuzzle, validation?: AdminDraftValidationResult | null) => {
    setDraftPuzzle(item);
    const editorial = item.metadata.editorial as Record<string, unknown> | undefined;
    setDraftEditor(typeof editorial?.editor === "string" ? editorial.editor : "");
    setDraftNotes(typeof editorial?.notes === "string" ? editorial.notes : "");
    setDraftValidation(validation ?? extractDraftValidation(editorial?.validation));
    setDraftClues(
      Object.fromEntries(item.entries.map((entry) => [entry.id, entry.clue ?? ""])),
    );
  }, []);

  const draftEditorial = (draftPuzzle?.metadata.editorial as Record<string, unknown> | undefined) ?? undefined;
  const draftState = typeof draftEditorial?.state === "string" ? draftEditorial.state : "draft";
  const draftStatusLabel = draftPuzzle?.publishedAt ? "published" : draftState;
  const draftAlerts = alerts.filter((alert) => {
    const details = isRecord(alert.details) ? alert.details : {};
    const alertDate = typeof details.date === "string" ? details.date : null;
    return alertDate === draftDate && (alert.alertType === "draft_ready" || alert.alertType === "draft_generation_failed");
  });

  return (
    <Layout>
      <section className="page-section" aria-labelledby="admin-heading">
        <div className="section-header">
          <h2 id="admin-heading">Admin Console</h2>
          <p>Write tomorrow&apos;s crossword and cryptic clues, and manage connections reserve operations when needed.</p>
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
            {!reserveModeEnabled ? null : (
              <>
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
              </>
            )}
          </div>
          <div className="admin-actions">
            {reserveModeEnabled ? (
              <>
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
              </>
            ) : null}
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
            <div>
              <h3>Daily Draft Editor</h3>
              <p className="panel__meta">Day-ahead workflow: generate, write, validate, and publish tomorrow&apos;s puzzle before midnight.</p>
            </div>
          </div>
          {!draftModeEnabled ? (
            <p>Select `crossword` or `cryptic` above to work on the next unpublished draft.</p>
          ) : (
            <>
              <div className="admin-controls__grid">
                <label className="admin-field">
                  <span>Draft Date</span>
                  <input type="date" value={draftDate} onChange={(event) => setDraftDate(event.target.value)} />
                </label>
                <label className="admin-field">
                  <span>Editor</span>
                  <input value={draftEditor} onChange={(event) => setDraftEditor(event.target.value)} placeholder="optional" />
                </label>
                <label className="admin-field">
                  <span>Draft Notes</span>
                  <input value={draftNotes} onChange={(event) => setDraftNotes(event.target.value)} placeholder="optional" />
                </label>
              </div>
              <div className="admin-actions">
                <button
                  className="button"
                  disabled={busyAction !== null || !hasAdminToken}
                  onClick={() =>
                    runAction("generate-draft", async () => {
                      if (!activeDraftGameType) return null;
                      const result = await generateDraft({ date: draftDate, gameType: activeDraftGameType });
                      const fresh = await getDraft({ date: draftDate, gameType: activeDraftGameType });
                      syncDraft(fresh.item);
                      return { ...result, draft: fresh.item };
                    })
                  }
                >
                  Generate Draft
                </button>
                <button
                  className="button secondary"
                  disabled={busyAction !== null || !hasAdminToken}
                  onClick={() =>
                    runAction("load-draft", async () => {
                      if (!activeDraftGameType) return null;
                      const result = await getDraft({ date: draftDate, gameType: activeDraftGameType });
                      syncDraft(result.item);
                      return result;
                    })
                  }
                >
                  Load Draft
                </button>
                <button className="button ghost" type="button" onClick={() => setDraftDate(tomorrowIso())}>
                  Use Tomorrow
                </button>
              </div>

              {draftAlerts.length > 0 ? (
                <div className="admin-list">
                  {draftAlerts.map((alert) => (
                    <div key={alert.id} className={`admin-stat ${alert.alertType === "draft_generation_failed" ? "is-warning" : ""}`}>
                      <div className="admin-stat__title">{alert.alertType}</div>
                      <div>{alert.message}</div>
                      <div>{formatTimestamp(alert.createdAt)}</div>
                    </div>
                  ))}
                </div>
              ) : null}

              {draftPuzzle ? (
                <>
                  <div className="admin-inline-header">
                    <div>
                      <strong>{draftPuzzle.title}</strong>
                      <div className="panel__meta">
                        Status: {draftStatusLabel} · Puzzle ID: {draftPuzzle.id}
                      </div>
                    </div>
                    <div className="admin-actions">
                      <button
                        className="button"
                        disabled={busyAction !== null || !hasAdminToken}
                        onClick={() =>
                          runAction("save-draft", async () => {
                            const result = await saveDraft({
                              puzzleId: draftPuzzle.id,
                              entries: draftPuzzle.entries.map((entry) => ({
                                id: entry.id,
                                clue: draftClues[entry.id] ?? "",
                              })),
                              metadata: {
                                editor: draftEditor.trim() || undefined,
                                notes: draftNotes.trim() || undefined,
                              },
                            });
                            syncDraft(result.item, null);
                            return result;
                          })
                        }
                      >
                        Save Draft
                      </button>
                      <button
                        className="button secondary"
                        disabled={busyAction !== null || !hasAdminToken}
                        onClick={() =>
                          runAction("validate-draft", async () => {
                            const result = await validateDraft(draftPuzzle.id);
                            syncDraft(result.item, result.validation);
                            return result;
                          })
                        }
                      >
                        Validate Draft
                      </button>
                      <button
                        className="button secondary"
                        disabled={busyAction !== null || !hasAdminToken}
                        onClick={() =>
                          runAction("publish-draft", async () => {
                            const saveResult = await saveDraft({
                              puzzleId: draftPuzzle.id,
                              entries: draftPuzzle.entries.map((entry) => ({
                                id: entry.id,
                                clue: draftClues[entry.id] ?? "",
                              })),
                              metadata: {
                                editor: draftEditor.trim() || undefined,
                                notes: draftNotes.trim() || undefined,
                              },
                            });
                            syncDraft(saveResult.item, null);
                            const result = await publishDraft({
                              puzzleId: draftPuzzle.id,
                              contestMode,
                            });
                            syncDraft(result.item, result.validation);
                            return result;
                          })
                        }
                      >
                        Publish Draft
                      </button>
                    </div>
                  </div>

                  {draftValidation ? (
                    <div className={`admin-stat ${draftValidation.isPublishable ? "" : "is-warning"}`}>
                      <div className="admin-stat__title">Validation</div>
                      <div>Publishable: {draftValidation.isPublishable ? "yes" : "no"}</div>
                      <div>Score: {draftValidation.score ?? "—"}</div>
                      <div>Hard failures: {Array.isArray(draftValidation.hardFailures) && draftValidation.hardFailures.length ? draftValidation.hardFailures.join(", ") : "none"}</div>
                      <div>Warnings: {Array.isArray(draftValidation.warnings) && draftValidation.warnings.length ? draftValidation.warnings.join(", ") : "none"}</div>
                    </div>
                  ) : null}

                  <div className="admin-table-wrap">
                    <table className="admin-table">
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>No.</th>
                          <th>Direction</th>
                          <th>Answer</th>
                          <th>Enum</th>
                          <th>Clue</th>
                          <th>Bulbapedia</th>
                        </tr>
                      </thead>
                      <tbody>
                        {draftPuzzle.entries.map((entry) => (
                          <tr key={entry.id}>
                            <td>{entry.id}</td>
                            <td>{entry.number}</td>
                            <td>{entry.direction}</td>
                            <td>{entry.answer}</td>
                            <td>{entry.enumeration ?? entry.length}</td>
                            <td>
                              <input
                                value={draftClues[entry.id] ?? ""}
                                onChange={(event) =>
                                  setDraftClues((current) => ({
                                    ...current,
                                    [entry.id]: event.target.value,
                                  }))
                                }
                                placeholder="Write clue"
                              />
                            </td>
                            <td>
                              <a href={bulbapediaSearchUrl(entry.answer)} target="_blank" rel="noreferrer">
                                Search
                              </a>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </>
              ) : (
                <p>No draft loaded for {gameType} on {draftDate}. Generate it first or load an existing unpublished draft.</p>
              )}
            </>
          )}
        </section>

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

        {reserveModeEnabled ? (
        <div className="admin-layout">
          <section className="card">
            <h3>Connections Reserve</h3>
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
        ) : null}

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
