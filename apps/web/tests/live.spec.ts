import { execFileSync } from "node:child_process";
import path from "node:path";

import { expect, test, type Page } from "@playwright/test";

const ADMIN_TOKEN = process.env.PLAYWRIGHT_ADMIN_TOKEN ?? "local-admin-token-change-me";
const API_CONTAINER_BASE_URL = process.env.PLAYWRIGHT_CONTAINER_API_BASE_URL ?? "http://127.0.0.1:8000";
const API_COMPOSE_FILE =
  process.env.PLAYWRIGHT_API_COMPOSE_FILE ?? path.resolve(process.cwd(), "../../services/api/docker-compose.yml");
const API_SERVICE_NAME = process.env.PLAYWRIGHT_API_SERVICE_NAME ?? "api";

type ContainerApiResponse = {
  status: number;
  headers: Record<string, string>;
  body_b64: string;
};

type ApiEnvelope<T> = {
  data: T;
};

type DailyPuzzle = {
  id: string;
  date: string;
  title: string;
  entries: Array<{
    answer: string;
  }>;
  metadata: {
    connections?: {
      groups: Array<{
        title: string;
        labels: string[];
      }>;
    } | null;
  };
};

function filterRequestHeaders(headers: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(headers).filter(([key]) => {
      const lowered = key.toLowerCase();
      return !["accept-encoding", "connection", "content-length", "host"].includes(lowered);
    }),
  );
}

function filterResponseHeaders(headers: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(headers).filter(([key]) => {
      const lowered = key.toLowerCase();
      return !["connection", "content-encoding", "content-length", "date", "server", "transfer-encoding"].includes(
        lowered,
      );
    }),
  );
}

function requestViaApiContainer(params: {
  url: string;
  method: string;
  headers: Record<string, string>;
  body: Buffer | null;
}): ContainerApiResponse {
  const script = [
    "import base64, json, sys, urllib.error, urllib.request",
    "url, method, headers_json, body_b64 = sys.argv[1:5]",
    "headers = json.loads(headers_json)",
    "body = None if body_b64 == '-' else base64.b64decode(body_b64.encode())",
    "request = urllib.request.Request(url, data=body, headers=headers, method=method)",
    "try:",
    "    with urllib.request.urlopen(request) as response:",
    "        payload = {",
    "            'status': response.status,",
    "            'headers': dict(response.getheaders()),",
    "            'body_b64': base64.b64encode(response.read()).decode(),",
    "        }",
    "except urllib.error.HTTPError as error:",
    "    payload = {",
    "        'status': error.code,",
    "        'headers': dict(error.headers.items()),",
    "        'body_b64': base64.b64encode(error.read()).decode(),",
    "    }",
    "print(json.dumps(payload))",
  ].join("\n");

  const output = execFileSync(
    "docker",
    [
      "compose",
      "-f",
      API_COMPOSE_FILE,
      "exec",
      "-T",
      API_SERVICE_NAME,
      "python",
      "-c",
      script,
      params.url,
      params.method,
      JSON.stringify(params.headers),
      params.body ? params.body.toString("base64") : "-",
    ],
    {
      cwd: process.cwd(),
      encoding: "utf8",
    },
  );

  return JSON.parse(output) as ContainerApiResponse;
}

function requestJsonViaApiContainer<T>(params: {
  url: string;
  method?: string;
  headers?: Record<string, string>;
  body?: Buffer | null;
}) {
  const response = requestViaApiContainer({
    url: params.url,
    method: params.method ?? "GET",
    headers: params.headers ?? {},
    body: params.body ?? null,
  });
  const text = Buffer.from(response.body_b64, "base64").toString("utf8");
  return {
    status: response.status,
    json: JSON.parse(text) as T,
  };
}

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

async function expectNoErrorBanner(page: Page) {
  await expect(page.getByText(/puzzle fetch failed/i)).toHaveCount(0);
  await expect(page.getByText(/not enabled for this environment/i)).toHaveCount(0);
}

test.beforeEach(async ({ page }) => {
  const runId = `${Date.now()}`;

  await page.route("**/api/v1/**", async (route) => {
    const requestUrl = new URL(route.request().url());
    const upstreamUrl = `${API_CONTAINER_BASE_URL}${requestUrl.pathname}${requestUrl.search}`;
    const response = requestViaApiContainer({
      url: upstreamUrl,
      method: route.request().method(),
      headers: filterRequestHeaders(route.request().headers()),
      body: route.request().postDataBuffer(),
    });

    await route.fulfill({
      status: response.status,
      headers: filterResponseHeaders(response.headers),
      body: Buffer.from(response.body_b64, "base64"),
    });
  });

  await page.addInitScript(({ adminToken, runId }) => {
    window.localStorage.setItem("player:token:v1", `anon_e2e_primary_${runId}`);
    window.localStorage.setItem("crossword:session-id", `sess_crossword_live_${runId}`);
    window.localStorage.setItem("cryptic:session-id", `sess_cryptic_live_${runId}`);
    window.localStorage.setItem("connections:session-id", `sess_connections_live_${runId}`);
    window.sessionStorage.setItem("admin:api-token", adminToken);

    Object.defineProperty(navigator, "sendBeacon", {
      configurable: true,
      value: () => true,
    });

    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async () => undefined,
      },
    });
  }, { adminToken: ADMIN_TOKEN, runId });
});

