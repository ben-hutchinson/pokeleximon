import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import SidebarNav from "./SidebarNav";
import BuyMeCoffeeButton from "./BuyMeCoffeeButton";

type LayoutProps = {
  children: React.ReactNode;
};

const FOOTER_LOGO_SRC = "/munchlax-cubist.svg";
const FOOTER_LOGO_FALLBACK_SRC = "/hutchlax-mascot.svg";
const CONTRAST_STORAGE_KEY = "ui:contrast-mode";

type ContrastMode = "default" | "high";

function loadContrastMode(): ContrastMode {
  if (typeof window === "undefined") return "default";
  const raw = window.localStorage.getItem(CONTRAST_STORAGE_KEY);
  return raw === "high" ? "high" : "default";
}

export default function Layout({ children }: LayoutProps) {
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

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <SidebarNav highContrast={highContrast} onToggleContrast={toggleContrast} />
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
        <footer className="legal-footer" role="contentinfo" aria-label="Legal disclaimer">
          <div className="legal-footer__brand">
            <img
              className="legal-footer__logo"
              src={FOOTER_LOGO_SRC}
              alt="Munchlax mascot"
              onError={(event) => {
                const img = event.currentTarget;
                if (img.dataset.fallbackApplied === "true") return;
                img.dataset.fallbackApplied = "true";
                img.src = FOOTER_LOGO_FALLBACK_SRC;
              }}
            />
          </div>
          <p className="legal-footer__text">
            hutchlax games is not affiliated with Nintendo and does not own or claim any rights to any Nintendo
            trademark or the Pokemon trademark. All references to such are used for commentary and informational
            purposes only.
          </p>
        </footer>
      </main>
    </div>
  );
}
