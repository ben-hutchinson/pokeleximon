import { expect, test, type Page, type Route } from "@playwright/test";

const crosswordPuzzle = {
  id: "puz_crossword_smoke",
  date: "2026-03-10",
  gameType: "crossword",
  title: "Smoke Test Crossword",
  publishedAt: "2026-03-10T09:00:00Z",
  timezone: "Europe/London",
  grid: {
    width: 3,
    height: 3,
    cells: [
      { x: 0, y: 0, isBlock: false, solution: "C", entryIdAcross: "a1", entryIdDown: "d1" },
      { x: 1, y: 0, isBlock: false, solution: "A", entryIdAcross: "a1", entryIdDown: "d2" },
      { x: 2, y: 0, isBlock: false, solution: "T", entryIdAcross: "a1", entryIdDown: "d3" },
      { x: 0, y: 1, isBlock: false, solution: "A", entryIdAcross: "a4", entryIdDown: "d1" },
      { x: 1, y: 1, isBlock: false, solution: "P", entryIdAcross: "a4", entryIdDown: "d2" },
      { x: 2, y: 1, isBlock: false, solution: "E", entryIdAcross: "a4", entryIdDown: "d3" },
      { x: 0, y: 2, isBlock: false, solution: "T", entryIdAcross: "a7", entryIdDown: "d1" },
      { x: 1, y: 2, isBlock: false, solution: "E", entryIdAcross: "a7", entryIdDown: "d2" },
      { x: 2, y: 2, isBlock: false, solution: "N", entryIdAcross: "a7", entryIdDown: "d3" },
    ],
  },
  entries: [
    { id: "a1", direction: "across", number: 1, answer: "CAT", clue: "Starter pet", length: 3, cells: [[0, 0], [1, 0], [2, 0]] },
    { id: "a4", direction: "across", number: 4, answer: "APE", clue: "Primate", length: 3, cells: [[0, 1], [1, 1], [2, 1]] },
    { id: "a7", direction: "across", number: 7, answer: "TEN", clue: "Two hands, fingers-wise", length: 3, cells: [[0, 2], [1, 2], [2, 2]] },
    { id: "d1", direction: "down", number: 1, answer: "CAT", clue: "Feline", length: 3, cells: [[0, 0], [0, 1], [0, 2]] },
    { id: "d2", direction: "down", number: 2, answer: "APE", clue: "Climbing primate", length: 3, cells: [[1, 0], [1, 1], [1, 2]] },
    { id: "d3", direction: "down", number: 3, answer: "TEN", clue: "Double five", length: 3, cells: [[2, 0], [2, 1], [2, 2]] },
  ],
  metadata: {
    difficulty: "easy",
    themeTags: ["pokemon", "smoke"],
    source: "curated",
    contestMode: false,
    byline: "Codex",
    constructor: "Smoke Suite",
    editor: "QA",
    notes: "Fixture puzzle for Playwright smoke coverage.",
  },
};

const crypticPuzzle = {
  id: "puz_cryptic_smoke",
  date: "2026-03-10",
  gameType: "cryptic",
  title: "Smoke Test Cryptic",
  publishedAt: "2026-03-10T09:00:00Z",
  timezone: "Europe/London",
  grid: {
    width: 4,
    height: 1,
    cells: [
      { x: 0, y: 0, isBlock: false, solution: "M", entryIdAcross: "c1", entryIdDown: null },
      { x: 1, y: 0, isBlock: false, solution: "E", entryIdAcross: "c1", entryIdDown: null },
      { x: 2, y: 0, isBlock: false, solution: "W", entryIdAcross: "c1", entryIdDown: null },
      { x: 3, y: 0, isBlock: false, solution: null, entryIdAcross: null, entryIdDown: null },
    ],
  },
  entries: [
    {
      id: "c1",
      direction: "across",
      number: 1,
      answer: "MEW",
      clue: "Legendary psychic Pokemon we remodeled (3)",
      length: 3,
      enumeration: "3",
      cells: [[0, 0], [1, 0], [2, 0]],
      mechanism: "anagram",
      wordplayMetadata: { indicator: "remodeled", fodder: "WE" },
    },
  ],
  metadata: {
    difficulty: "medium",
    themeTags: ["pokemon", "cryptic"],
    source: "curated",
    contestMode: false,
    byline: "Codex",
  },
};