test("live app routes work against the local backend", async ({ page }) => {
  const crossword = requestJsonViaApiContainer<ApiEnvelope<DailyPuzzle>>({
    url: `${API_CONTAINER_BASE_URL}/api/v1/puzzles/daily?gameType=crossword`,
  }).json.data;
  const cryptic = requestJsonViaApiContainer<ApiEnvelope<DailyPuzzle>>({
    url: `${API_CONTAINER_BASE_URL}/api/v1/puzzles/daily?gameType=cryptic`,
  }).json.data;
  const connections = requestJsonViaApiContainer<ApiEnvelope<DailyPuzzle>>({
    url: `${API_CONTAINER_BASE_URL}/api/v1/puzzles/daily?gameType=connections`,
  }).json.data;
  const firstConnectionsGroup = connections.metadata.connections?.groups[0];

  await page.goto(`/daily?date=${crossword.date}`);
  await expect(page.getByRole("heading", { name: "Daily Crossword" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Check Entry" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Reveal All" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Reveal All" }).click();
  await expect(page.getByText("Puzzle Recap")).toBeVisible({ timeout: 20_000 });
  await expectNoErrorBanner(page);

  await page.goto(`/cryptic?date=${cryptic.date}`);
  await expect(page.getByRole("heading", { name: "Cryptic Clue" })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Hint 1" }).click();
  await expect(page.getByText("Hint 1 shown.")).toBeVisible();
  await page.getByRole("textbox", { name: "Your Answer" }).fill(cryptic.entries[0]?.answer ?? "");
  await page.getByRole("button", { name: "Submit Guess" }).click();
  await expect(page.getByText("Correct. Explanation unlocked.")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Explanation" })).toBeVisible({ timeout: 20_000 });
  await expectNoErrorBanner(page);

  await page.goto(`/connections?date=${connections.date}`);
  await expect(page.getByRole("heading", { name: "Daily Connections" })).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".connections-tile")).toHaveCount(16, { timeout: 20_000 });
  await page.locator(".connections-tile").first().click();
  await page.getByRole("button", { name: "Clear" }).click();
  await expect(page.getByText("Selection cleared.")).toBeVisible();
  for (const label of firstConnectionsGroup?.labels ?? []) {
    await page.getByRole("button", { name: label, exact: true }).click();
  }
  await page.getByRole("button", { name: "Submit Group" }).click();
  await expect(page.getByRole("heading", { name: firstConnectionsGroup?.title ?? "" })).toBeVisible({ timeout: 20_000 });
  await expectNoErrorBanner(page);

  await page.goto("/archive?gameType=connections");
  await expect(page.getByRole("heading", { name: "Archive" })).toBeVisible({ timeout: 20_000 });
  await expectNoErrorBanner(page);

  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Profile", exact: true })).toBeVisible({ timeout: 20_000 });
  await expect(page).toHaveURL(/\/profile$/);
  await expect(page.getByRole("button", { name: "Create Account" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("button", { name: "Log In" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Completion Rate")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("link", { name: "View Public Page" }).click();
  await expect(page).toHaveURL(/\/players\//);
  await expectNoErrorBanner(page);

  await page.goto("/leaderboard");
  await expect(page.getByRole("heading", { name: "Leaderboard" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Your Profile")).toBeVisible({ timeout: 20_000 });
  await page.getByRole("textbox", { name: "Date" }).fill(crossword.date);
  await page.getByRole("textbox", { name: "Date" }).press("Tab");
  await expect(page.getByText(`Window: ${crossword.date} to ${crossword.date}`)).toBeVisible({ timeout: 20_000 });
  const playerLinks = page.locator('a[href^="/players/"]');
  if (await playerLinks.count()) {
    await playerLinks.first().click();
    await expect(page).toHaveURL(/\/players\//);
    await expect(page.getByRole("heading", { level: 2 })).toBeVisible({ timeout: 20_000 });
  } else {
    await expect(page.getByText("No ranked completions in this window yet.")).toBeVisible({ timeout: 20_000 });
  }
  await expectNoErrorBanner(page);

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin Console" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Token loaded")).toBeVisible({ timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Reserve" })).toBeVisible({ timeout: 20_000 });
  await expectNoErrorBanner(page);
});
