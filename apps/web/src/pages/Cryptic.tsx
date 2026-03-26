import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ClipboardEvent, CSSProperties, FormEvent, KeyboardEvent } from "react";
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
const CRYPTIC_PROGRESS_VERSION = 2;
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
const HINT_KEYS = ["definition", "fodder", "indicators"] as const;

type OutcomeState = "in_progress" | "solved" | "revealed" | "gave_up";
type HintKey = (typeof HINT_KEYS)[number];
type RevealedHints = Record<HintKey, boolean>;
type TileLayoutItem =
  | {
      type: "tile";
      index: number;
    }
  | {
      type: "separator";
      kind: "gap" | "hyphen";
      value: string;
    };
type DerivedHint = {
  title: string;
  text: string;
  terms: string[];
};
type CrypticProgressSnapshot = {
  version: 2;
  updatedAt: string;
  guess: string;
  guessTiles: string[];
  revealedHints: RevealedHints;
  revealedLetters: number[];
  hintTitle: string;
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

function normalizeTileValue(input: string) {
  const normalized = normalizeGuess(input);
  return normalized ? normalized[0] : "";
}

function parseTimestamp(value: string | null | undefined): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

function emptyRevealedHints(): RevealedHints {
  return {
    definition: false,
    fodder: false,
    indicators: false,
  };
}

function parseRevealedHints(value: unknown): RevealedHints {
  if (!value || typeof value !== "object") return emptyRevealedHints();
  const raw = value as Record<string, unknown>;
  return {
    definition: raw.definition === true,
    fodder: raw.fodder === true,
    indicators: raw.indicators === true,
  };
}

function parseGuessTiles(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => normalizeTileValue(String(item ?? "")));
}

function parseRevealedLetters(value: unknown): number[] {
  if (!Array.isArray(value)) return [];
  const seen = new Set<number>();
  for (const item of value) {
    const index = Number(item);
    if (Number.isInteger(index) && index >= 0) {
      seen.add(index);
    }
  }
  return [...seen].sort((left, right) => left - right);
}

function parseCrypticProgressSnapshot(value: unknown): CrypticProgressSnapshot | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Record<string, unknown>;
  const outcomeRaw = raw.outcome;
  const outcome: OutcomeState =
    outcomeRaw === "solved" || outcomeRaw === "revealed" || outcomeRaw === "gave_up" ? outcomeRaw : "in_progress";
  return {
    version: 2,
    updatedAt: typeof raw.updatedAt === "string" ? raw.updatedAt : new Date().toISOString(),
    guess: typeof raw.guess === "string" ? raw.guess : "",
    guessTiles: parseGuessTiles(raw.guessTiles),
    revealedHints: parseRevealedHints(raw.revealedHints),
    revealedLetters: parseRevealedLetters(raw.revealedLetters),
    hintTitle: typeof raw.hintTitle === "string" ? raw.hintTitle : "",
    hintText: typeof raw.hintText === "string" ? raw.hintText : "",
    outcome,
  };
}

function coerceGuessTiles(snapshot: CrypticProgressSnapshot | null, tileCount: number) {
  const next = Array.from({ length: tileCount }, () => "");
  if (!snapshot || tileCount <= 0) return next;

  if (snapshot.guessTiles.length > 0) {
    snapshot.guessTiles.slice(0, tileCount).forEach((value, index) => {
      next[index] = normalizeTileValue(value);
    });
    return next;
  }

  const compactGuess = normalizeGuess(snapshot.guess).slice(0, tileCount);
  compactGuess.split("").forEach((value, index) => {
    next[index] = value;
  });
  return next;
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

function metadataStrings(value: unknown): string[] {
  if (typeof value === "string") {
    const trimmed = value.trim();
    return trimmed ? [trimmed] : [];
  }
  if (Array.isArray(value)) {
    return value.flatMap((item) => metadataStrings(item));
  }
  if (value && typeof value === "object") {
    const textValue = (value as Record<string, unknown>).text;
    return metadataStrings(textValue);
  }
  return [];
}

function uniqueTerms(values: string[]) {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    const trimmed = value.trim();
    const key = trimmed.toLowerCase();
    if (!trimmed || seen.has(key)) continue;
    seen.add(key);
    out.push(trimmed);
  }
  return out;
}