const connectionsPuzzle = {
  id: "puz_connections_smoke",
  date: "2026-03-10",
  gameType: "connections",
  title: "Smoke Test Connections",
  publishedAt: "2026-03-10T09:00:00Z",
  timezone: "Europe/London",
  grid: {
    width: 4,
    height: 4,
    cells: Array.from({ length: 16 }, (_, index) => ({
      x: index % 4,
      y: Math.floor(index / 4),
      isBlock: false,
      solution: null,
      entryIdAcross: null,
      entryIdDown: null,
    })),
  },
  entries: [],
  metadata: {
    difficulty: "easy",
    themeTags: ["pokemon", "connections"],
    source: "curated",
    connections: {
      version: 1,
      difficultyOrder: ["yellow", "green", "blue", "purple"],
      groups: [
        { id: "yellow", title: "Starter Pokemon", difficulty: "yellow", labels: ["Bulbasaur", "Charmander", "Squirtle", "Pikachu"] },
        { id: "green", title: "Eeveelutions", difficulty: "green", labels: ["Vaporeon", "Jolteon", "Flareon", "Umbreon"] },
        { id: "blue", title: "Ghost Types", difficulty: "blue", labels: ["Gastly", "Haunter", "Gengar", "Misdreavus"] },
        { id: "purple", title: "Legendary Birds", difficulty: "purple", labels: ["Articuno", "Zapdos", "Moltres", "Lugia"] },
      ],
      tiles: [
        { id: "t1", label: "Bulbasaur", groupId: "yellow" },
        { id: "t2", label: "Charmander", groupId: "yellow" },
        { id: "t3", label: "Squirtle", groupId: "yellow" },
        { id: "t4", label: "Pikachu", groupId: "yellow" },
        { id: "t5", label: "Vaporeon", groupId: "green" },
        { id: "t6", label: "Jolteon", groupId: "green" },
        { id: "t7", label: "Flareon", groupId: "green" },
        { id: "t8", label: "Umbreon", groupId: "green" },
        { id: "t9", label: "Gastly", groupId: "blue" },
        { id: "t10", label: "Haunter", groupId: "blue" },
        { id: "t11", label: "Gengar", groupId: "blue" },
        { id: "t12", label: "Misdreavus", groupId: "blue" },
        { id: "t13", label: "Articuno", groupId: "purple" },
        { id: "t14", label: "Zapdos", groupId: "purple" },
        { id: "t15", label: "Moltres", groupId: "purple" },
        { id: "t16", label: "Lugia", groupId: "purple" },
      ],
    },
  },
};

const archivePage = {
  items: [
    {
      id: crosswordPuzzle.id,
      date: crosswordPuzzle.date,
      gameType: "crossword",
      title: crosswordPuzzle.title,
      difficulty: "easy",
      publishedAt: crosswordPuzzle.publishedAt,
      noteSnippet: "Crossword fixture",
    },
    {
      id: crypticPuzzle.id,
      date: crypticPuzzle.date,
      gameType: "cryptic",
      title: crypticPuzzle.title,
      difficulty: "medium",
      publishedAt: crypticPuzzle.publishedAt,
      noteSnippet: "Cryptic fixture",
    },
    {
      id: connectionsPuzzle.id,
      date: connectionsPuzzle.date,
      gameType: "connections",
      title: connectionsPuzzle.title,
      difficulty: "easy",
      publishedAt: connectionsPuzzle.publishedAt,
      noteSnippet: "Connections fixture",
    },
  ],
  cursor: null,
  hasMore: false,
};

