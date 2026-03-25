import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { getLeaderboard, type CompetitiveGameType, type GlobalLeaderboardPage } from "../api/puzzles";
import { FEATURE_CONNECTIONS_ENABLED } from "../featureFlags";
import { todayIsoInTimezone } from "../utils/date";
import Layout from "../components/Layout";

const NEWS_ITEMS = [
  {
    title: "Daily puzzle cadence",
    body: "Crossword, cryptic, and connections stay surfaced from one home dashboard so the quickest route to today's puzzle is always visible.",
  },
  {
    title: "Profile hub",
    body: "Player identity, stats, and public profile controls now live together instead of being split across account and stats pages.",
  },
  {
    title: "Archive flow",
    body: "Puzzle archives remain available, but entry points move into each puzzle page so browse history stays tied to the game you're playing.",
  },
];

function formatSolveMs(value: number | null | undefined) {
  if (value === null || value === undefined) return "--:--";
  const totalSeconds = Math.max(0, Math.floor(value / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

export default function Home() {
  const [gameType, setGameType] = useState<CompetitiveGameType>("crossword");
  const [leaderboard, setLeaderboard] = useState<GlobalLeaderboardPage | null>(null);
  const [loadingLeaderboard, setLoadingLeaderboard] = useState(true);
  const [leaderboardError, setLeaderboardError] = useState<string | null>(null);

  useEffect(() => {
    setLoadingLeaderboard(true);
    setLeaderboardError(null);
    getLeaderboard({
      gameType,
      scope: "daily",
      date: todayIsoInTimezone(),
      limit: 5,
    })
      .then(setLeaderboard)
      .catch((error) => setLeaderboardError(error instanceof Error ? error.message : "Failed to load leaderboard preview."))
      .finally(() => setLoadingLeaderboard(false));
  }, [gameType]);

  const leaderboardItems = useMemo(() => leaderboard?.items ?? [], [leaderboard]);

  return (
    <Layout>
      <section className="home-dashboard" aria-label="Homepage dashboard">
        <nav className="home-dashboard__game-nav" aria-label="Puzzle navigation">
          <Link className="home-dashboard__game-link is-primary" to="/daily">
            Crossword
          </Link>
          <Link className="home-dashboard__game-link is-secondary" to="/cryptic">
            Cryptic
          </Link>
          {FEATURE_CONNECTIONS_ENABLED ? (
            <Link className="home-dashboard__game-link is-ghost" to="/connections">
              Connections
            </Link>
          ) : null}
        </nav>

        <div className="home-dashboard__grid">
          <section className="card home-dashboard__panel" aria-labelledby="home-news-heading">
            <div className="home-dashboard__panel-header">
              <h3 id="home-news-heading">News / Dev Activity</h3>
            </div>
            <div className="home-dashboard__news-list">
              {NEWS_ITEMS.map((item) => (
                <article key={item.title} className="home-dashboard__news-item">
                  <h4>{item.title}</h4>
                  <p>{item.body}</p>
                </article>
              ))}
            </div>
          </section>

          <section className="card home-dashboard__panel home-dashboard__panel--leaderboard" aria-labelledby="home-leaderboard-heading">
            <div className="home-dashboard__panel-header">
              <h3 id="home-leaderboard-heading">Leaderboard</h3>
              <Link className="button ghost" to="/leaderboard">
                View Full
              </Link>
            </div>

            <div className="stats-controls" role="group" aria-label="Homepage leaderboard game filter">
              <button
                className={`button ghost${gameType === "crossword" ? " is-active" : ""}`}
                type="button"
                onClick={() => setGameType("crossword")}
                aria-pressed={gameType === "crossword"}
              >
                Crossword
              </button>
              <button
                className={`button ghost${gameType === "cryptic" ? " is-active" : ""}`}
                type="button"
                onClick={() => setGameType("cryptic")}
                aria-pressed={gameType === "cryptic"}
              >
                Cryptic
              </button>
            </div>

            {leaderboardError ? <div className="error" role="alert">{leaderboardError}</div> : null}
            {loadingLeaderboard ? <p className="panel__meta">Loading leaderboard preview…</p> : null}

            {!loadingLeaderboard ? (
              <div className="home-dashboard__leaderboard">
                {leaderboardItems.length === 0 ? (
                  <p className="panel__meta">No ranked completions yet for this window.</p>
                ) : (
                  leaderboardItems.map((item) => (
                    <div key={`${item.playerToken}-${item.rank}`} className="home-dashboard__leaderboard-row">
                      <div>
                        <strong>#{item.rank}</strong> {item.publicSlug ? <Link to={`/players/${item.publicSlug}`}>{item.displayName}</Link> : item.displayName}
                      </div>
                      <span>{formatSolveMs(item.bestSolveTimeMs)}</span>
                    </div>
                  ))
                )}
              </div>
            ) : null}
          </section>
        </div>

        <section id="home-about" className="card home-dashboard__about" aria-labelledby="home-about-heading">
          <h3 id="home-about-heading">About</h3>
          <p>
            Pokeleximon is a puzzle playground built around daily crossword, cryptic, and connections formats with a shared player profile,
            public stats, and puzzle archives that stay tied to each game page.
          </p>
          <p>
            This refresh keeps the established palette, makes core destinations visible without a burger menu, and gives profile and leaderboard
            features a permanent home in the main UI instead of scattered secondary pages.
          </p>
        </section>
      </section>
    </Layout>
  );
}