function metadataTerms(metadata: Record<string, unknown>, keys: string[]) {
  return uniqueTerms(keys.flatMap((key) => metadataStrings(metadata[key])));
}

function joinHintTerms(terms: string[]) {
  if (terms.length === 0) return "";
  if (terms.length === 1) return terms[0];
  if (terms.length === 2) return `${terms[0]} and ${terms[1]}`;
  return `${terms.slice(0, -1).join(", ")}, and ${terms[terms.length - 1]}`;
}

function buildDefinitionHint(entry: PuzzleEntry | null): DerivedHint {
  if (!entry) {
    return { title: "Definition", text: "Definition hint unavailable.", terms: [] };
  }
  const metadata = (entry.wordplayMetadata ?? {}) as Record<string, unknown>;
  const explanation = metadataStrings(metadata.definitionText ?? metadata.definition_text ?? metadata.defText ?? metadata.def_text)[0];
  const terms = metadataTerms(metadata, ["definition", "def"]);

  if (explanation) {
    return { title: "Definition", text: explanation, terms };
  }
  if (terms.length > 0) {
    return {
      title: "Definition",
      text: `Definition: ${joinHintTerms(terms)}.`,
      terms,
    };
  }
  return {
    title: "Definition",
    text: "No explicit definition is stored for this clue yet. The straight definition is usually at one end of the clue.",
    terms: [],
  };
}

function buildIndicatorHint(entry: PuzzleEntry | null): DerivedHint {
  if (!entry) {
    return { title: "Indicator", text: "Indicator hint unavailable.", terms: [] };
  }
  const metadata = (entry.wordplayMetadata ?? {}) as Record<string, unknown>;
  const indicators = metadataTerms(metadata, ["indicator", "indicators"]);

  if (indicators.length > 0) {
    return {
      title: "Indicator",
      text:
        indicators.length === 1
          ? `Indicator: ${indicators[0]}.`
          : `Indicators: ${joinHintTerms(indicators)}.`,
      terms: indicators,
    };
  }

  if (entry.mechanism === "charade") {
    return {
      title: "Indicator",
      text: "This is a charade clue, so it may not have a dedicated manipulation indicator. Build the answer from smaller parts in sequence.",
      terms: [],
    };
  }
  if (entry.mechanism === "anagram") {
    return {
      title: "Indicator",
      text: "An explicit anagram indicator is not stored yet. Look for a word suggesting movement, disorder, or rearrangement.",
      terms: [],
    };
  }
  if (entry.mechanism === "hidden") {
    return {
      title: "Indicator",
      text: "An explicit hidden-word indicator is not stored yet. Look for wording that suggests the answer is concealed inside other text.",
      terms: [],
    };
  }
  if (entry.mechanism === "deletion") {
    return {
      title: "Indicator",
      text: "An explicit deletion indicator is not stored yet. Look for wording that suggests removing or dropping letters.",
      terms: [],
    };
  }
  return {
    title: "Indicator",
    text: "No explicit indicator metadata is stored for this clue yet.",
    terms: [],
  };
}

function buildFodderHint(entry: PuzzleEntry | null): DerivedHint {
  if (!entry) {
    return { title: "Fodder", text: "Fodder hint unavailable.", terms: [] };
  }
  const metadata = (entry.wordplayMetadata ?? {}) as Record<string, unknown>;
  const fodderTerms = metadataTerms(metadata, ["fodder", "fodders", "components", "masked_components", "surface"]);
  const removeTerms = metadataTerms(metadata, ["remove"]);
  const terms = uniqueTerms([...fodderTerms, ...removeTerms]);

  if (fodderTerms.length > 0 || removeTerms.length > 0) {
    const parts: string[] = [];
    if (fodderTerms.length > 0) {
      parts.push(`Fodder: ${joinHintTerms(fodderTerms)}.`);
    }
    if (removeTerms.length > 0) {
      parts.push(`Remove: ${joinHintTerms(removeTerms)}.`);
    }
    return {
      title: "Fodder",
      text: parts.join(" "),
      terms,
    };
  }

  if (entry.mechanism === "hidden") {
    return {
      title: "Fodder",
      text: "No explicit hidden-word source is stored yet. For a hidden clue, the answer will appear consecutively inside other clue text.",
      terms: [],
    };
  }
  if (entry.mechanism === "charade") {
    return {
      title: "Fodder",
      text: "No explicit component list is stored yet. For a charade clue, look for smaller building blocks that join together to make the answer.",
      terms: [],
    };
  }
  return {
    title: "Fodder",
    text: "No explicit fodder metadata is stored for this clue yet.",
    terms: [],
  };
}

