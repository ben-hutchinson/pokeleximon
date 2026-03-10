import { Link } from "react-router-dom";
import Layout from "../components/Layout";
import { FEATURE_CONNECTIONS_ENABLED } from "../featureFlags";

export default function Home() {
  return (
    <Layout>
      <section className="home-routes" aria-labelledby="home-nav-heading">
        <h2 id="home-nav-heading" className="sr-only">
          Game navigation
        </h2>
        <Link className="button" to="/daily">
          Daily Crossword
        </Link>
        <Link className="button secondary" to="/cryptic">
          Cryptic Clue
        </Link>
        {FEATURE_CONNECTIONS_ENABLED ? (
          <Link className="button ghost" to="/connections">
            Daily Connections
          </Link>
        ) : null}
        <Link className="button ghost" to="/archive">
          Archive
        </Link>
        <Link className="button ghost" to="/stats">
          Your Stats
        </Link>
        <Link className="button ghost" to="/leaderboard">
          Leaderboards
        </Link>
        <Link className="button ghost" to="/account">
          Account
        </Link>
      </section>
    </Layout>
  );
}