const personalStats = {
  sessionIds: ["sess_crossword_smoke", "sess_cryptic_smoke"],
  windowDays: 30,
  timezone: "Europe/London",
  crossword: {
    pageViews: 4,
    completions: 2,
    completionRate: 0.5,
    medianSolveTimeMs: 82000,
    cleanSolveRate: 0.5,
    streakCurrent: 2,
    streakBest: 3,
  },
  cryptic: {
    pageViews: 2,
    completions: 1,
    completionRate: 0.5,
    medianSolveTimeMs: 61000,
    cleanSolveRate: 1,
    streakCurrent: 1,
    streakBest: 1,
  },
  connections: {
    pageViews: 1,
    completions: 1,
    completionRate: 1,
    medianSolveTimeMs: 45000,
    cleanSolveRate: 0,
    streakCurrent: 1,
    streakBest: 1,
  },
  historyByGameType: {
    crossword: [
      { date: "2026-03-08", pageViews: 1, completions: 1, cleanCompletions: 1 },
      { date: "2026-03-09", pageViews: 2, completions: 0, cleanCompletions: 0 },
      { date: "2026-03-10", pageViews: 1, completions: 1, cleanCompletions: 0 },
    ],
    cryptic: [{ date: "2026-03-10", pageViews: 2, completions: 1, cleanCompletions: 1 }],
    connections: [{ date: "2026-03-10", pageViews: 1, completions: 1, cleanCompletions: 0 }],
  },
};

const guestAuthSession = {
  authenticated: false,
  playerToken: null,
  username: null,
  profile: null,
  mergedGuestToken: null,
};

const leaderboardPage = {
  items: [
    {
      rank: 1,
      playerToken: "anon_ash",
      displayName: "Ash",
      publicSlug: "ash-ketchum",
      completions: 7,
      averageSolveTimeMs: 65000,
      bestSolveTimeMs: 54000,
    },
    {
      rank: 2,
      playerToken: "anon_misty",
      displayName: "Misty",
      publicSlug: "misty",
      completions: 6,
      averageSolveTimeMs: 71000,
      bestSolveTimeMs: 59000,
    },
  ],
  cursor: null,
  hasMore: false,
  dateFrom: "2026-03-04",
  dateTo: "2026-03-10",
};

const playerProfile = {
  playerToken: "anon_smoke_player",
  displayName: "Ash",
  publicSlug: "ash-ketchum",
  leaderboardVisible: true,
  hasAccount: false,
};

const publicPlayerStats = {
  profile: {
    displayName: "Ash",
    publicSlug: "ash-ketchum",
    leaderboardVisible: true,
    hasAccount: true,
    createdAt: "2026-03-10T09:00:00Z",
    updatedAt: "2026-03-10T09:00:00Z",
  },
  stats: personalStats,
};

const challengeDetail = {
  challenge: {
    code: "SMOKE1",
    gameType: "crossword",
    puzzleDate: "2026-03-10",
    memberCount: 2,
  },
  joined: false,
  items: [
    {
      rank: 1,
      playerToken: "anon_ash",
      displayName: "Ash",
      publicSlug: "ash-ketchum",
      solveTimeMs: 54000,
      usedAssists: false,
      usedReveals: false,
    },
  ],
  cursor: null,
  hasMore: false,
};

const joinedChallengeDetail = {
  ...challengeDetail,
  joined: true,
};

const textOnlyExport = {
  id: crosswordPuzzle.id,
  date: crosswordPuzzle.date,
  gameType: "crossword",
  title: "Smoke Test Crossword Text Export",
  timezone: "Europe/London",
  metadata: {
    difficulty: "easy",
    themeTags: ["pokemon", "smoke"],
    contestMode: false,
  },
  grid: {
    width: 3,
    height: 3,
    rows: ["...", "...", "..."],
  },
  entries: [
    { id: "a1", number: 1, direction: "across", clue: "Starter pet", length: 3, enumeration: "3", cells: [[0, 0], [1, 0], [2, 0]] },
    { id: "d1", number: 1, direction: "down", clue: "Feline", length: 3, enumeration: "3", cells: [[0, 0], [0, 1], [0, 2]] },
  ],
  redactedAnswers: true,
};

async function fulfillJson(route: Route, body: unknown, status = 200) {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
  });
}