function explanationDetails(entry: PuzzleEntry): string[] {
  const metadata = (entry.wordplayMetadata ?? {}) as Record<string, unknown>;
  const details: string[] = [];

  if (entry.mechanism === "anagram") {
    const indicator = metadataTerms(metadata, ["indicator", "indicators"]);
    const fodder = metadataTerms(metadata, ["fodder"]);
    if (indicator.length > 0) details.push(`Indicator: ${joinHintTerms(indicator)}.`);
    if (fodder.length > 0) details.push(`Fodder: ${joinHintTerms(fodder)}.`);
    return details;
  }

  if (entry.mechanism === "deletion") {
    const indicator = metadataTerms(metadata, ["indicator", "indicators"]);
    const fodder = metadataTerms(metadata, ["fodder"]);
    const remove = metadataTerms(metadata, ["remove"]);
    if (indicator.length > 0) details.push(`Indicator: ${joinHintTerms(indicator)}.`);
    if (fodder.length > 0) details.push(`Fodder: ${joinHintTerms(fodder)}.`);
    if (remove.length > 0) details.push(`Remove: ${joinHintTerms(remove)}.`);
    return details;
  }

  if (entry.mechanism === "charade") {
    const components = metadataTerms(metadata, ["masked_components", "components"]);
    const indicator = metadataTerms(metadata, ["indicator", "indicators"]);
    if (components.length > 0) details.push(`Components: ${joinHintTerms(components)}.`);
    if (indicator.length > 0) details.push(`Join indicator: ${joinHintTerms(indicator)}.`);
    return details;
  }

  if (entry.mechanism === "hidden") {
    const indicator = metadataTerms(metadata, ["indicator", "indicators"]);
    const surface = metadataTerms(metadata, ["surface"]);
    if (indicator.length > 0) details.push(`Indicator: ${joinHintTerms(indicator)}.`);
    if (surface.length > 0) details.push(`Hidden-string surface: ${joinHintTerms(surface)}.`);
    return details;
  }

  return details;
}

function buildTileLayout(enumeration: string | null | undefined, tileCount: number): TileLayoutItem[] {
  const fallback = Array.from({ length: tileCount }, (_, index) => ({ type: "tile", index }) as TileLayoutItem);
  const compact = (enumeration ?? "").trim();
  if (!compact) return fallback;

  const tokens = compact.match(/\d+|[,-]/g);
  if (!tokens) return fallback;

  const layout: TileLayoutItem[] = [];
  let tileIndex = 0;
  for (let index = 0; index < tokens.length; index += 1) {
    const token = tokens[index];
    if (!/^\d+$/.test(token)) continue;

    const count = Number(token);
    if (!Number.isInteger(count) || count <= 0) return fallback;

    for (let offset = 0; offset < count; offset += 1) {
      layout.push({ type: "tile", index: tileIndex });
      tileIndex += 1;
    }

    const nextToken = tokens[index + 1];
    if (nextToken === ",") {
      layout.push({ type: "separator", kind: "gap", value: "" });
    } else if (nextToken === "-") {
      layout.push({ type: "separator", kind: "hyphen", value: "-" });
    }
  }

  return tileIndex === tileCount ? layout : fallback;
}

