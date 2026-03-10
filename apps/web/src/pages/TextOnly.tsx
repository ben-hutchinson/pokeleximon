import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import Layout from "../components/Layout";
import { getPuzzleTextExport, type CompetitiveGameType, type PuzzleTextExport } from "../api/puzzles";

export default function TextOnly() {
  const [searchParams] = useSearchParams();
  const [data, setData] = useState<PuzzleTextExport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const gameTypeParam = searchParams.get("gameType");
  const gameType: CompetitiveGameType = gameTypeParam === "cryptic" ? "cryptic" : "crossword";
  const date = searchParams.get("date") ?? undefined;
  const puzzleId = searchParams.get("puzzleId") ?? undefined;

  useEffect(() => {
    setData(null);
    setError(null);
    getPuzzleTextExport({ gameType, date, puzzleId })
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load text-only export."));
  }, [date, gameType, puzzleId]);

  const pdfHref = useMemo(() => {
    const params = new URLSearchParams({ gameType });
    if (date) params.set("date", date);
    if (puzzleId) params.set("puzzleId", puzzleId);
    return `/api/v1/puzzles/export/pdf?${params.toString()}`;
  }, [date, gameType, puzzleId]);

  const playHref = useMemo(() => {
    const params = new URLSearchParams();
    if (date) params.set("date", date);
    const suffix = params.toString() ? `?${params.toString()}` : "";
    if (gameType === "cryptic") return `/cryptic${suffix}`;
    return `/daily${suffix}`;
  }, [date, gameType]);

  const across = (data?.entries ?? []).filter((entry) => entry.direction === "across");
  const down = (data?.entries ?? []).filter((entry) => entry.direction === "down");

  return (
    <Layout>
      <section className="page-section text-only-page" aria-labelledby="text-only-heading" aria-busy={!data && !error}>
        <div className="section-header">
          <h2 id="text-only-heading">Text-Only Puzzle View</h2>
          <p>Screen-reader-first clue and structure view. Answers are always omitted in this export.</p>
        </div>
        <div className="text-only-actions no-print">
          <Link className="button secondary" to={playHref}>
            Back to Interactive Puzzle
          </Link>
          <a className="button secondary" href={pdfHref}>
            Download PDF
          </a>
          <button className="button" type="button" onClick={() => window.print()}>
            Print This View
          </button>
        </div>
        {error ? (
          <div className="error" role="alert">
            {error}
          </div>
        ) : null}
        {!data && !error ? (
          <div className="card" role="status" aria-live="polite">
            Loading text-only export…
          </div>
        ) : null}
        {data ? (
          <article className="card text-only-card" aria-label={`${data.gameType} puzzle text-only export`}>
            <h3>{data.title}</h3>
            <p>
              {data.gameType} • {data.date} • Difficulty {data.metadata.difficulty}
            </p>
            {data.metadata.contestMode ? <p>Contest mode is active for this puzzle.</p> : null}
            {data.gameType === "crossword" ? (
              <>
                <section aria-labelledby="text-grid-structure">
                  <h4 id="text-grid-structure">Grid Structure</h4>
                  <p>Rows use `#` for blocks and `.` for fillable cells.</p>
                  <pre className="text-grid" aria-label="Crossword grid structure">
                    {data.grid.rows.join("\n")}
                  </pre>
                </section>
                <section aria-labelledby="text-across">
                  <h4 id="text-across">Across</h4>
                  <ol className="text-clue-list">
                    {across.map((entry) => (
                      <li key={entry.id}>
                        <span className="text-clue-num">{entry.number}.</span> {entry.clue} ({entry.enumeration})
                      </li>
                    ))}
                  </ol>
                </section>
                <section aria-labelledby="text-down">
                  <h4 id="text-down">Down</h4>
                  <ol className="text-clue-list">
                    {down.map((entry) => (
                      <li key={entry.id}>
                        <span className="text-clue-num">{entry.number}.</span> {entry.clue} ({entry.enumeration})
                      </li>
                    ))}
                  </ol>
                </section>
              </>
            ) : (
              <section aria-labelledby="text-cryptic">
                <h4 id="text-cryptic">Cryptic Clue</h4>
                {(data.entries ?? []).slice(0, 1).map((entry) => (
                  <p key={entry.id}>
                    {entry.number}. {entry.clue} ({entry.enumeration})
                  </p>
                ))}
              </section>
            )}
          </article>
        ) : null}
      </section>
    </Layout>
  );
}
