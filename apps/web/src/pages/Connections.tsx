import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Layout from "../components/Layout";
import { FEATURE_CONNECTIONS_ENABLED } from "../featureFlags";
import {
  getDailyPuzzle,
  getPuzzleProgress,
  postConnectionsTelemetry,
  putPuzzleProgress,
  type ConnectionsTelemetryEventType,
  type Puzzle,
} from "../api/puzzles";

const SESSION_KEY = "connections:session-id";
const CONNECTIONS_PROGRESS_VERSION = 1;
const CONNECTIONS_PROGRESS_STORAGE_PREFIX = "connections:puzzle";
const MAX_MISTAKES = 4;

type OutcomeState = "in_progress" | "completed" | "failed";

type ConnectionsProgressSnapshot = {
  version: 1;
  updatedAt: string;
  selectedTileIds: string[];
  solvedGroupIds: string[];
  mistakes: number;
  outcome: OutcomeState;
  tileOrder: string[];
  statusMessage: string;
};

type ConnectionsDifficultyTone = "yellow" | "green" | "blue" | "purple" | "neutral";

function getOrCreateConnectionsSessionId() {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const next = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  localStorage.setItem(SESSION_KEY, next);
  return next;
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function randomShuffle<T>(items: T[]): T[] {
  const out = items.slice();
  for (let index = out.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(Math.random() * (index + 1));
    const current = out[index];
    out[index] = out[swapIndex];
    out[swapIndex] = current;
  }
  return out;
}

function parseProgressSnapshot(value: unknown): ConnectionsProgressSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<ConnectionsProgressSnapshot>;
  const outcomeRaw = raw.outcome;
  const outcome: OutcomeState =
    outcomeRaw === "completed" || outcomeRaw === "failed" || outcomeRaw === "in_progress" ? outcomeRaw : "in_progress";
  return {
    version: 1,
    updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt : new Date().toISOString(),
    selectedTileIds: Array.isArray(raw.selectedTileIds) ? raw.selectedTileIds.map(String) : [],
    solvedGroupIds: Array.isArray(raw.solvedGroupIds) ? raw.solvedGroupIds.map(String) : [],
    mistakes: Number.isFinite(raw.mistakes) ? Math.max(0, Math.min(MAX_MISTAKES, Number(raw.mistakes))) : 0,
    outcome,
    tileOrder: Array.isArray(raw.tileOrder) ? raw.tileOrder.map(String) : [],
    statusMessage: typeof raw.statusMessage === "string" ? raw.statusMessage : "",
  };
}

function normalizeTileOrder(order: string[], allTileIds: string[]): string[] {
  const valid = order.filter((tileId) => allTileIds.includes(tileId));
  const missing = allTileIds.filter((tileId) => !valid.includes(tileId));
  return [...valid, ...missing];
}

function getConnectionsDifficultyTone(difficulty: string | null | undefined): ConnectionsDifficultyTone {
  const normalizedDifficulty = (difficulty ?? "").toLowerCase();
  switch (normalizedDifficulty) {
    case "yellow":
    case "green":
    case "blue":
    case "purple":
      return normalizedDifficulty as Exclude<ConnectionsDifficultyTone, "neutral">;
    default:
      return "neutral";
  }
}

