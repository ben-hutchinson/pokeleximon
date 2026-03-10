import Layout from "../components/Layout";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  getArchive,
  type ArchiveDifficulty,
  type ArchiveGameType,
  type ArchivePage,
} from "../api/puzzles";

const DATE_TOKEN_RE = /^\d{4}-\d{2}-\d{2}$/;

function parseGameTypeFilter(value: string | null): ArchiveGameType {
  if (value === "crossword" || value === "cryptic") return value;
  if (value === "connections") return value;
  return "all";
}

function parseDifficultyFilter(value: string | null): ArchiveDifficulty | "" {
  if (value === "easy" || value === "medium" || value === "hard") return value;
  return "";
}

function normalizeThemeTags(value: string): string[] {
  return Array.from(
    new Set(
      value
        .split(",")
        .map((part) => part.trim().toLowerCase())
        .filter((part) => part.length > 0),
    ),
  );
}

function isDateToken(value: string): boolean {
  return DATE_TOKEN_RE.test(value);
}

export default function Archive() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [archivePage, setArchivePage] = useState<ArchivePage>({ items: [], cursor: null, hasMore: false });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const pageSize = 12;
  const [cursorHistory, setCursorHistory] = useState<(string | null)[]>([null]);

  const activeFilters = useMemo(() => {
    const gameType = parseGameTypeFilter(searchParams.get("gameType"));
    const difficulty = parseDifficultyFilter(searchParams.get("difficulty"));
    const query = (searchParams.get("q") ?? "").trim();
    const themeTags = Array.from(
      new Set(
        searchParams
          .getAll("themeTag")
          .map((tag) => tag.trim().toLowerCase())
          .filter((tag) => tag.length > 0),
      ),
    );
    const dateFromRaw = (searchParams.get("dateFrom") ?? "").trim();
    const dateToRaw = (searchParams.get("dateTo") ?? "").trim();
    const dateFrom = isDateToken(dateFromRaw) ? dateFromRaw : "";
    const dateTo = isDateToken(dateToRaw) ? dateToRaw : "";
    return { gameType, difficulty, query, themeTags, dateFrom, dateTo };
  }, [searchParams]);

  const [draftGameType, setDraftGameType] = useState<ArchiveGameType>(activeFilters.gameType);
  const [draftDifficulty, setDraftDifficulty] = useState<ArchiveDifficulty | "">(activeFilters.difficulty);
  const [draftQuery, setDraftQuery] = useState(activeFilters.query);
  const [draftThemeTags, setDraftThemeTags] = useState(activeFilters.themeTags.join(", "));
  const [draftDateFrom, setDraftDateFrom] = useState(activeFilters.dateFrom);
  const [draftDateTo, setDraftDateTo] = useState(activeFilters.dateTo);

  useEffect(() => {
    setDraftGameType(activeFilters.gameType);
    setDraftDifficulty(activeFilters.difficulty);
    setDraftQuery(activeFilters.query);
    setDraftThemeTags(activeFilters.themeTags.join(", "));
    setDraftDateFrom(activeFilters.dateFrom);
    setDraftDateTo(activeFilters.dateTo);
  }, [activeFilters]);

  const archiveFetchOptions = useMemo(
    () => ({
      limit: pageSize,
      difficulty: activeFilters.difficulty || undefined,
      query: activeFilters.query || undefined,
      themeTags: activeFilters.themeTags,
      dateFrom: activeFilters.dateFrom || undefined,
      dateTo: activeFilters.dateTo || undefined,
    }),
    [activeFilters, pageSize],
  );

  useEffect(() => {
    setLoading(true);
    setError(null);
    setPage(0);
    setCursorHistory([null]);
    getArchive(activeFilters.gameType, archiveFetchOptions)
      .then((data) => setArchivePage(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [activeFilters, archiveFetchOptions]);

  const visibleItems = useMemo(() => archivePage.items, [archivePage.items]);
  const pageLabel = page + 1;
  const hasAnyFilters = useMemo(
    () =>
      activeFilters.gameType !== "all" ||
      activeFilters.difficulty.length > 0 ||
      activeFilters.query.length > 0 ||
      activeFilters.themeTags.length > 0 ||
      activeFilters.dateFrom.length > 0 ||
      activeFilters.dateTo.length > 0,
    [activeFilters],
  );

  const formatTimestamp = (value: string) =>
    new Date(value).toLocaleString(undefined, {
      dateStyle: "medium",
      timeStyle: "short",
    });

  const goPrevious = () => {
    if (page <= 0) return;
    const prevPage = page - 1;
    const cursor = cursorHistory[prevPage] ?? null;
    setLoading(true);
    setError(null);
    getArchive(activeFilters.gameType, { ...archiveFetchOptions, cursor: cursor ?? undefined })
      .then((data) => {
        setArchivePage(data);
        setPage(prevPage);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  const goNext = () => {
    if (!archivePage.hasMore || !archivePage.cursor) return;
    const nextCursor = archivePage.cursor;
    setLoading(true);
    setError(null);
    getArchive(activeFilters.gameType, { ...archiveFetchOptions, cursor: nextCursor })
      .then((data) => {
        setArchivePage(data);
        setCursorHistory((current) => {
          const copy = current.slice(0, page + 1);
          copy.push(nextCursor);
          return copy;
        });
        setPage((current) => current + 1);
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  };

  const applyFilters = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const next = new URLSearchParams();
    const cleanedQuery = draftQuery.trim();
    const cleanedThemeTags = normalizeThemeTags(draftThemeTags);
    const cleanedDateFrom = draftDateFrom.trim();
    const cleanedDateTo = draftDateTo.trim();

    if (draftGameType !== "all") next.set("gameType", draftGameType);
    if (draftDifficulty) next.set("difficulty", draftDifficulty);
    if (cleanedQuery) next.set("q", cleanedQuery);
    for (const tag of cleanedThemeTags) {
      next.append("themeTag", tag);
    }
    if (isDateToken(cleanedDateFrom)) next.set("dateFrom", cleanedDateFrom);
    if (isDateToken(cleanedDateTo)) next.set("dateTo", cleanedDateTo);
    setSearchParams(next);
  };

  const clearFilters = () => {
    setSearchParams(new URLSearchParams());
  };

  return (
    <Layout>
      <section className="page-section" aria-labelledby="archive-heading" aria-busy={loading}>
        <div className="section-header">
          <h2 id="archive-heading">Archive</h2>
          <p>Browse published puzzles by date and reopen any entry.</p>
        </div>

        <form className="archive-controls" onSubmit={applyFilters}>
          <label className="archive-control" htmlFor="archive-game-type">
            <span>Game</span>
            <select
              id="archive-game-type"
              value={draftGameType}
              onChange={(event) => {
                const value = event.target.value;
                if (value === "crossword" || value === "cryptic" || value === "connections") {
                  setDraftGameType(value);
                  return;
                }
                setDraftGameType("all");
              }}
            >
              <option value="all">All</option>
              <option value="crossword">Crossword</option>
              <option value="cryptic">Cryptic</option>
              <option value="connections">Connections</option>
            </select>
          </label>
          <label className="archive-control" htmlFor="archive-difficulty">
            <span>Difficulty</span>
            <select
              id="archive-difficulty"
              value={draftDifficulty}
              onChange={(event) => {
                const value = event.target.value;
                if (value === "easy" || value === "medium" || value === "hard") {
                  setDraftDifficulty(value);
                  return;
                }
                setDraftDifficulty("");
              }}
            >
              <option value="">Any</option>
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
          </label>
          <label className="archive-control" htmlFor="archive-query">
            <span>Title Search</span>
            <input
              id="archive-query"
              type="search"
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="Type title text"
            />
          </label>
          <label className="archive-control" htmlFor="archive-theme-tags">
            <span>Theme Tags</span>
            <input
              id="archive-theme-tags"
              type="text"
              value={draftThemeTags}
              onChange={(event) => setDraftThemeTags(event.target.value)}
              placeholder="e.g. fire, starter"
            />
          </label>
          <label className="archive-control" htmlFor="archive-date-from">
            <span>Date From</span>
            <input
              id="archive-date-from"
              type="date"
              value={draftDateFrom}
              onChange={(event) => setDraftDateFrom(event.target.value)}
            />
          </label>
          <label className="archive-control" htmlFor="archive-date-to">
            <span>Jump To (On/Before)</span>
            <input
              id="archive-date-to"
              type="date"
              value={draftDateTo}
              onChange={(event) => setDraftDateTo(event.target.value)}
            />
          </label>
          <div className="archive-control archive-control--actions">
            <span>Filters</span>
            <div className="archive-control__buttons">
              <button className="button ghost" type="submit">
                Apply
              </button>
              <button className="button ghost" type="button" onClick={clearFilters}>
                Reset
              </button>
            </div>
          </div>
          <div className="archive-count" role="status" aria-live="polite">
            {loading
              ? "Loading…"
              : `${archivePage.items.length} puzzle${archivePage.items.length === 1 ? "" : "s"} on page${
                  hasAnyFilters ? " (filtered)" : ""
                }`}
          </div>
        </form>

        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}

        <div className="archive-list">
          {loading ? (
            <div className="archive-skeletons" role="status" aria-live="polite" aria-label="Loading archive">
              {Array.from({ length: 3 }, (_, index) => (
                <article className="card archive-item skeleton-card" key={`archive-skeleton-${index}`}>
                  <div className="archive-item__top">
                    <div className="skeleton-line skeleton-line--heading" />
                    <div className="skeleton-line skeleton-line--chip" />
                  </div>
                  <div className="archive-item__meta">
                    <div className="skeleton-line" />
                    <div className="skeleton-line skeleton-line--short" />
                    <div className="skeleton-line skeleton-line--short" />
                  </div>
                  <div className="archive-item__actions">
                    <div className="skeleton-line skeleton-line--button" />
                  </div>
                </article>
              ))}
            </div>
          ) : null}
          {!loading && visibleItems.length === 0 ? (
            <div className="card">
              {hasAnyFilters
                ? "No archived puzzles match these filters. Try broadening your search or resetting filters."
                : "No archived puzzles found."}
            </div>
          ) : null}
          {!loading
            ? visibleItems.map((item) => (
                <article className="card archive-item" key={item.id}>
                  <div className="archive-item__top">
                    <h3>{item.title}</h3>
                    <span className={`tag archive-tag archive-tag--${item.difficulty}`}>{item.difficulty}</span>
                  </div>
                  <div className="archive-item__meta">
                    <div>Date: {item.date}</div>
                    <div>Published: {formatTimestamp(item.publishedAt)}</div>
                    <div>ID: {item.id}</div>
                  </div>
                  {item.noteSnippet ? <div className="archive-item__note">{item.noteSnippet}</div> : null}
                  <div className="archive-item__actions">
                    <Link
                      className="button"
                      to={
                        item.gameType === "cryptic"
                          ? `/cryptic?date=${item.date}`
                          : item.gameType === "connections"
                            ? `/connections?date=${item.date}`
                          : `/daily?gameType=${item.gameType}&date=${item.date}`
                      }
                    >
                      Open Puzzle
                    </Link>
                  </div>
                </article>
              ))
            : null}
        </div>

        <div className="archive-pagination" aria-label="Archive pagination">
          <button className="button ghost" disabled={loading || page <= 0} onClick={goPrevious}>
            Previous
          </button>
          <div role="status" aria-live="polite">
            Page {pageLabel}
          </div>
          <button className="button ghost" disabled={loading || !archivePage.hasMore} onClick={goNext}>
            Next
          </button>
        </div>
      </section>
    </Layout>
  );
}
