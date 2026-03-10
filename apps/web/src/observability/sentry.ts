type ClientErrorPayload = {
  message: string;
  stack?: string | null;
  source: "frontend";
  route?: string;
  userAgent?: string;
  appVersion?: string;
  eventType: "error" | "unhandledrejection";
  details?: Record<string, unknown>;
};

function postClientError(payload: ClientErrorPayload) {
  const body = JSON.stringify(payload);
  if ("sendBeacon" in navigator) {
    try {
      const blob = new Blob([body], { type: "application/json" });
      const accepted = navigator.sendBeacon("/api/v1/puzzles/client-errors", blob);
      if (accepted) return;
    } catch {
      // fall through to fetch
    }
  }
  void fetch("/api/v1/puzzles/client-errors", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    keepalive: true,
  }).catch(() => undefined);
}

export function initSentry() {
  const appVersion = (import.meta.env.VITE_SENTRY_RELEASE ?? import.meta.env.VITE_APP_VERSION ?? "").trim() || "web";
  window.addEventListener("error", (event) => {
    postClientError({
      source: "frontend",
      eventType: "error",
      message: event.message || "Unhandled error event",
      stack: event.error instanceof Error ? event.error.stack : null,
      route: window.location.pathname + window.location.search,
      userAgent: navigator.userAgent,
      appVersion,
      details: {
        fileName: event.filename,
        line: event.lineno,
        column: event.colno,
      },
    });
  });

  window.addEventListener("unhandledrejection", (event) => {
    const reason = event.reason;
    const asError = reason instanceof Error ? reason : null;
    const reasonMessage = asError?.message ?? (typeof reason === "string" ? reason : "Unhandled promise rejection");
    postClientError({
      source: "frontend",
      eventType: "unhandledrejection",
      message: reasonMessage,
      stack: asError?.stack ?? null,
      route: window.location.pathname + window.location.search,
      userAgent: navigator.userAgent,
      appVersion,
      details: {
        reasonType: typeof reason,
      },
    });
  });
}