export default function Connections() {
  const { playerToken } = useAuth();
  const [searchParams] = useSearchParams();
  const [puzzle, setPuzzle] = useState<Puzzle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [selectedTileIds, setSelectedTileIds] = useState<string[]>([]);
  const [solvedGroupIds, setSolvedGroupIds] = useState<string[]>([]);
  const [mistakes, setMistakes] = useState(0);
  const [outcome, setOutcome] = useState<OutcomeState>("in_progress");
  const [tileOrder, setTileOrder] = useState<string[]>([]);
  const [statusMessage, setStatusMessage] = useState("Pick four tiles that share a connection.");
  const [progressUpdatedAt, setProgressUpdatedAt] = useState<string>(new Date().toISOString());

  const trackedPuzzleId = useRef<string | null>(null);
  const hasSentCompleted = useRef(false);
  const hasSentAbandon = useRef(false);
  const hydratedProgressRef = useRef(false);
  const skipProgressBumpRef = useRef(false);
  const cloudSaveTimeoutRef = useRef<number | null>(null);
  const selectedDate = searchParams.get("date") ?? undefined;

  const connections = puzzle?.metadata.connections ?? null;
  const difficultyOrder = useMemo(
    () => connections?.difficultyOrder ?? ["yellow", "green", "blue", "purple"],
    [connections?.difficultyOrder],
  );
  const allGroups = useMemo(() => connections?.groups ?? [], [connections?.groups]);
  const allTiles = useMemo(() => connections?.tiles ?? [], [connections?.tiles]);
  const allTileIds = useMemo(() => allTiles.map((tile) => tile.id), [allTiles]);
  const tileById = useMemo(() => new Map(allTiles.map((tile) => [tile.id, tile])), [allTiles]);
  const groupById = useMemo(() => new Map(allGroups.map((group) => [group.id, group])), [allGroups]);
  const solvedGroupIdSet = useMemo(() => new Set(solvedGroupIds), [solvedGroupIds]);
  const canInteract = outcome === "in_progress";
  const showCompletedLayout = outcome === "completed";

  const orderedSolvedGroups = useMemo(() => {
    const rankByDifficulty = new Map(difficultyOrder.map((value, index) => [value, index]));
    return solvedGroupIds
      .map((groupId) => groupById.get(groupId))
      .filter((group): group is NonNullable<typeof group> => Boolean(group))
      .sort(
        (left, right) => (rankByDifficulty.get(left.difficulty) ?? 999) - (rankByDifficulty.get(right.difficulty) ?? 999),
      );
  }, [difficultyOrder, groupById, solvedGroupIds]);

  const unsolvedTiles = useMemo(
    () =>
      normalizeTileOrder(tileOrder, allTileIds)
        .map((tileId) => tileById.get(tileId) ?? null)
        .filter((tile): tile is NonNullable<typeof tile> => Boolean(tile))
        .filter((tile) => !solvedGroupIdSet.has(tile.groupId ?? "")),
    [allTileIds, solvedGroupIdSet, tileById, tileOrder],
  );

  const revealedGroups = useMemo(() => {
    if (outcome !== "failed") return [];
    return allGroups.filter((group) => !solvedGroupIdSet.has(group.id));
  }, [allGroups, outcome, solvedGroupIdSet]);

  const track = useCallback(
    async (eventType: ConnectionsTelemetryEventType, eventValue: Record<string, unknown> = {}) => {
      if (!puzzle || puzzle.gameType !== "connections") return;
      try {
        await postConnectionsTelemetry({
          puzzleId: puzzle.id,
          eventType,
          sessionId,
          eventValue,
          clientTs: new Date().toISOString(),
        });
      } catch {
        // Telemetry should never block gameplay.
      }
    },
    [puzzle, sessionId],
  );

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) {
      setError("Connections is not enabled for this environment.");
      return;
    }

    setSessionId(getOrCreateConnectionsSessionId());
  }, []);

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) return;

    setError(null);
    setPuzzle(null);
    setSelectedTileIds([]);
    setSolvedGroupIds([]);
    setMistakes(0);
    setOutcome("in_progress");
    setTileOrder([]);
    setStatusMessage("Pick four tiles that share a connection.");
    setProgressUpdatedAt(new Date().toISOString());
    trackedPuzzleId.current = null;
    hasSentCompleted.current = false;
    hasSentAbandon.current = false;
    hydratedProgressRef.current = false;
    skipProgressBumpRef.current = false;
    if (cloudSaveTimeoutRef.current !== null) {
      window.clearTimeout(cloudSaveTimeoutRef.current);
      cloudSaveTimeoutRef.current = null;
    }

    getDailyPuzzle("connections", { date: selectedDate, redactAnswers: false })
      .then((nextPuzzle) => {
        if (nextPuzzle.gameType !== "connections" || !nextPuzzle.metadata.connections) {
          throw new Error("Connections payload is unavailable for this date.");
        }
        setPuzzle(nextPuzzle);
      })
      .catch((err) => setError(err.message));
  }, [selectedDate]);

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) return;
    if (!puzzle || trackedPuzzleId.current === puzzle.id) return;
    trackedPuzzleId.current = puzzle.id;
    void track("page_view", { title: puzzle.title });
  }, [puzzle, track]);

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) return;
    if (!puzzle?.id || !connections) return;
    const localKey = `${CONNECTIONS_PROGRESS_STORAGE_PREFIX}:${puzzle.id}:state:v${CONNECTIONS_PROGRESS_VERSION}`;
    const cloudKey = `connections:puzzle:${puzzle.id}`;
    const baseTileOrder = allTileIds.slice();
    let cancelled = false;

    const applySnapshot = (snapshot: ConnectionsProgressSnapshot) => {
      const normalizedSolved = snapshot.solvedGroupIds.filter((groupId) => groupById.has(groupId));
      const normalizedSelection = snapshot.selectedTileIds
        .filter((tileId) => baseTileOrder.includes(tileId))
        .filter((tileId) => !normalizedSolved.includes(tileById.get(tileId)?.groupId ?? ""))
        .slice(0, 4);

      skipProgressBumpRef.current = true;
      setSolvedGroupIds(normalizedSolved);
      setSelectedTileIds(normalizedSelection);
      setMistakes(Math.max(0, Math.min(MAX_MISTAKES, snapshot.mistakes)));
      setOutcome(snapshot.outcome);
      setTileOrder(normalizeTileOrder(snapshot.tileOrder, baseTileOrder));
      setStatusMessage(snapshot.statusMessage || "Pick four tiles that share a connection.");
      setProgressUpdatedAt(snapshot.updatedAt);
    };

    const localSnapshot = (() => {
      try {
        const raw = localStorage.getItem(localKey);
        if (!raw) return null;
        return parseProgressSnapshot(JSON.parse(raw));
      } catch {
        return null;
      }
    })();

    if (localSnapshot) {
      applySnapshot(localSnapshot);
    } else {
      applySnapshot({
        version: 1,
        updatedAt: new Date().toISOString(),
        selectedTileIds: [],
        solvedGroupIds: [],
        mistakes: 0,
        outcome: "in_progress",
        tileOrder: baseTileOrder,
        statusMessage: "Pick four tiles that share a connection.",
      });
    }

    const sync = async () => {
      const token = playerToken.trim();
      if (!token) {
        hydratedProgressRef.current = true;
        return;
      }
      try {
        const remote = await getPuzzleProgress({ key: cloudKey, playerToken: token });
        if (cancelled) return;
        const remoteSnapshot = parseProgressSnapshot(remote?.progress ?? null);
        const localTs = parseTimestamp(localSnapshot?.updatedAt);
        const remoteTs = parseTimestamp(remoteSnapshot?.updatedAt);
        if (remoteSnapshot && remoteTs > localTs) {
          applySnapshot(remoteSnapshot);
        } else if (localSnapshot) {
          await putPuzzleProgress({
            key: cloudKey,
            gameType: "connections",
            puzzleId: puzzle.id,
            progress: localSnapshot,
            clientUpdatedAt: localSnapshot.updatedAt,
            playerToken: token,
          });
        }
      } catch {
        // Keep local state if remote sync fails.
      } finally {
        if (!cancelled) hydratedProgressRef.current = true;
      }
    };

    void sync();
    return () => {
      cancelled = true;
    };
  }, [allTileIds, connections, groupById, playerToken, puzzle?.id, tileById]);

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) return;
    if (!hydratedProgressRef.current) return;
    if (skipProgressBumpRef.current) {
      skipProgressBumpRef.current = false;
      return;
    }
    setProgressUpdatedAt(new Date().toISOString());
  }, [selectedTileIds, solvedGroupIds, mistakes, outcome, tileOrder, statusMessage]);

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) return;
    if (!puzzle?.id || !hydratedProgressRef.current) return;
    const snapshot: ConnectionsProgressSnapshot = {
      version: 1,
      updatedAt: progressUpdatedAt,
      selectedTileIds,
      solvedGroupIds,
      mistakes,
      outcome,
      tileOrder: normalizeTileOrder(tileOrder, allTileIds),
      statusMessage,
    };
    localStorage.setItem(
      `${CONNECTIONS_PROGRESS_STORAGE_PREFIX}:${puzzle.id}:state:v${CONNECTIONS_PROGRESS_VERSION}`,
      JSON.stringify(snapshot),
    );

    const token = playerToken.trim();
    if (!token) return;
    if (cloudSaveTimeoutRef.current !== null) {
      window.clearTimeout(cloudSaveTimeoutRef.current);
    }
    cloudSaveTimeoutRef.current = window.setTimeout(() => {
      void putPuzzleProgress({
        key: `connections:puzzle:${puzzle.id}`,
        gameType: "connections",
        puzzleId: puzzle.id,
        progress: snapshot,
        clientUpdatedAt: snapshot.updatedAt,
        playerToken: token,
      }).catch(() => {
        // Retry on next mutation.
      });
    }, 650);
  }, [allTileIds, mistakes, outcome, playerToken, progressUpdatedAt, puzzle?.id, selectedTileIds, solvedGroupIds, statusMessage, tileOrder]);

  useEffect(() => {
    return () => {
      if (cloudSaveTimeoutRef.current !== null) {
        window.clearTimeout(cloudSaveTimeoutRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (!FEATURE_CONNECTIONS_ENABLED) return;
    return () => {
      if (!puzzle?.id || outcome !== "in_progress" || hasSentAbandon.current) return;
      hasSentAbandon.current = true;
      void track("abandon", { mistakes, solvedGroups: solvedGroupIds.length });
    };
  }, [mistakes, outcome, puzzle?.id, solvedGroupIds.length, track]);

  const toggleTile = (tileId: string) => {
    if (!canInteract) return;
    if (selectedTileIds.includes(tileId)) {
      setSelectedTileIds((current) => current.filter((value) => value !== tileId));
      void track("tile_deselect", { tileId });
      return;
    }
    if (selectedTileIds.length >= 4) {
      setStatusMessage("You can only select four tiles at a time.");
      return;
    }
    setSelectedTileIds((current) => [...current, tileId]);
    void track("tile_select", { tileId });
  };

  const clearSelection = () => {
    if (!canInteract) return;
    setSelectedTileIds([]);
    setStatusMessage("Selection cleared.");
  };

  const shuffleTiles = () => {
    if (!canInteract) return;
    setTileOrder((current) => {
      const normalized = normalizeTileOrder(current, allTileIds);
      const unsolved = normalized.filter((tileId) => !solvedGroupIdSet.has(tileById.get(tileId)?.groupId ?? ""));
      const solved = normalized.filter((tileId) => solvedGroupIdSet.has(tileById.get(tileId)?.groupId ?? ""));
      return [...randomShuffle(unsolved), ...solved];
    });
    setStatusMessage("Tiles shuffled.");
    void track("shuffle", { solvedGroups: solvedGroupIds.length });
  };

  const submitSelection = () => {
    if (!canInteract) return;
    if (selectedTileIds.length !== 4) {
      setStatusMessage("Select exactly four tiles before submitting.");
      return;
    }

    const selectedTiles = selectedTileIds.map((tileId) => tileById.get(tileId)).filter((tile) => Boolean(tile));
    if (selectedTiles.length !== 4) {
      setStatusMessage("Selection is invalid. Try reselecting tiles.");
      setSelectedTileIds([]);
      return;
    }

    void track("submit_group", {
      tileIds: selectedTileIds,
      labels: selectedTiles.map((tile) => tile?.label ?? ""),
    });

    const groupIdCounts = new Map<string, number>();
    for (const tile of selectedTiles) {
      const groupId = tile?.groupId ?? "";
      if (!groupId) continue;
      groupIdCounts.set(groupId, (groupIdCounts.get(groupId) ?? 0) + 1);
    }

    const solvedGroupId = Array.from(groupIdCounts.entries()).find((entry) => entry[1] === 4)?.[0] ?? null;
    if (solvedGroupId && !solvedGroupIdSet.has(solvedGroupId)) {
      const nextSolved = [...solvedGroupIds, solvedGroupId];
      setSolvedGroupIds(nextSolved);
      setSelectedTileIds([]);
      const solvedGroup = groupById.get(solvedGroupId);
      setStatusMessage(`Correct: ${solvedGroup?.title ?? "group solved"}.`);
      void track("solve_group", { groupId: solvedGroupId, mistakes });

      if (nextSolved.length === 4 && !hasSentCompleted.current) {
        hasSentCompleted.current = true;
        setOutcome("completed");
        setStatusMessage("Solved. Nice find across all four groups.");
        void track("completed", { mistakes, solvedGroups: 4 });
      }
      return;
    }

    const oneAwayGroup = Array.from(groupIdCounts.entries()).find(
      ([groupId, count]) => count === 3 && !solvedGroupIdSet.has(groupId),
    )?.[0];
    if (oneAwayGroup) {
      setStatusMessage("One away. Three of those tiles belong together.");
      void track("one_away", { groupId: oneAwayGroup });
    } else {
      setStatusMessage("Not a valid group.");
    }

    const nextMistakes = mistakes + 1;
    setMistakes(nextMistakes);
    setSelectedTileIds([]);
    void track("mistake", { count: nextMistakes });

    if (nextMistakes >= MAX_MISTAKES) {
      setOutcome("failed");
      setStatusMessage("No mistakes remaining. Game over.");
      if (!hasSentAbandon.current) {
        hasSentAbandon.current = true;
        void track("abandon", { reason: "mistake_limit", mistakes: nextMistakes, solvedGroups: solvedGroupIds.length });
      }
    } else if (!oneAwayGroup) {
      setStatusMessage(`Incorrect. ${MAX_MISTAKES - nextMistakes} mistakes remaining.`);
    }
  };

  if (!FEATURE_CONNECTIONS_ENABLED) {
    return (
      <Layout>
        <section className="page-section" aria-labelledby="connections-heading">
          <div className="section-header section-header--with-actions">
            <div>
              <h2 id="connections-heading">Daily Connections</h2>
              <p>
                Connections is not enabled for this environment. Set{" "}
                <code>VITE_FEATURE_CONNECTIONS_ENABLED=true</code> and{" "}
                <code>FEATURE_CONNECTIONS_ENABLED=true</code> in your API env, then restart both services.
              </p>
            </div>
            <div className="section-header__actions">
              <Link className="button ghost" to="/archive?gameType=connections">
                Connections Archive
              </Link>
            </div>
          </div>
        </section>
      </Layout>
    );
  }

  return (
    <Layout>
      <section className="page-section" aria-labelledby="connections-heading">
        <div className="section-header section-header--with-actions">
          <div>
            <h2 id="connections-heading">Daily Connections</h2>
            <p>Find four groups of four. You get four mistakes.</p>
          </div>
          <div className="section-header__actions">
            <Link className="button ghost" to="/archive?gameType=connections">
              Connections Archive
            </Link>
          </div>
        </div>

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        {!puzzle || !connections ? (
          <div className="card">
            <p>Loading connections puzzle…</p>
          </div>
        ) : (
          <div className="connections-shell">
            {!showCompletedLayout ? (
              <>
                <div className="card connections-header">
                  <div className="connections-header__meta">
                    <span className="tag">{puzzle.metadata.difficulty}</span>
                    <span className="timer-chip">
                      <span className="timer-chip__label">Mistakes</span>
                      <span className="timer-chip__value">
                        {mistakes}/{MAX_MISTAKES}
                      </span>
                    </span>
                    <span className="streak-chip">
                      <span className="streak-chip__label">Solved Groups</span>
                      <span className="streak-chip__value">{solvedGroupIds.length}/4</span>
                    </span>
                  </div>
                  <div className="connections-actions">
                    <button
                      className="button secondary"
                      onClick={submitSelection}
                      disabled={!canInteract || selectedTileIds.length !== 4}
                    >
                      Submit Group
                    </button>
                    <button className="button ghost" onClick={shuffleTiles} disabled={!canInteract}>
                      Shuffle
                    </button>
                    <button className="button ghost" onClick={clearSelection} disabled={!canInteract || selectedTileIds.length === 0}>
                      Clear
                    </button>
                  </div>
                  <p className="connections-status" role="status" aria-live="polite">
                    {statusMessage}
                  </p>
                </div>

                <div className="card">
                  <div className="connections-grid" role="grid" aria-label="Connections tiles">
                    {unsolvedTiles.map((tile) => {
                      const selected = selectedTileIds.includes(tile.id);
                      return (
                        <button
                          key={tile.id}
                          type="button"
                          className={`connections-tile${selected ? " is-selected" : ""}`}
                          aria-pressed={selected}
                          onClick={() => toggleTile(tile.id)}
                          disabled={!canInteract}
                        >
                          {tile.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            ) : null}

            {orderedSolvedGroups.length > 0 ? (
              <div className="connections-solved">
                {orderedSolvedGroups.map((group) => (
                  <article
                    key={group.id}
                    className="card connections-group-card"
                    data-difficulty-tone={getConnectionsDifficultyTone(group.difficulty)}
                  >
                    <h3>{group.title}</h3>
                    <p>{group.labels.join(" • ")}</p>
                  </article>
                ))}
              </div>
            ) : null}

            {outcome === "completed" ? (
              <div className="card">
                <h3>Completed</h3>
                <p>You solved all four groups with {mistakes} mistake(s).</p>
                <Link className="button ghost" to="/archive?gameType=connections">
                  Open Connections Archive
                </Link>
              </div>
            ) : null}

            {revealedGroups.length > 0 ? (
              <div className="card">
                <h3>Revealed Groups</h3>
                <div className="connections-solved">
                  {revealedGroups.map((group) => (
                    <article
                      key={group.id}
                      className="card connections-group-card"
                      data-difficulty-tone={getConnectionsDifficultyTone(group.difficulty)}
                    >
                      <h3>{group.title}</h3>
                      <p>{group.labels.join(" • ")}</p>
                    </article>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </section>
    </Layout>
  );
}