async function mockApi(page: Page) {
  await page.addInitScript(() => {
    window.localStorage.setItem("crossword:session-id", "sess_crossword_smoke");
    window.localStorage.setItem("cryptic:session-id", "sess_cryptic_smoke");
    window.localStorage.setItem("connections:session-id", "sess_connections_smoke");
    window.localStorage.setItem("player:token:v1", "anon_smoke_player");
    Object.defineProperty(navigator, "sendBeacon", {
      configurable: true,
      value: () => true,
    });
  });

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const { pathname, searchParams } = url;

    if (pathname === "/api/v1/puzzles/daily" && request.method() === "GET") {
      const gameType = searchParams.get("gameType");
      if (gameType === "cryptic") return fulfillJson(route, { data: crypticPuzzle });
      if (gameType === "connections") return fulfillJson(route, { data: connectionsPuzzle });
      return fulfillJson(route, { data: crosswordPuzzle });
    }

    if (pathname === "/api/v1/puzzles/archive" && request.method() === "GET") {
      return fulfillJson(route, { data: archivePage });
    }

    if (pathname === "/api/v1/puzzles/stats/personal" && request.method() === "GET") {
      return fulfillJson(route, { data: personalStats });
    }

    if (pathname === "/api/v1/auth/session" && request.method() === "GET") {
      return fulfillJson(route, { data: guestAuthSession });
    }

    if (pathname === "/api/v1/puzzles/profile" && request.method() === "GET") {
      return fulfillJson(route, { data: playerProfile });
    }

    if (pathname === "/api/v1/puzzles/profile" && request.method() === "PUT") {
      return fulfillJson(route, { data: playerProfile });
    }

    if (pathname === "/api/v1/puzzles/leaderboard" && request.method() === "GET") {
      return fulfillJson(route, { data: leaderboardPage });
    }

    if (pathname === "/api/v1/puzzles/players/ash-ketchum" && request.method() === "GET") {
      return fulfillJson(route, { data: publicPlayerStats });
    }

    if (pathname === "/api/v1/puzzles/export/text" && request.method() === "GET") {
      return fulfillJson(route, { data: textOnlyExport });
    }

    if (pathname === "/api/v1/puzzles/progress" && request.method() === "GET") {
      return fulfillJson(route, { data: null });
    }

    if (pathname === "/api/v1/puzzles/progress" && request.method() === "PUT") {
      return fulfillJson(route, {
        data: {
          id: 1,
          playerToken: "anon_smoke_player",
          key: "smoke-progress",
          gameType: "crossword",
          puzzleId: crosswordPuzzle.id,
          progress: {},
          updatedAt: "2026-03-10T09:00:00Z",
          createdAt: "2026-03-10T09:00:00Z",
        },
      });
    }

    if (pathname === "/api/v1/puzzles/challenges" && request.method() === "POST") {
      return fulfillJson(route, { data: { code: "SMOKE1" } });
    }

    if (pathname === "/api/v1/puzzles/challenges/SMOKE1" && request.method() === "GET") {
      return fulfillJson(route, { data: challengeDetail });
    }

    if (pathname === "/api/v1/puzzles/challenges/SMOKE1/join" && request.method() === "POST") {
      return fulfillJson(route, { data: joinedChallengeDetail });
    }

    if (
      pathname === "/api/v1/puzzles/crossword/telemetry" ||
      pathname === "/api/v1/puzzles/cryptic/telemetry" ||
      pathname === "/api/v1/puzzles/connections/telemetry" ||
      pathname === "/api/v1/puzzles/cryptic/clue-feedback" ||
      pathname === "/api/v1/puzzles/leaderboard/submit" ||
      pathname === "/api/v1/puzzles/client-errors"
    ) {
      return fulfillJson(route, { data: { ok: true } });
    }

    if (pathname === "/api/v1/admin/reserve" && request.method() === "GET") {
      return fulfillJson(route, { items: [], timezone: "Europe/London" });
    }

    if (pathname === "/api/v1/admin/jobs" && request.method() === "GET") {
      return fulfillJson(route, { items: [] });
    }

    if (pathname === "/api/v1/admin/alerts" && request.method() === "GET") {
      return fulfillJson(route, { items: [] });
    }

    if (pathname === "/api/v1/admin/analytics/summary" && request.method() === "GET") {
      return fulfillJson(route, {
        windowDays: 30,
        timezone: "Europe/London",
        dailyActiveUsers: { latest: 2, average: 2, series: [] },
        crossword: { pageViewSessions: 2, completedSessions: 1, completionRate: 0.5, medianSolveTimeMs: 82000, dropoffByEventType: [] },
      });
    }

    return fulfillJson(route, { error: `Unhandled mock for ${pathname}` }, 500);
  });
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("main navigation routes render and core interactions work", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByRole("link", { name: "Daily Crossword" })).toBeVisible();
  await page.getByRole("link", { name: "Daily Crossword" }).click();
  await expect(page).toHaveURL(/\/daily$/);
  await expect(page.getByRole("button", { name: "Check Entry" })).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: "Cryptic Clue" }).click();
  await expect(page).toHaveURL(/\/cryptic$/);
  await expect(page.getByRole("heading", { name: "Cryptic Clue" })).toBeVisible();
  await page.getByRole("button", { name: "Hint 1" }).click();
  await expect(page.getByText("Hint 1 shown.")).toBeVisible();

  await page.goto("/");
  await page.getByRole("link", { name: "Daily Connections" }).click();
  await expect(page).toHaveURL(/\/connections$/);
  await expect(page.getByRole("heading", { name: "Daily Connections" })).toBeVisible();
  await page.getByRole("button", { name: "Bulbasaur" }).click();
  await page.getByRole("button", { name: "Charmander" }).click();
  await page.getByRole("button", { name: "Squirtle" }).click();
  await page.getByRole("button", { name: "Pikachu" }).click();
  await page.getByRole("button", { name: "Submit Group" }).click();
  await expect(page.getByRole("heading", { name: "Starter Pokemon" })).toBeVisible();
});

