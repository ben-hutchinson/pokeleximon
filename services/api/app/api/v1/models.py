from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

PuzzleGameType = Literal["crossword", "cryptic", "connections"]
CompetitiveGameType = Literal["crossword", "cryptic"]


class HealthResponse(BaseModel):
    status: str
    version: str


class Cell(BaseModel):
    x: int
    y: int
    isBlock: bool
    solution: str | None = None
    entryIdAcross: str | None = None
    entryIdDown: str | None = None


class Grid(BaseModel):
    width: int
    height: int
    cells: list[Cell]


class Entry(BaseModel):
    id: str
    direction: Literal["across", "down"]
    number: int
    answer: str
    clue: str
    length: int
    cells: list[tuple[int, int]]
    sourceRef: str | None = None
    mechanism: str | None = None
    enumeration: str | None = None
    wordplayPlan: str | None = None
    wordplayMetadata: dict[str, Any] | None = None


class PuzzleMetadata(BaseModel):
    difficulty: Literal["easy", "medium", "hard"]
    themeTags: list[str] = Field(default_factory=list)
    source: Literal["pokeapi", "curated"]
    generatorVersion: str | None = None
    contestMode: bool = False
    byline: str | None = None
    constructor: str | None = None
    editor: str | None = None
    notes: str | None = None
    connections: dict[str, Any] | None = None


class Puzzle(BaseModel):
    id: str
    date: str
    gameType: PuzzleGameType
    title: str
    publishedAt: str
    timezone: str
    grid: Grid
    entries: list[Entry]
    metadata: PuzzleMetadata


class PuzzleSummary(BaseModel):
    id: str
    date: str
    gameType: PuzzleGameType
    title: str
    difficulty: Literal["easy", "medium", "hard"]
    publishedAt: str
    noteSnippet: str | None = None


class ArchivePage(BaseModel):
    items: list[PuzzleSummary]
    cursor: str | None
    hasMore: bool


class ResponseMeta(BaseModel):
    redactedAnswers: bool = False


class PuzzleResponse(BaseModel):
    data: Puzzle
    meta: ResponseMeta


class PuzzleSummaryResponse(BaseModel):
    data: PuzzleSummary


class ArchiveResponse(BaseModel):
    data: ArchivePage


class JobResponse(BaseModel):
    jobId: str
    status: Literal["queued", "running", "succeeded", "failed"]


class PersonalStatsBucket(BaseModel):
    pageViews: int = 0
    completions: int = 0
    completionRate: float | None = None
    medianSolveTimeMs: int | None = None
    cleanSolveRate: float | None = None
    streakCurrent: int = 0
    streakBest: int = 0


class PersonalStatsDay(BaseModel):
    date: str
    pageViews: int = 0
    completions: int = 0
    cleanCompletions: int = 0


class PersonalStats(BaseModel):
    sessionIds: list[str] = Field(default_factory=list)
    windowDays: int
    timezone: str
    crossword: PersonalStatsBucket
    cryptic: PersonalStatsBucket
    connections: PersonalStatsBucket
    historyByGameType: dict[PuzzleGameType, list[PersonalStatsDay]] = Field(default_factory=dict)


class PersonalStatsResponse(BaseModel):
    data: PersonalStats


class PuzzleProgressRequest(BaseModel):
    key: str
    gameType: PuzzleGameType | None = None
    puzzleId: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    clientUpdatedAt: datetime | None = None


class PuzzleProgressRecord(BaseModel):
    id: int
    playerToken: str
    key: str
    gameType: PuzzleGameType | None = None
    puzzleId: str | None = None
    progress: dict[str, Any] = Field(default_factory=dict)
    clientUpdatedAt: str | None = None
    updatedAt: str | None = None
    createdAt: str | None = None


class PuzzleProgressResponse(BaseModel):
    data: PuzzleProgressRecord | None = None


class PlayerProfileUpdateRequest(BaseModel):
    displayName: str | None = None
    leaderboardVisible: bool | None = None


class PlayerProfileRecord(BaseModel):
    playerToken: str
    displayName: str
    publicSlug: str
    leaderboardVisible: bool = True
    hasAccount: bool = False
    createdAt: str | None = None
    updatedAt: str | None = None


class PlayerProfileResponse(BaseModel):
    data: PlayerProfileRecord


class AuthSignupRequest(BaseModel):
    username: str
    password: str
    guestPlayerToken: str | None = None


class AuthLoginRequest(BaseModel):
    username: str
    password: str
    guestPlayerToken: str | None = None
    mergeGuestData: bool = True


class AuthSessionRecord(BaseModel):
    authenticated: bool = False
    playerToken: str | None = None
    username: str | None = None
    profile: PlayerProfileRecord | None = None
    mergedGuestToken: str | None = None


class AuthSessionResponse(BaseModel):
    data: AuthSessionRecord


class PublicPlayerProfileRecord(BaseModel):
    displayName: str
    publicSlug: str
    leaderboardVisible: bool = True
    hasAccount: bool = False
    createdAt: str | None = None
    updatedAt: str | None = None


class PublicPlayerStatsRecord(BaseModel):
    profile: PublicPlayerProfileRecord
    stats: PersonalStats


class PublicPlayerStatsResponse(BaseModel):
    data: PublicPlayerStatsRecord


class ChallengeCreateRequest(BaseModel):
    gameType: CompetitiveGameType
    puzzleId: str | None = None
    date: str | None = None


class ChallengeRecord(BaseModel):
    id: int
    code: str
    gameType: CompetitiveGameType
    puzzleId: str
    puzzleDate: str
    createdByToken: str
    memberCount: int = 0
    createdAt: str | None = None


