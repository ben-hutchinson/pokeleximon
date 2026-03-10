import { expect, test, type APIRequestContext, type Page } from "@playwright/test";

const API_BASE_URL = process.env.PLAYWRIGHT_API_BASE_URL ?? "http://127.0.0.1:8000";
const E2E_DATE = process.env.PLAYWRIGHT_E2E_DATE ?? "2099-01-01";
const ADMIN_TOKEN = process.env.PLAYWRIGHT_ADMIN_TOKEN ?? "local-admin-token-change-me";
const GAME_TYPES = ["crossword", "cryptic", "connections"] as const;

test.describe.configure({ mode: "serial" });
test.setTimeout(180_000);

async function responseBody(response: Awaited<ReturnType<APIRequestContext["get"]>>) {
  const text = await response.text();
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

async function ensurePuzzlePublished(api: APIRequestContext, gameType: (typeof GAME_TYPES)[number]) {
  const dailyResponse = await api.get(`${API_BASE_URL}/api/v1/puzzles/daily`, {
    params: { date: E2E_DATE, gameType, redact_answers: "false" },
  });
  expect(dailyResponse.ok(), `daily ${gameType}: ${JSON.stringify(await responseBody(dailyResponse))}`).toBeTruthy();
}

async function expectNoErrorBanner(page: Page) {
  await expect(page.locator(".error")).toHaveCount(0);
}

test.beforeAll(async ({ playwright }) => {
  const api = await playwright.request.newContext();
  for (const gameType of GAME_TYPES) {
    await ensurePuzzlePublished(api, gameType);
  }
  await api.dispose();
});

test.beforeEach(async ({ page }) => {
  await page.addInitScript(({ adminToken }) => {
    window.localStorage.setItem("player:token:v1", "anon_e2e_primary");
    window.localStorage.setItem("crossword:session-id", "sess_crossword_live");
    window.localStorage.setItem("cryptic:session-id", "sess_cryptic_live");
    window.localStorage.setItem("connections:session-id", "sess_connections_live");
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
  }, { adminToken: ADMIN_TOKEN });
});

test("live app routes work against the local backend", async ({ page }) => {
  await page.goto(`/daily?date=${E2E_DATE}`);
  await expect(page.getByRole("button", { name: "Check Entry" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Create Challenge" })).toBeVisible();
  await expectNoErrorBanner(page);

  await page.getByRole("button", { name: "Create Challenge" }).click();
  const challengeStatus = page.locator(".panel__meta").filter({ hasText: "Challenge created:" }).last();
  await expect(challengeStatus).toBeVisible();
  const challengeStatusText = (await challengeStatus.textContent()) ?? "";
  const challengeCodeMatch = challengeStatusText.match(/Challenge created:\s(?:https?:\/\/\S+\/challenge\/)?([A-Z0-9]{8})/i);
  expect(challengeCodeMatch?.[1], `challenge status: ${challengeStatusText}`).toBeTruthy();
  const challengeCode = challengeCodeMatch![1].toUpperCase();

  await page.evaluate(() => {
    window.localStorage.setItem("player:token:v1", "anon_e2e_joiner");
  });
  await page.goto(`/challenge/${challengeCode}`);
  await expect(page.getByRole("heading", { name: "Challenge" })).toBeVisible();
  await expect(page.getByText(`Code: ${challengeCode}`)).toBeVisible();
  const joinButton = page.getByRole("button", { name: "Join Challenge" });
  if (await joinButton.isVisible()) {
    await joinButton.click();
    await expect(page.getByText("You joined this challenge.")).toBeVisible();
  }
  await expectNoErrorBanner(page);

  await page.goto(`/cryptic?date=${E2E_DATE}`);
  await expect(page.getByRole("heading", { name: "Cryptic Clue" })).toBeVisible();
  await page.getByRole("button", { name: "Hint 1" }).click();
  await expect(page.getByText("Hint 1 shown.")).toBeVisible();
  await expectNoErrorBanner(page);

  await page.goto(`/connections?date=${E2E_DATE}`);
  await expect(page.getByRole("heading", { name: "Daily Connections" })).toBeVisible();
  await expect(page.locator(".connections-tile")).toHaveCount(16);
  await page.locator(".connections-tile").first().click();
  await page.getByRole("button", { name: "Clear Selection" }).click();
  await expect(page.getByText("Pick four tiles that share a connection.")).toBeVisible();
  await expectNoErrorBanner(page);

  await page.goto("/archive?gameType=connections");
  await expect(page.getByRole("heading", { name: "Archive" })).toBeVisible();
  await expect(page.getByText(`Connections ${E2E_DATE}`)).toBeVisible();
  await expectNoErrorBanner(page);

  await page.goto("/stats");
  await expect(page.getByRole("heading", { name: "Your Stats" })).toBeVisible();
  await expect(page.getByText("Completion Rate")).toBeVisible();
  await expectNoErrorBanner(page);

  await page.goto("/leaderboard");
  await expect(page.getByRole("heading", { name: "Leaderboard" })).toBeVisible();
  await expect(page.getByText("Your Ranking Privacy")).toBeVisible();
  await expectNoErrorBanner(page);

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin Console" })).toBeVisible();
  await expect(page.getByText("Token loaded")).toBeVisible();
  await expectNoErrorBanner(page);
});
