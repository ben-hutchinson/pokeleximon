import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import Layout from "../components/Layout";
import {
  getDailyPuzzle,
  getPuzzleProgress,
  postCrypticClueFeedback,
  postCrypticTelemetry,
  putPuzzleProgress,
  type CrypticTelemetryEventType,
  type Puzzle,
  type PuzzleEntry,
} from "../api/puzzles";

const SESSION_KEY = "cryptic:session-id";
const CRYPTIC_PROGRESS_VERSION = 1;
const CRYPTIC_PROGRESS_STORAGE_PREFIX = "cryptic:puzzle";
const CELEBRATION_PARTICLES = Array.from({ length: 16 }, (_, index) => ({
  angle: `${index * 22.5}deg`,
  delay: `${(index % 4) * 35}ms`,
}));
const DOWNVOTE_REASON_TAGS = [
  { id: "definition_too_obvious", label: "Definition too obvious" },
  { id: "wordplay_unclear", label: "Wordplay unclear" },
  { id: "surface_awkward", label: "Surface awkward" },
  { id: "too_easy", label: "Too easy" },
  { id: "too_hard", label: "Too hard" },
  { id: "answer_leak", label: "Answer leak" },
  { id: "not_fair", label: "Not fair" },
] as const;

type OutcomeState = "in_progress" | "solved" | "revealed" | "gave_up";

type CrypticProgressSnapshot = {
  version: 1;
  updatedAt: string;
  guess: string;
  hintStep: number;
  hintText: string;
  outcome: OutcomeState;
};