function hashSeed(input: string) {
  let hash = 2166136261;
  for (let index = 0; index < input.length; index += 1) {
    hash ^= input.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function mulberry32(seed: number) {
  return () => {
    let next = (seed += 0x6d2b79f5);
    next = Math.imul(next ^ (next >>> 15), next | 1);
    next ^= next + Math.imul(next ^ (next >>> 7), next | 61);
    return ((next ^ (next >>> 14)) >>> 0) / 4294967296;
  };
}

function buildRevealOrder(tileCount: number, seedSource: string) {
  const order = Array.from({ length: tileCount }, (_, index) => index);
  const random = mulberry32(hashSeed(seedSource));
  for (let index = order.length - 1; index > 0; index -= 1) {
    const swapIndex = Math.floor(random() * (index + 1));
    [order[index], order[swapIndex]] = [order[swapIndex], order[index]];
  }
  return order;
}

function countRevealedHints(revealedHints: RevealedHints) {
  return HINT_KEYS.reduce((count, key) => count + (revealedHints[key] ? 1 : 0), 0);
}

export default function Cryptic() {
  const isDev = import.meta.env.DEV;
  const { playerToken } = useAuth();
  const [searchParams] = useSearchParams();
  const [puzzle, setPuzzle] = useState<Puzzle | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [guessTiles, setGuessTiles] = useState<string[]>([]);
  const [message, setMessage] = useState<string>("Fill the tiles and check when ready.");
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [isCelebrating, setIsCelebrating] = useState(false);
  const [celebrationKey, setCelebrationKey] = useState(0);
  const [hintTitle, setHintTitle] = useState("");
  const [hintText, setHintText] = useState("");
  const [revealedHints, setRevealedHints] = useState<RevealedHints>(emptyRevealedHints());
  const [revealedLetters, setRevealedLetters] = useState<number[]>([]);
  const [isHintPanelOpen, setIsHintPanelOpen] = useState(false);
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
  const tileRefs = useRef<Array<HTMLInputElement | null>>([]);
  const selectedDate = searchParams.get("date") ?? undefined;

  const entry = puzzle?.entries?.[0] ?? null;
  const contestModeEnabled = Boolean(puzzle?.metadata.contestMode);
  const solutionChars = useMemo(() => normalizeGuess(entry?.answer ?? "").split(""), [entry?.answer]);
  const solutionLength = solutionChars.length;
  const hasOutcome = outcome !== "in_progress";
  const clueLength = entry?.length ?? solutionLength;
  const clueText = entry?.clue ?? "Cryptic clue unavailable.";
  const clueMechanism = entry?.mechanism ?? "n/a";
  const clueEnumeration = entry?.enumeration ?? `${clueLength}`;
  const tileLayout = useMemo(() => buildTileLayout(entry?.enumeration, solutionLength), [entry?.enumeration, solutionLength]);
  const revealOrder = useMemo(
    () => buildRevealOrder(solutionLength, `${puzzle?.id ?? ""}:${entry?.id ?? ""}:${entry?.answer ?? ""}`),
    [entry?.answer, entry?.id, puzzle?.id, solutionLength],
  );
  const derivedHints = useMemo(
    () => ({
      definition: buildDefinitionHint(entry),
      fodder: buildFodderHint(entry),
      indicators: buildIndicatorHint(entry),
    }),
    [entry],
  );
  const hintUsageCount = revealedLetters.length + countRevealedHints(revealedHints);
  const nextRevealLetterIndex = useMemo(
    () => revealOrder.find((index) => !revealedLetters.includes(index)) ?? null,
    [revealOrder, revealedLetters],
  );
  const isGuessComplete = solutionLength > 0 && guessTiles.length === solutionLength && guessTiles.every((value) => value.length === 1);
  const normalizedGuess = useMemo(() => guessTiles.join(""), [guessTiles]);
  const puzzleByline = typeof puzzle?.metadata.byline === "string" ? puzzle.metadata.byline.trim() : "";
  const puzzleConstructor = typeof puzzle?.metadata.constructor === "string" ? puzzle.metadata.constructor.trim() : "";
  const puzzleEditor = typeof puzzle?.metadata.editor === "string" ? puzzle.metadata.editor.trim() : "";
  const puzzleNotes = typeof puzzle?.metadata.notes === "string" ? puzzle.metadata.notes.trim() : "";
  const puzzleBylineLabel = puzzleByline || (puzzleConstructor ? `By ${puzzleConstructor}` : "");
  const hasPuzzleEditorial = Boolean(puzzleBylineLabel || puzzleEditor || puzzleNotes);
  const clueMetaId = puzzle ? `cryptic-clue-meta-${puzzle.id}` : "cryptic-clue-meta";
  const hintStatusId = puzzle ? `cryptic-hint-status-${puzzle.id}` : "cryptic-hint-status";
  const explanationId = puzzle ? `cryptic-explanation-${puzzle.id}` : "cryptic-explanation";

  const focusTile = useCallback((index: number | null) => {
    if (index === null || index < 0) return;
    tileRefs.current[index]?.focus();
  }, []);

  const firstEditableTile = useCallback(
    (startIndex = 0, revealedOverride: number[] = revealedLetters) => {
      if (solutionLength <= 0) return null;
      for (let index = startIndex; index < solutionLength; index += 1) {
        if (!revealedOverride.includes(index)) return index;
      }
      for (let index = 0; index < startIndex; index += 1) {
        if (!revealedOverride.includes(index)) return index;
      }
      return null;
    },
    [revealedLetters, solutionLength],
  );

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
    setSessionId(getOrCreateSessionId());
    setError(null);
    setGuessTiles([]);
    setMessage("Fill the tiles and check when ready.");
    setHintTitle("");
    setHintText("");
    setRevealedHints(emptyRevealedHints());
    setRevealedLetters([]);
    setIsHintPanelOpen(false);
    setOutcome("in_progress");
    setFeedbackPendingDownvote(false);
    setFeedbackReasonTags([]);
    setFeedbackSubmitted(false);
    setFeedbackStatus("Rate this clue to help improve quality.");
    setProgressUpdatedAt(new Date().toISOString());
    hydratedProgressRef.current = false;
    skipProgressBumpRef.current = false;
    tileRefs.current = [];
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
  }, [entry, puzzle, track]);

  useEffect(() => {
    if (!puzzle?.id) return;
    const localKey = `${CRYPTIC_PROGRESS_STORAGE_PREFIX}:${puzzle.id}:state:v${CRYPTIC_PROGRESS_VERSION}`;
    const cloudKey = `cryptic:puzzle:${puzzle.id}`;
    let cancelled = false;

    const applySnapshot = (snapshot: CrypticProgressSnapshot) => {
      const nextGuessTiles = coerceGuessTiles(snapshot, solutionLength);
      const validRevealedLetters = snapshot.revealedLetters.filter((index) => index >= 0 && index < solutionLength);
      for (const index of validRevealedLetters) {
        nextGuessTiles[index] = solutionChars[index] ?? "";
      }

      skipProgressBumpRef.current = true;
      setGuessTiles(nextGuessTiles);
      setHintTitle(snapshot.hintTitle);
      setHintText(snapshot.hintText);
      setRevealedHints(snapshot.revealedHints);
      setRevealedLetters(validRevealedLetters);
      setOutcome(snapshot.outcome);
      setIsHintPanelOpen(false);
      if (snapshot.outcome === "solved") {
        setMessage("Correct. Explanation unlocked.");
      } else if (snapshot.outcome === "revealed") {
        setMessage(`Revealed: ${entry?.answer ?? snapshot.guess}`);
      } else if (snapshot.outcome === "gave_up") {
        setMessage("Attempt marked as given up. Explanation unlocked.");
      } else {
        setMessage(nextGuessTiles.some(Boolean) ? "Progress restored." : "Fill the tiles and check when ready.");
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
        version: 2,
        updatedAt: new Date().toISOString(),
        guess: "",
        guessTiles: Array.from({ length: solutionLength }, () => ""),
        revealedHints: emptyRevealedHints(),
        revealedLetters: [],
        hintTitle: "",
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
  }, [entry?.answer, playerToken, puzzle?.id, solutionChars, solutionLength]);

  useEffect(() => {
    if (!hydratedProgressRef.current) return;
    if (skipProgressBumpRef.current) {
      skipProgressBumpRef.current = false;
      return;
    }
    setProgressUpdatedAt(new Date().toISOString());
  }, [guessTiles, hintText, hintTitle, outcome, revealedHints, revealedLetters]);

  useEffect(() => {
    if (!puzzle?.id || !hydratedProgressRef.current) return;
    const snapshot: CrypticProgressSnapshot = {
      version: 2,
      updatedAt: progressUpdatedAt,
      guess: guessTiles.join(""),
      guessTiles,
      revealedHints,
      revealedLetters,
      hintTitle,
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
  }, [guessTiles, hintText, hintTitle, outcome, playerToken, progressUpdatedAt, puzzle?.id, revealedHints, revealedLetters]);

  const updateGuessTile = useCallback(
    (index: number, rawValue: string, moveFocus = false) => {
      const value = normalizeTileValue(rawValue);
      setGuessTiles((current) => {
        const base = current.length === solutionLength ? [...current] : Array.from({ length: solutionLength }, (_, tileIndex) => current[tileIndex] ?? "");
        base[index] = value;
        return base;
      });

      if (value && moveFocus) {
        const nextTile = firstEditableTile(index + 1);
        if (nextTile !== null && nextTile !== index) {
          focusTile(nextTile);
        }
      }
    },
    [firstEditableTile, focusTile, solutionLength],
  );

  const onTileKeyDown = useCallback(
    (index: number, event: KeyboardEvent<HTMLInputElement>) => {
      if (revealedLetters.includes(index) || hasOutcome) return;

      if (/^[a-z0-9]$/i.test(event.key)) {
        event.preventDefault();
        updateGuessTile(index, event.key, true);
        return;
      }

      if (event.key === "Backspace") {
        event.preventDefault();
        if (guessTiles[index]) {
          updateGuessTile(index, "", false);
          focusTile(index);
          return;
        }
        const previousTile = (() => {
          for (let tileIndex = index - 1; tileIndex >= 0; tileIndex -= 1) {
            if (!revealedLetters.includes(tileIndex)) return tileIndex;
          }
          return null;
        })();
        if (previousTile !== null) {
          updateGuessTile(previousTile, "", false);
          focusTile(previousTile);
        }
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        const previousTile = (() => {
          for (let tileIndex = index - 1; tileIndex >= 0; tileIndex -= 1) {
            if (!revealedLetters.includes(tileIndex)) return tileIndex;
          }
          return null;
        })();
        focusTile(previousTile);
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        const nextTile = firstEditableTile(index + 1);
        focusTile(nextTile);
      }
    },
    [firstEditableTile, focusTile, guessTiles, hasOutcome, revealedLetters, updateGuessTile],
  );

  const onTilePaste = useCallback(
    (index: number, event: ClipboardEvent<HTMLInputElement>) => {
      const pasted = normalizeGuess(event.clipboardData.getData("text"));
      if (!pasted) return;
      event.preventDefault();

      setGuessTiles((current) => {
        const next = current.length === solutionLength ? [...current] : Array.from({ length: solutionLength }, (_, tileIndex) => current[tileIndex] ?? "");
        let insertIndex = index;
        for (const character of pasted) {
          while (insertIndex < solutionLength && revealedLetters.includes(insertIndex)) {
            insertIndex += 1;
          }
          if (insertIndex >= solutionLength) break;
          next[insertIndex] = character;
          insertIndex += 1;
        }
        return next;
      });

      const nextActive = firstEditableTile(index + pasted.length);
      if (nextActive !== null) {
        focusTile(nextActive);
      }
    },
    [firstEditableTile, focusTile, revealedLetters, solutionLength],
  );

  const onSubmitGuess = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      if (!entry) return;

      await track("guess_submit", {
        length: normalizedGuess.length,
        filledTiles: guessTiles.filter(Boolean).length,
        complete: isGuessComplete,
        mechanism: entry.mechanism,
      });

      if (!isGuessComplete) {
        setMessage("Fill every tile before checking.");
        return;
      }

      if (normalizeGuess(entry.answer) === normalizedGuess) {
        triggerCelebration();
        setOutcome("solved");
        setIsHintPanelOpen(false);
        setMessage("Correct. Explanation unlocked.");
        return;
      }

      setMessage("Not it yet. Keep going.");
    },
    [entry, guessTiles, isGuessComplete, normalizedGuess, track, triggerCelebration],
  );

  const onShowHint = useCallback(
    async (key: HintKey) => {
      if (!entry || hasOutcome || contestModeEnabled) return;
      const hint = derivedHints[key];
      const alreadyRevealed = revealedHints[key];

      setHintTitle(hint.title);
      setHintText(hint.text);
      setMessage(`${hint.title} hint shown.`);
      setIsHintPanelOpen(false);
      if (!alreadyRevealed) {
        setRevealedHints((current) => ({
          ...current,
          [key]: true,
        }));
      }

      await track("hint_click", {
        hintType: key,
        repeated: alreadyRevealed,
        guessLength: normalizedGuess.length,
        mechanism: entry.mechanism,
      });
    },
    [contestModeEnabled, derivedHints, entry, hasOutcome, normalizedGuess.length, revealedHints, track],
  );

  const onRevealLetter = useCallback(async () => {
    if (!entry || hasOutcome || contestModeEnabled || nextRevealLetterIndex === null) return;

    const nextRevealedLetters = uniqueTerms([...revealedLetters.map(String), String(nextRevealLetterIndex)]).map((value) => Number(value));
    setGuessTiles((current) => {
      const next = current.length === solutionLength ? [...current] : Array.from({ length: solutionLength }, (_, index) => current[index] ?? "");
      next[nextRevealLetterIndex] = solutionChars[nextRevealLetterIndex] ?? "";
      return next;
    });
    setRevealedLetters(nextRevealedLetters);
    setHintTitle("Reveal Letter");
    setHintText(`Letter ${nextRevealLetterIndex + 1} revealed.`);
    setIsHintPanelOpen(false);

    if (nextRevealedLetters.length >= solutionLength) {
      setOutcome("revealed");
      setMessage(`Revealed: ${entry.answer}`);
    } else {
      setMessage("Letter revealed.");
      const nextActive = firstEditableTile(nextRevealLetterIndex + 1, nextRevealedLetters);
      focusTile(nextActive);
    }

    await track("hint_click", {
      hintType: "letter",
      letterIndex: nextRevealLetterIndex + 1,
      guessLength: normalizedGuess.length,
      mechanism: entry.mechanism,
    });
  }, [
    contestModeEnabled,
    entry,
    firstEditableTile,
    focusTile,
    hasOutcome,
    nextRevealLetterIndex,
    normalizedGuess.length,
    revealedLetters,
    solutionChars,
    solutionLength,
    track,
  ]);

  const onReveal = useCallback(async () => {
    if (!entry) return;
    if (contestModeEnabled) {
      setMessage("Contest mode is active. Reveal is disabled.");
      return;
    }
    setGuessTiles(solutionChars);
    setOutcome("revealed");
    setIsHintPanelOpen(false);
    setMessage(`Revealed: ${entry.answer}`);
    await track("reveal_click", {
      hintCount: hintUsageCount,
      guessLength: normalizedGuess.length,
      mechanism: entry.mechanism,
    });
  }, [contestModeEnabled, entry, hintUsageCount, normalizedGuess.length, solutionChars, track]);

  const onAbandon = useCallback(async () => {
    if (!entry) return;
    if (contestModeEnabled) {
      setMessage("Contest mode is active. Give up is disabled.");
      return;
    }
    setOutcome("gave_up");
    setIsHintPanelOpen(false);
    setMessage("Attempt marked as given up. Explanation unlocked.");
    await track("abandon", {
      guessLength: normalizedGuess.length,
      hintCount: hintUsageCount,
      mechanism: entry.mechanism,
    });
  }, [contestModeEnabled, entry, hintUsageCount, normalizedGuess.length, track]);

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
            Contest mode: hints and reveal are locked for this clue.
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
                <span>Enumeration: ({clueEnumeration})</span>
                <span>Hints used: {hintUsageCount}</span>
              </div>
              {isDev ? (
                <div className="cryptic-dev-meta">
                  <span>Mechanism: {clueMechanism}</span>
                  <span>Answer length: {solutionLength}</span>
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
              <div className="cryptic-entry-header">
                <label className="cryptic-eyebrow" htmlFor={puzzle ? `cryptic-entry-${puzzle.id}-0` : "cryptic-entry"}>
                  Your Answer
                </label>
                <span className="cryptic-entry-counter">{isGuessComplete ? "Ready to check" : `${guessTiles.filter(Boolean).length}/${solutionLength} filled`}</span>
              </div>

              <div className="cryptic-entry-grid" role="group" aria-label={`Answer entry (${clueEnumeration})`}>
                {tileLayout.map((item, itemIndex) =>
                  item.type === "tile" ? (
                    <input
                      key={`tile-${item.index}`}
                      id={puzzle ? `cryptic-entry-${puzzle.id}-${item.index}` : `cryptic-entry-${item.index}`}
                      ref={(node) => {
                        tileRefs.current[item.index] = node;
                      }}
                      className={[
                        "cryptic-entry-tile",
                        revealedLetters.includes(item.index) ? "is-revealed" : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      value={guessTiles[item.index] ?? ""}
                      onChange={(event) => updateGuessTile(item.index, event.target.value, false)}
                      onKeyDown={(event) => onTileKeyDown(item.index, event)}
                      onPaste={(event) => onTilePaste(item.index, event)}
                      disabled={hasOutcome || revealedLetters.includes(item.index)}
                      inputMode="text"
                      autoComplete="off"
                      spellCheck={false}
                      maxLength={1}
                      aria-label={`Letter ${item.index + 1} of ${solutionLength}`}
                    />
                  ) : (
                    <span
                      key={`separator-${itemIndex}`}
                      className={`cryptic-entry-separator cryptic-entry-separator--${item.kind}`}
                      aria-hidden="true"
                    >
                      {item.value}
                    </span>
                  ),
                )}
              </div>

              <div className="cryptic-actions">
                <button className="button" type="submit" disabled={hasOutcome}>
                  Check Answer
                </button>
                <button
                  className="button secondary"
                  type="button"
                  onClick={() => setIsHintPanelOpen((current) => !current)}
                  disabled={hasOutcome || contestModeEnabled}
                >
                  {isHintPanelOpen ? "Hide Hints" : "Hints"}
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

              {isHintPanelOpen && !contestModeEnabled && !hasOutcome ? (
                <div className="cryptic-hint-picker">
                  <button
                    className={`button secondary cryptic-hint-picker__button${revealedHints.definition ? " is-used" : ""}`}
                    type="button"
                    onClick={() => void onShowHint("definition")}
                  >
                    Definition
                  </button>
                  <button
                    className={`button secondary cryptic-hint-picker__button${revealedHints.fodder ? " is-used" : ""}`}
                    type="button"
                    onClick={() => void onShowHint("fodder")}
                  >
                    Fodder
                  </button>
                  <button
                    className={`button secondary cryptic-hint-picker__button${revealedHints.indicators ? " is-used" : ""}`}
                    type="button"
                    onClick={() => void onShowHint("indicators")}
                  >
                    Indicator
                  </button>
                  <button
                    className="button secondary cryptic-hint-picker__button"
                    type="button"
                    onClick={() => void onRevealLetter()}
                    disabled={nextRevealLetterIndex === null}
                  >
                    Reveal Letter
                  </button>
                </div>
              ) : null}

              <div className="cryptic-hint" id={hintStatusId} role="status" aria-live="polite">
                {contestModeEnabled ? (
                  "Contest mode is active. Hint and reveal controls are unavailable."
                ) : hintText ? (
                  <>
                    {hintTitle ? <strong>{hintTitle}: </strong> : null}
                    {hintText}
                  </>
                ) : (
                  "Use Hints to reveal the definition, fodder, indicator, or one answer letter at a time."
                )}
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
