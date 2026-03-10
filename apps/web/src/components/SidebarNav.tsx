import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { FEATURE_CONNECTIONS_ENABLED } from "../featureFlags";

export default function SidebarNav({
  highContrast,
  onToggleContrast,
}: {
  highContrast: boolean;
  onToggleContrast: () => void;
}) {
  const [isOpen, setIsOpen] = useState(false);
  const location = useLocation();

  return (
    <aside className={`sidebar ${isOpen ? "is-open" : "is-closed"}`} aria-label="Primary">
      <button
        className="sidebar__button"
        type="button"
        onClick={() => setIsOpen((prev) => !prev)}
        aria-expanded={isOpen}
        aria-controls="primary-nav"
        aria-label={isOpen ? "Collapse navigation" : "Expand navigation"}
      >
        <span className="sidebar__burger" aria-hidden="true">
          <span />
          <span />
          <span />
        </span>
      </button>

      <nav id="primary-nav" className="sidebar__panel" aria-label="Primary navigation">
        <Link
          to="/daily"
          className={`sidebar__link ${location.pathname === "/daily" ? "is-active" : ""}`}
          aria-current={location.pathname === "/daily" ? "page" : undefined}
        >
          Daily Puzzle
        </Link>
        <Link
          to="/cryptic"
          className={`sidebar__link ${location.pathname === "/cryptic" ? "is-active" : ""}`}
          aria-current={location.pathname === "/cryptic" ? "page" : undefined}
        >
          Cryptic Clue
        </Link>
        {FEATURE_CONNECTIONS_ENABLED ? (
          <Link
            to="/connections"
            className={`sidebar__link ${location.pathname === "/connections" ? "is-active" : ""}`}
            aria-current={location.pathname === "/connections" ? "page" : undefined}
          >
            Connections
          </Link>
        ) : null}
        <Link
          to="/archive"
          className={`sidebar__link ${location.pathname === "/archive" ? "is-active" : ""}`}
          aria-current={location.pathname === "/archive" ? "page" : undefined}
        >
          Archive
        </Link>
        <Link
          to="/stats"
          className={`sidebar__link ${location.pathname === "/stats" ? "is-active" : ""}`}
          aria-current={location.pathname === "/stats" ? "page" : undefined}
        >
          Your Stats
        </Link>
        <Link
          to="/leaderboard"
          className={`sidebar__link ${location.pathname === "/leaderboard" ? "is-active" : ""}`}
          aria-current={location.pathname === "/leaderboard" ? "page" : undefined}
        >
          Leaderboards
        </Link>
        <Link
          to="/account"
          className={`sidebar__link ${location.pathname === "/account" ? "is-active" : ""}`}
          aria-current={location.pathname === "/account" ? "page" : undefined}
        >
          Account
        </Link>
        <Link
          to="/text-only"
          className={`sidebar__link ${location.pathname === "/text-only" ? "is-active" : ""}`}
          aria-current={location.pathname === "/text-only" ? "page" : undefined}
        >
          Text-Only
        </Link>
        <Link
          to="/admin"
          className={`sidebar__link ${location.pathname === "/admin" ? "is-active" : ""}`}
          aria-current={location.pathname === "/admin" ? "page" : undefined}
        >
          Admin
        </Link>
        <button
          className={`button ghost contrast-toggle sidebar__contrast-toggle${highContrast ? " is-enabled" : ""}`}
          type="button"
          aria-pressed={highContrast}
          aria-label={highContrast ? "Disable high contrast mode" : "Enable high contrast mode"}
          onClick={onToggleContrast}
        >
          <span className="contrast-toggle__icon" aria-hidden="true" />
          <span className="contrast-toggle__label">
            High Contrast <strong>{highContrast ? "On" : "Off"}</strong>
          </span>
        </button>
      </nav>
    </aside>
  );
}