function getOrCreateSessionId() {
  const existing = localStorage.getItem(SESSION_KEY);
  if (existing) return existing;
  const next = `sess_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
  localStorage.setItem(SESSION_KEY, next);
  return next;
}

function normalizeGuess(input: string) {
  return input.toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function parseCrypticProgressSnapshot(value: unknown): CrypticProgressSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Partial<CrypticProgressSnapshot>;
  const outcomeRaw = raw.outcome;
  const outcome: OutcomeState =
    outcomeRaw === "solved" || outcomeRaw === "revealed" || outcomeRaw === "gave_up" ? outcomeRaw : "in_progress";
  return {
    version: 1,
    updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt : new Date().toISOString(),
    guess: typeof raw.guess === "string" ? raw.guess : "",
    hintStep: Number.isFinite(raw.hintStep) ? Math.max(0, Math.min(2, Number(raw.hintStep))) : 0,
    hintText: typeof raw.hintText === "string" ? raw.hintText : "",
    outcome,
  };
}

function mechanismLabel(mechanism: string | null | undefined): string {
  const value = (mechanism ?? "").toLowerCase();
  const mapping: Record<string, string> = {
    anagram: "Anagram",
    charade: "Charade",
    deletion: "Deletion",
    hidden: "Hidden word",
    manual: "Manual cryptic",
  };
  return mapping[value] ?? "Cryptic wordplay";
}

function hintStepOne(entry: PuzzleEntry | null): string {
  if (!entry) return "Read the clue for a straight definition at one end and wordplay at the other.";
  const enumeration = entry.enumeration ?? `${entry.length}`;
  return `Non-spoiler hint: think definition + wordplay split. Enumeration is (${enumeration}).`;
}

function hintStepTwo(entry: PuzzleEntry | null): string {
  if (!entry) return "Stronger hint unavailable.";
  const metadata = (entry.wordplayMetadata ?? {}) as Record<string, unknown>;

  if (entry.mechanism === "anagram") {
    const indicator = typeof metadata.indicator === "string" ? metadata.indicator : "anagram indicator";
    return `Stronger hint: look for an ${indicator} signal and rearrange the indicated fodder.`;
  }
  if (entry.mechanism === "deletion") {
    const indicator = typeof metadata.indicator === "string" ? metadata.indicator : "deletion indicator";
    return `Stronger hint: deletion clue. Remove letters using the ${indicator} indicator.`;
  }
  if (entry.mechanism === "charade") {
    return "Stronger hint: charade clue. Build the answer from smaller word parts in sequence.";
  }
  if (entry.mechanism === "hidden") {
    return "Stronger hint: hidden clue. The answer appears consecutively inside surface text.";
  }

  if (entry.wordplayPlan) {
    return "Stronger hint: use the stored breakdown after reveal if you get stuck.";
  }

  return "Stronger hint: no mechanism is stored for this clue, so focus on where the straight definition begins or ends.";
}

function explanationDetails(entry: PuzzleEntry): string[] {
  const metadata = (entry.wordplayMetadata ?? {}) as Record<string, unknown>;
  const details: string[] = [];

  if (entry.mechanism === "anagram") {
    const indicator = typeof metadata.indicator === "string" ? metadata.indicator : "";
    const fodder = typeof metadata.fodder === "string" ? metadata.fodder : "";
    if (indicator) details.push(`Indicator: ${indicator}.`);
    if (fodder) details.push(`Fodder: ${fodder}.`);
    return details;
  }

  if (entry.mechanism === "deletion") {
    const indicator = typeof metadata.indicator === "string" ? metadata.indicator : "";
    const fodder = typeof metadata.fodder === "string" ? metadata.fodder : "";
    const remove = typeof metadata.remove === "string" ? metadata.remove : "";
    if (indicator) details.push(`Indicator: ${indicator}.`);
    if (fodder) details.push(`Fodder: ${fodder}.`);
    if (remove) details.push(`Remove: ${remove}.`);
    return details;
  }

  if (entry.mechanism === "charade") {
    const componentsRaw = metadata.masked_components;
    if (Array.isArray(componentsRaw)) {
      const cleaned = componentsRaw
        .map((value) => String(value).trim())
        .filter((value) => value.length > 0);
      if (cleaned.length > 0) {
        details.push(`Components: ${cleaned.join(" + ")}.`);
      }
    }
    const indicator = typeof metadata.indicator === "string" ? metadata.indicator : "";
    if (indicator) details.push(`Join indicator: ${indicator}.`);
    return details;
  }

  if (entry.mechanism === "hidden") {
    const indicator = typeof metadata.indicator === "string" ? metadata.indicator : "";
    const surface = typeof metadata.surface === "string" ? metadata.surface : "";
    if (indicator) details.push(`Indicator: ${indicator}.`);
    if (surface) details.push(`Hidden-string surface: ${surface}.`);
    return details;
  }

  return details;
}

export default function Cryptic() {
  const isDev = import.meta.env.DEV;
  const { playerToken } = useAuth();
  const [searchParams] = useSearchParams();
  const [puzzle, setPuzzle] = useState<Puzzle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guess, setGuess] = useState("");
  const [message, setMessage] = useState<string>("Enter your guess and submit.");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isCelebrating, setIsCelebrating] = useState(false);
  const [celebrationKey, setCelebrationKey] = useState(0);
  const [hintStep, setHintStep] = useState(0);
  const [hintText, setHintText] = useState<string>("");
  const [outcome, setOutcome] = useState<OutcomeState>("in_progress");
  const [feedbackPendingDownvote, setFeedbackPendingDownvote] = useState(false);
  const [feedbackReasonTags, setFeedbackReasonTags] = useState<string[]>([]);
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false);
  const [feedbackStatus, setFeedbackStatus] = useState<string>("Rate this clue to help improve quality.");
  const [progressUpdatedAt, setProgressUpdatedAt] = useState<string>(new Date().toISOString());
  const trackedPuzzleId = useRef<string | null>(null);
  const celebrationTimeoutRef = useRef<number | null>(null);
  const cloudSaveTimeoutRef = useRef<number | null>(null);
  const hydratedProgressRef = useRef(false);
  const skipProgressBumpRef = useRef(false);
  const selectedDate = searchParams.get("date") ?? undefined;

  const entry = puzzle?.entries?.[0] ?? null;
  const hasOutcome = outcome !== "in_progress";
  const contestModeEnabled = Boolean(puzzle?.metadata.contestMode);

  useEffect(() => {
    setSessionId(getOrCreateSessionId());
    setError(null);
    setGuess("");
    setMessage("Enter your guess and submit.");
    setHintStep(0);
    setHintText("");
    setOutcome("in_progress");
    setFeedbackPendingDownvote(false);
    setFeedbackReasonTags([]);
    setFeedbackSubmitted(false);
    setFeedbackStatus("Rate this clue to help improve quality.");
    setProgressUpdatedAt(new Date().toISOString());
    hydratedProgressRef.current = false;
    skipProgressBumpRef.current = false;
    if (cloudSaveTimeoutRef.current !== null) {
      window.clearTimeout(cloudSaveTimeoutRef.current);
      cloudSaveTimeoutRef.current = null;
    }

    getDailyPuzzle("cryptic", { date: selectedDate })
      .then(setPuzzle)
      .catch((err) => setError(err.message));
  }, [selectedDate]);

  useEffect(() => {
    return () => {
      if (celebrationTimeoutRef.current !== null) {
        window.clearTimeout(celebrationTimeoutRef.current);
      }
      if (cloudSaveTimeoutRef.current !== null) {
        window.clearTimeout(cloudSaveTimeoutRef.current);
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

  const track = useCallback(
    async (eventType: CrypticTelemetryEventType, eventValue: Record<string, unknown> = {}) => {
      if (!puzzle) return;
      try {
        await postCrypticTelemetry({
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
        // Telemetry failures should not interrupt gameplay.
      }
    },
    [contestModeEnabled, puzzle, sessionId],
  );

  useEffect(() => {
    if (!puzzle || trackedPuzzleId.current === puzzle.id) return;
    trackedPuzzleId.current = puzzle.id;
    void track("page_view", { title: puzzle.title });
    if (entry) {
      void track("clue_view", {
        entryId: entry.id,
        length: entry.length,
      });
    }
  }, [puzzle, entry, track]);

  useEffect(() => {
    if (!puzzle?.id) return;
    const localKey = `${CRYPTIC_PROGRESS_STORAGE_PREFIX}:${puzzle.id}:state:v${CRYPTIC_PROGRESS_VERSION}`;
    const cloudKey = `cryptic:puzzle:${puzzle.id}`;
    let cancelled = false;

    const applySnapshot = (snapshot: CrypticProgressSnapshot) => {
      skipProgressBumpRef.current = true;
      setGuess(snapshot.guess);
      setHintStep(snapshot.hintStep);
      setHintText(snapshot.hintText);
      setOutcome(snapshot.outcome);
      if (snapshot.outcome === "solved") {
        setMessage("Correct. Explanation unlocked.");
      } else if (snapshot.outcome === "revealed") {
        setMessage(`Revealed: ${snapshot.guess}`);
      } else if (snapshot.outcome === "gave_up") {
        setMessage("Attempt marked as given up. Explanation unlocked.");
      } else {
        setMessage(snapshot.guess ? "Progress restored." : "Enter your guess and submit.");
      }
      setProgressUpdatedAt(snapshot.updatedAt);
    };

    const localSnapshot = (() => {
      try {
        const raw = localStorage.getItem(localKey);
        if (!raw) return null;
        return parseCrypticProgressSnapshot(JSON.parse(raw));
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
        guess: "",
        hintStep: 0,
        hintText: "",
        outcome: "in_progress",
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
        const remoteSnapshot = parseCrypticProgressSnapshot(remote?.progress ?? null);
        const localTs = parseTimestamp(localSnapshot?.updatedAt);
        const remoteTs = parseTimestamp(remoteSnapshot?.updatedAt);

        if (remoteSnapshot && remoteTs > localTs) {
          applySnapshot(remoteSnapshot);
        } else if (localSnapshot) {
          await putPuzzleProgress({
            key: cloudKey,
            gameType: "cryptic",
            puzzleId: puzzle.id,
            progress: localSnapshot,
            clientUpdatedAt: localSnapshot.updatedAt,
            playerToken: token,
          });
        }
      } catch {
        // Keep local progress as fallback.
      } finally {
        if (!cancelled) hydratedProgressRef.current = true;
      }
    };

    void sync();
    return () => {
      cancelled = true;
    };
  }, [playerToken, puzzle?.id]);

  useEffect(() => {
    if (!hydratedProgressRef.current) return;
    if (skipProgressBumpRef.current) {
      skipProgressBumpRef.current = false;
      return;
    }
    setProgressUpdatedAt(new Date().toISOString());
  }, [guess, hintStep, hintText, outcome]);

  useEffect(() => {
    if (!puzzle?.id || !hydratedProgressRef.current) return;
    const snapshot: CrypticProgressSnapshot = {
      version: 1,
      updatedAt: progressUpdatedAt,
      guess,
      hintStep,
      hintText,
      outcome,
    };
    const localKey = `${CRYPTIC_PROGRESS_STORAGE_PREFIX}:${puzzle.id}:state:v${CRYPTIC_PROGRESS_VERSION}`;
    localStorage.setItem(localKey, JSON.stringify(snapshot));

    const token = playerToken.trim();
    if (!token) return;
    if (cloudSaveTimeoutRef.current !== null) {
      window.clearTimeout(cloudSaveTimeoutRef.current);
    }
    cloudSaveTimeoutRef.current = window.setTimeout(() => {
      void putPuzzleProgress({
        key: `cryptic:puzzle:${puzzle.id}`,
        gameType: "cryptic",
        puzzleId: puzzle.id,
        progress: snapshot,
        clientUpdatedAt: snapshot.updatedAt,
        playerToken: token,
      }).catch(() => {
        // Retry on later edits.
      });
    }, 650);
  }, [guess, hintStep, hintText, outcome, progressUpdatedAt, puzzle?.id, playerToken]);

  const clueLength = entry?.length ?? 0;
  const clueText = entry?.clue ?? "Cryptic clue unavailable.";
  const clueMechanism = entry?.mechanism ?? "n/a";
  const clueEnumeration = entry?.enumeration ?? `${clueLength}`;
  const puzzleByline = typeof puzzle?.metadata.byline === "string" ? puzzle.metadata.byline.trim() : "";
  const puzzleConstructor = typeof puzzle?.metadata.constructor === "string" ? puzzle.metadata.constructor.trim() : "";
  const puzzleEditor = typeof puzzle?.metadata.editor === "string" ? puzzle.metadata.editor.trim() : "";
  const puzzleNotes = typeof puzzle?.metadata.notes === "string" ? puzzle.metadata.notes.trim() : "";
  const puzzleBylineLabel = puzzleByline || (puzzleConstructor ? `By ${puzzleConstructor}` : "");
  const hasPuzzleEditorial = Boolean(puzzleBylineLabel || puzzleEditor || puzzleNotes);
  const clueMetaId = puzzle ? `cryptic-clue-meta-${puzzle.id}` : "cryptic-clue-meta";
  const guessInputId = puzzle ? `cryptic-guess-${puzzle.id}` : "cryptic-guess";
  const hintStatusId = puzzle ? `cryptic-hint-status-${puzzle.id}` : "cryptic-hint-status";
  const explanationId = puzzle ? `cryptic-explanation-${puzzle.id}` : "cryptic-explanation";

  const normalizedGuess = useMemo(() => normalizeGuess(guess), [guess]);

  const onSubmitGuess = useCallback(
    async (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!entry) return;

      const matchesLength = normalizedGuess.length === entry.length;
      await track("guess_submit", {
        length: normalizedGuess.length,
        matchesLength,
      });

      if (!normalizedGuess) {
        setMessage("Type a guess first.");
        return;
      }

      const answerMatches = normalizeGuess(entry.answer) === normalizedGuess;
      if (answerMatches) {
        triggerCelebration();
        setOutcome("solved");
        setMessage("Correct. Explanation unlocked.");
        return;
      }

      if (matchesLength) {
        setMessage("Length matches. Keep going.");
      } else {
        setMessage(`Length mismatch: expected ${entry.length}.`);
      }
    },
    [entry, normalizedGuess, track, triggerCelebration],
  );

  const onCheckLength = useCallback(async () => {
    if (!entry) return;
    if (contestModeEnabled) {
      setMessage("Contest mode is active. Length check is disabled.");
      return;
    }
    const matchesLength = normalizedGuess.length === entry.length;
    const answerMatches = normalizeGuess(entry.answer) === normalizedGuess;
    await track("check_click", {
      length: normalizedGuess.length,
      matchesLength,
      answerMatches,
    });
    if (answerMatches) {
      triggerCelebration();
      setOutcome("solved");
      setMessage("Correct. Explanation unlocked.");
      return;
    }
    setMessage(matchesLength ? "Length check passed." : `Length check failed: expected ${entry.length}.`);
  }, [contestModeEnabled, entry, normalizedGuess, track, triggerCelebration]);

  const onHintOne = useCallback(async () => {
    if (!entry || hasOutcome || contestModeEnabled) return;
    const text = hintStepOne(entry);
    setHintStep((current) => Math.max(current, 1));
    setHintText(text);
    setMessage("Hint 1 shown.");
    await track("hint_click", {
      step: 1,
      guessLength: normalizedGuess.length,
      mechanism: entry.mechanism,
    });
  }, [contestModeEnabled, entry, hasOutcome, normalizedGuess.length, track]);

  const onHintTwo = useCallback(async () => {
    if (!entry || hasOutcome || contestModeEnabled) return;
    const text = hintStepTwo(entry);
    setHintStep(2);
    setHintText(text);
    setMessage("Hint 2 shown.");
    await track("hint_click", {
      step: 2,
      guessLength: normalizedGuess.length,
      mechanism: entry.mechanism,
    });
  }, [contestModeEnabled, entry, hasOutcome, normalizedGuess.length, track]);

  const onReveal = useCallback(async () => {
    if (!entry) return;
    if (contestModeEnabled) {
      setMessage("Contest mode is active. Reveal is disabled.");
      return;
    }
    setGuess(entry.answer);
    setOutcome("revealed");
    setMessage(`Revealed: ${entry.answer}`);
    await track("reveal_click", {
      hintStep,
      guessLength: normalizedGuess.length,
      mechanism: entry.mechanism,
    });
  }, [contestModeEnabled, entry, hintStep, normalizedGuess.length, track]);

  const onAbandon = useCallback(async () => {
    if (!entry) return;
    if (contestModeEnabled) {
      setMessage("Contest mode is active. Give up is disabled.");
      return;
    }
    setOutcome("gave_up");
    setMessage("Attempt marked as given up. Explanation unlocked.");
    await track("abandon", { guessLength: normalizedGuess.length, hintStep, mechanism: entry.mechanism });
  }, [contestModeEnabled, entry, hintStep, normalizedGuess.length, track]);

  const submitClueFeedback = useCallback(
    async (rating: "up" | "down", reasonTags: string[]) => {
      if (!puzzle || !entry || !sessionId || feedbackSubmitted) return;
      try {
        const response = await postCrypticClueFeedback({
          puzzleId: puzzle.id,
          entryId: entry.id,
          rating,
          reasonTags,
          sessionId,
          mechanism: entry.mechanism ?? null,
          clueText: entry.clue,
          clientTs: new Date().toISOString(),
        });
        setFeedbackSubmitted(true);
        setFeedbackPendingDownvote(false);
        if (response.duplicate) {
          setFeedbackStatus("Feedback already recorded for this clue in your session.");
          return;
        }
        setFeedbackStatus("Thanks. Your clue feedback was recorded.");
      } catch {
        setFeedbackStatus("Could not submit feedback right now. Please try again.");
      }
    },
    [entry, feedbackSubmitted, puzzle, sessionId],
  );

  const onFeedbackUp = useCallback(() => {
    void submitClueFeedback("up", []);
  }, [submitClueFeedback]);

  const onFeedbackDown = useCallback(() => {
    if (feedbackSubmitted) return;
    setFeedbackPendingDownvote(true);
    setFeedbackStatus("Optional: pick reason tags, then submit your downvote.");
  }, [feedbackSubmitted]);

  const toggleReasonTag = useCallback((tag: string) => {
    setFeedbackReasonTags((current) => {
      if (current.includes(tag)) {
        return current.filter((value) => value !== tag);
      }
      return [...current, tag];
    });
  }, []);

  const onSubmitDownvote = useCallback(() => {
    void submitClueFeedback("down", feedbackReasonTags);
  }, [feedbackReasonTags, submitClueFeedback]);

  const explanationLines = useMemo(() => {
    if (!entry) return [];
    const lines: string[] = [];
    if (entry.wordplayPlan) {
      lines.push(entry.wordplayPlan);
    }
    lines.push(...explanationDetails(entry));
    return lines;
  }, [entry]);

  return (
    <Layout>
      <section className="page-section" aria-labelledby="cryptic-heading" aria-busy={!puzzle || !entry}>
        <div className="section-header section-header--with-actions">
          <div>
            <h2 id="cryptic-heading">Cryptic Clue</h2>
            <p>Work today&apos;s clue, then open the cryptic archive without leaving the cryptic experience.</p>
          </div>
          <div className="section-header__actions">
            <Link className="button ghost" to="/archive?gameType=cryptic">
              Cryptic Archive
            </Link>
          </div>
        </div>
        {hasPuzzleEditorial ? (
          <section className="card puzzle-editorial puzzle-editorial--standalone" aria-label="Puzzle editorial metadata">
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
            Contest mode: hints, checks, and reveal are locked for this clue.
          </div>
        ) : null}

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        {!puzzle || !entry ? (
          <div className="cryptic-mini" role="status" aria-live="polite" aria-label="Loading cryptic clue">
            <section className="card cryptic-card skeleton-card">
              <div className="skeleton-line skeleton-line--heading" />
              <div className="skeleton-line" />
              <div className="skeleton-line" />
              <div className="skeleton-line skeleton-line--short" />
            </section>
            <section className="card cryptic-card skeleton-card">
              <div className="skeleton-line skeleton-line--heading" />
              <div className="skeleton-line" />
              <div className="skeleton-line skeleton-line--button" />
              <div className="skeleton-line" />
            </section>
          </div>
        ) : (
          <div className="cryptic-mini">
            {isCelebrating ? (
              <div key={celebrationKey} className="celebration-burst celebration-burst--inline" aria-hidden="true">
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
            <section className="card cryptic-card" aria-labelledby="cryptic-clue-heading">
              <div className="cryptic-eyebrow">Clue</div>
              <div id="cryptic-clue-heading" className="cryptic-clue">
                {clueText}
              </div>
              <div id={clueMetaId} className="cryptic-meta">
                <span>Length: ({clueLength})</span>
              </div>
              {isDev ? (
                <div className="cryptic-dev-meta">
                  <span>Mechanism: {clueMechanism}</span>
                  <span>Enumeration: ({clueEnumeration})</span>
                </div>
              ) : null}

              <div className="cryptic-feedback" aria-label="Clue quality feedback">
                <div className="cryptic-feedback__title">Clue Quality</div>
                <div className="cryptic-feedback__actions">
                  <button className="button secondary" type="button" disabled={feedbackSubmitted} onClick={onFeedbackUp}>
                    Thumbs Up
                  </button>
                  <button className="button secondary" type="button" disabled={feedbackSubmitted} onClick={onFeedbackDown}>
                    Thumbs Down
                  </button>
                </div>
                {feedbackPendingDownvote && !feedbackSubmitted ? (
                  <div className="cryptic-feedback__reasons">
                    {DOWNVOTE_REASON_TAGS.map((tag) => (
                      <label key={tag.id} className="cryptic-feedback__reason">
                        <input
                          type="checkbox"
                          checked={feedbackReasonTags.includes(tag.id)}
                          onChange={() => toggleReasonTag(tag.id)}
                        />
                        <span>{tag.label}</span>
                      </label>
                    ))}
                    <button className="button" type="button" onClick={onSubmitDownvote}>
                      Submit Downvote
                    </button>
                  </div>
                ) : null}
                <div className="cryptic-feedback__status" role="status" aria-live="polite">
                  {feedbackStatus}
                </div>
              </div>
            </section>

            <form className="card cryptic-card" onSubmit={onSubmitGuess}>
              <label className="cryptic-eyebrow" htmlFor={guessInputId}>
                Your Answer
              </label>
              <input
                id={guessInputId}
                className="cryptic-input"
                value={guess}
                onChange={(event) => setGuess(event.target.value)}
                placeholder="Type your guess"
                autoComplete="off"
                spellCheck={false}
                aria-describedby={clueMetaId}
              />

              <div className="cryptic-actions">
                <button className="button" type="submit" disabled={hasOutcome}>
                  Submit Guess
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={onCheckLength}
                  disabled={hasOutcome || contestModeEnabled}
                >
                  Check Length
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={onHintOne}
                  disabled={hasOutcome || contestModeEnabled || hintStep >= 1}
                >
                  Hint 1
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={onHintTwo}
                  disabled={hasOutcome || contestModeEnabled || hintStep < 1 || hintStep >= 2}
                >
                  Hint 2
                </button>
                <button
                  className="button reveal"
                  type="button"
                  onClick={onReveal}
                  disabled={contestModeEnabled || outcome === "revealed"}
                >
                  Reveal
                </button>
                <button className="button clear" type="button" onClick={onAbandon} disabled={hasOutcome || contestModeEnabled}>
                  Give Up
                </button>
              </div>

              <div className="cryptic-hint" id={hintStatusId} role="status" aria-live="polite">
                {contestModeEnabled
                  ? "Contest mode is active. Hint and reveal controls are unavailable."
                  : hintText || "Hints: use Hint 1 for a non-spoiler nudge, then Hint 2 for a stronger steer."}
              </div>

              <div className="cryptic-message" role="status" aria-live="polite">
                {message}
              </div>
            </form>

            {hasOutcome ? (
              <section className="card cryptic-card cryptic-explanation" aria-labelledby={explanationId}>
                <h3 id={explanationId} className="cryptic-explanation__title">
                  Explanation
                </h3>
                <div className="cryptic-explanation__meta">
                  <span>Mechanism: {mechanismLabel(entry.mechanism)}</span>
                  <span>Enumeration: ({clueEnumeration})</span>
                </div>
                <div className="cryptic-explanation__answer">Answer: {entry.answer}</div>
                <ul className="cryptic-explanation__list" aria-live="polite">
                  {explanationLines.length > 0 ? (
                    explanationLines.map((line, index) => <li key={index}>{line}</li>)
                  ) : (
                    <li>No detailed breakdown available for this clue.</li>
                  )}
                </ul>
              </section>
            ) : null}
          </div>
        )}
      </section>
    </Layout>
  );
}
