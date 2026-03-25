import { useEffect, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { FEATURE_CONNECTIONS_ENABLED } from "../featureFlags";
import BuyMeCoffeeButton from "./BuyMeCoffeeButton";
import ProfileAvatar from "./ProfileAvatar";
import SidebarNav from "./SidebarNav";

type LayoutProps = {
  children: React.ReactNode;
};

const FOOTER_LOGO_SRC = "/pokeleximon-logo.svg";
const FOOTER_LOGO_FALLBACK_SRC = "/hutchlax-mascot.svg";
const HEADER_LOGO_SRC = "/pokeleximon-logo.svg";
const CONTRAST_STORAGE_KEY = "ui:contrast-mode";

type ContrastMode = "default" | "high";

function loadContrastMode(): ContrastMode {
  if (typeof window === "undefined") return "default";
  const raw = window.localStorage.getItem(CONTRAST_STORAGE_KEY);
  return raw === "high" ? "high" : "default";
}

function LegalFooter() {
  return (
    <footer className="legal-footer" role="contentinfo" aria-label="Legal disclaimer">
      <div className="legal-footer__brand">
        <img
          className="legal-footer__logo"
          src={FOOTER_LOGO_SRC}
          alt="Pokeleximon logo"
          onError={(event) => {
            const img = event.currentTarget;
            if (img.dataset.fallbackApplied === "true") return;
            img.dataset.fallbackApplied = "true";
            img.src = FOOTER_LOGO_FALLBACK_SRC;
          }}
        />
      </div>
      <p className="legal-footer__text">
        hutchlax games is not affiliated with Nintendo and does not own or claim any rights to any Nintendo trademark or the
        Pokemon trademark. All references to such are used for commentary and informational purposes only.
      </p>
    </footer>
  );
}

function LegacyLayout({
  children,
  highContrast,
  onToggleContrast,
}: LayoutProps & {
  highContrast: boolean;
  onToggleContrast: () => void;
}) {
  return (
    <div className="app-shell app-shell--legacy">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <SidebarNav highContrast={highContrast} onToggleContrast={onToggleContrast} />
      <main id="main-content" className="page" tabIndex={-1} aria-label="Main content">
        <header className="main-brand">
          <div className="main-brand__toolbar">
            <BuyMeCoffeeButton />
          </div>
          <Link className="main-brand__home" to="/" aria-label="Back to home">
            <div className="main-brand__wordmark">
              <h1 className="main-brand__title">POKELEXIMON</h1>
              <p className="main-brand__subtitle">pokemon puzzles</p>
              <span className="main-brand__underline" aria-hidden="true" />
              <p className="main-brand__channels">Daily crossword • Cryptic • Connections</p>
            </div>
          </Link>
        </header>
        {children}
        <LegalFooter />
      </main>
    </div>
  );
}

function ModernLayout({
  children,
  highContrast,
  onToggleContrast,
}: LayoutProps & {
  highContrast: boolean;
  onToggleContrast: () => void;
}) {
  const location = useLocation();
  const { profile } = useAuth();
  const isHome = location.pathname === "/";
  const navItems = [
    { to: "/daily", label: "Crossword" },
    { to: "/cryptic", label: "Cryptic" },
    ...(FEATURE_CONNECTIONS_ENABLED ? [{ to: "/connections", label: "Connections" }] : []),
  ];

  return (
    <div className="app-shell app-shell--modern">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div className="page page--modern">
        <header className="top-shell">
          <div className="top-shell__bar">
            <Link className="top-shell__logo-link" to="/" aria-label="Go to homepage">
              <span className="top-shell__logo-frame" aria-hidden="true">
                <img className="top-shell__logo" src={HEADER_LOGO_SRC} alt="" />
              </span>
            </Link>

            <Link className="top-shell__home" to="/" aria-label="Back to home">
              <div className="top-shell__wordmark">
                <h1 className="top-shell__title">POKELEXIMON</h1>
              </div>
            </Link>

            <div className="top-shell__utilities">
              <Link className="top-shell__profile-link" to="/profile">
                <ProfileAvatar
                  className="top-shell__profile-avatar"
                  displayName={profile?.displayName ?? "Guest"}
                  avatarPreset={profile?.avatarPreset ?? null}
                  size="sm"
                />
                <span>Profile</span>
              </Link>
            </div>
          </div>

          <nav className="top-shell__nav" aria-label="Primary navigation">
            {navItems.map((item) => {
              const isActive = location.pathname === item.to;
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  className={`top-shell__nav-link${isActive ? " is-active" : ""}`}
                  aria-current={isActive ? "page" : undefined}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </header>

        <main id="main-content" className="page__content" tabIndex={-1} aria-label="Main content">
          {children}
        </main>

        <div className="page__footer-row">
          <LegalFooter />
          <div className="page__footer-actions">
            <button
              className={`button ghost contrast-toggle top-shell__contrast-toggle${highContrast ? " is-enabled" : ""}`}
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
            {isHome ? <BuyMeCoffeeButton /> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export default function Layout({ children }: LayoutProps) {
  const location = useLocation();
  const [contrastMode, setContrastMode] = useState<ContrastMode>(loadContrastMode);
  const highContrast = contrastMode === "high";
  const toggleContrast = () => {
    setContrastMode((current) => (current === "high" ? "default" : "high"));
  };

  useEffect(() => {
    const root = document.documentElement;
    root.setAttribute("data-contrast", contrastMode);
    window.localStorage.setItem(CONTRAST_STORAGE_KEY, contrastMode);
  }, [contrastMode]);

  if (location.pathname.startsWith("/admin")) {
    return <LegacyLayout highContrast={highContrast} onToggleContrast={toggleContrast}>{children}</LegacyLayout>;
  }

  return <ModernLayout highContrast={highContrast} onToggleContrast={toggleContrast}>{children}</ModernLayout>;
}