test("secondary routes render with mocked data", async ({ page }) => {
  await page.goto("/archive");
  await expect(page.getByRole("heading", { name: "Archive" })).toBeVisible();
  await expect(page.getByText("Smoke Test Crossword")).toBeVisible();

  await page.goto("/stats");
  await expect(page.getByRole("heading", { name: "Your Stats" })).toBeVisible();
  await expect(page.getByText("Completion Rate")).toBeVisible();

  await page.goto("/leaderboard");
  await expect(page.getByRole("heading", { name: "Leaderboard" })).toBeVisible();
  await expect(page.getByText("Your Account")).toBeVisible();
  await expect(page.getByRole("cell", { name: "Ash" })).toBeVisible();

  await page.goto("/account");
  await expect(page.getByRole("heading", { name: "Account", exact: true })).toBeVisible();
  await expect(page.getByText("This will claim the guest progress currently stored on this device.")).toBeVisible();

  await page.goto("/players/ash-ketchum");
  await expect(page.getByRole("heading", { name: "Ash" })).toBeVisible();
  await expect(page.getByText("Public stats page for @ash-ketchum.")).toBeVisible();

  await page.goto("/admin");
  await expect(page.getByRole("heading", { name: "Admin Console" })).toBeVisible();
  await expect(page.getByText("Enter and save the admin token to load console data and run admin actions.")).toBeVisible();
});

test("direct routes for challenge and text-only render", async ({ page }) => {
  await page.goto("/challenge/SMOKE1");
  await expect(page.getByRole("heading", { name: "Challenge" })).toBeVisible();
  await expect(page.getByText("Code: SMOKE1")).toBeVisible();
  await page.getByRole("button", { name: "Join Challenge" }).click();
  await expect(page.getByText("You joined this challenge.")).toBeVisible();

  await page.goto("/text-only?gameType=crossword&date=2026-03-10");
  await expect(page.getByRole("heading", { name: "Text-Only Puzzle View" })).toBeVisible();
  await expect(page.getByText("Smoke Test Crossword Text Export")).toBeVisible();
  await expect(page.getByText("Grid Structure")).toBeVisible();
});