class ChallengeLeaderboardEntry(BaseModel):
    rank: int
    playerToken: str
    displayName: str
    publicSlug: str | None = None
    solveTimeMs: int | None = None
    completed: bool = False
    usedAssists: bool = False
    usedReveals: bool = False
    updatedAt: str | None = None


class ChallengeDetail(BaseModel):
    challenge: ChallengeRecord
    joined: bool = False
    items: list[ChallengeLeaderboardEntry] = Field(default_factory=list)
    cursor: str | None = None
    hasMore: bool = False


class ChallengeResponse(BaseModel):
    data: ChallengeRecord


class ChallengeJoinResponse(BaseModel):
    data: ChallengeDetail


class ChallengeDetailResponse(BaseModel):
    data: ChallengeDetail


class LeaderboardSubmitRequest(BaseModel):
    gameType: CompetitiveGameType
    puzzleId: str
    puzzleDate: str
    completed: bool = True
    solveTimeMs: int | None = None
    usedAssists: bool = False
    usedReveals: bool = False
    sessionId: str | None = None


class LeaderboardSubmissionRecord(BaseModel):
    id: int
    playerToken: str
    gameType: CompetitiveGameType
    puzzleId: str
    puzzleDate: str
    completed: bool = False
    solveTimeMs: int | None = None
    usedAssists: bool = False
    usedReveals: bool = False
    sessionId: str | None = None
    submittedAt: str | None = None
    updatedAt: str | None = None


class LeaderboardSubmitResponse(BaseModel):
    data: LeaderboardSubmissionRecord


class GlobalLeaderboardEntry(BaseModel):
    rank: int
    playerToken: str
    displayName: str
    publicSlug: str | None = None
    completions: int
    averageSolveTimeMs: int | None = None
    bestSolveTimeMs: int | None = None


class GlobalLeaderboardPage(BaseModel):
    scope: Literal["daily", "weekly"]
    gameType: CompetitiveGameType
    dateFrom: str
    dateTo: str
    items: list[GlobalLeaderboardEntry] = Field(default_factory=list)
    cursor: str | None = None
    hasMore: bool = False


class GlobalLeaderboardResponse(BaseModel):
    data: GlobalLeaderboardPage


class CrypticTelemetryRequest(BaseModel):
    puzzleId: str
    eventType: Literal[
        "page_view",
        "clue_view",
        "guess_submit",
        "check_click",
        "hint_click",
        "reveal_click",
        "abandon",
    ]
    sessionId: str | None = None
    candidateId: int | None = None
    eventValue: dict[str, Any] = Field(default_factory=dict)
    clientTs: datetime | None = None


class CrypticTelemetryEvent(BaseModel):
    id: int
    puzzleId: str
    candidateId: int | None = None
    eventType: str
    sessionId: str | None = None
    eventValue: dict[str, Any] = Field(default_factory=dict)
    clientTs: str | None = None
    createdAt: str


class CrypticTelemetryResponse(BaseModel):
    data: CrypticTelemetryEvent


class CrypticClueFeedbackRequest(BaseModel):
    puzzleId: str
    entryId: str
    rating: Literal["up", "down"]
    reasonTags: list[str] = Field(default_factory=list)
    sessionId: str
    candidateId: int | None = None
    mechanism: str | None = None
    clueText: str | None = None
    clientTs: datetime | None = None


class CrypticClueFeedbackResponse(BaseModel):
    data: CrypticTelemetryEvent
    duplicate: bool = False


class CrosswordTelemetryRequest(BaseModel):
    puzzleId: str
    eventType: Literal[
        "page_view",
        "clue_view",
        "first_input",
        "check_entry",
        "check_square",
        "reveal_word",
        "reveal_square",
        "check_all",
        "reveal_all",
        "clear_all",
        "autocheck_toggle",
        "completed",
        "abandon",
    ]
    sessionId: str | None = None
    eventValue: dict[str, Any] = Field(default_factory=dict)
    clientTs: datetime | None = None


class CrosswordTelemetryEvent(BaseModel):
    id: int
    puzzleId: str
    eventType: str
    sessionId: str | None = None
    eventValue: dict[str, Any] = Field(default_factory=dict)
    clientTs: str | None = None
    createdAt: str


class CrosswordTelemetryResponse(BaseModel):
    data: CrosswordTelemetryEvent


class ConnectionsTelemetryRequest(BaseModel):
    puzzleId: str
    eventType: Literal[
        "page_view",
        "tile_select",
        "tile_deselect",
        "submit_group",
        "one_away",
        "solve_group",
        "mistake",
        "shuffle",
        "completed",
        "abandon",
    ]
    sessionId: str | None = None
    eventValue: dict[str, Any] = Field(default_factory=dict)
    clientTs: datetime | None = None


class ConnectionsTelemetryEvent(BaseModel):
    id: int
    puzzleId: str
    eventType: str
    sessionId: str | None = None
    eventValue: dict[str, Any] = Field(default_factory=dict)
    clientTs: str | None = None
    createdAt: str


class ConnectionsTelemetryResponse(BaseModel):
    data: ConnectionsTelemetryEvent


class ClientErrorRequest(BaseModel):
    message: str
    stack: str | None = None
    source: Literal["frontend"]
    route: str | None = None
    userAgent: str | None = None
    appVersion: str | None = None
    eventType: Literal["error", "unhandledrejection"] = "error"
    details: dict[str, Any] = Field(default_factory=dict)


class ClientErrorResponse(BaseModel):
    ok: bool
