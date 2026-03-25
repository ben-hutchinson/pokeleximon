import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { AVATAR_PRESETS } from "../components/ProfileAvatar";
import ProfileAvatar from "../components/ProfileAvatar";
import Layout from "../components/Layout";
import {
  getPersonalStats,
  getPlayerProfile,
  getPlayerStats,
  getStoredPlayerToken,
  putPlayerProfile,
  type PersonalStats,
  type PersonalStatsBucket,
  type PlayerProfile as PlayerProfileType,
  type PuzzleGameType,
} from "../api/puzzles";

const SESSION_KEYS = ["crossword:session-id", "cryptic:session-id", "connections:session-id"];
const WINDOW_OPTIONS: Array<7 | 30 | 90> = [7, 30, 90];
const GAME_OPTIONS: Array<{ value: PuzzleGameType; label: string }> = [
  { value: "crossword", label: "Crossword" },
  { value: "cryptic", label: "Cryptic" },
  { value: "connections", label: "Connections" },
];

function loadSessionIds(): string[] {
  if (typeof window === "undefined") return [];
  return Array.from(
    new Set(
      SESSION_KEYS.map((key) => window.localStorage.getItem(key) ?? "")
        .map((value) => value.trim())
        .filter((value) => value.length > 0),
    ),
  );
}

function formatPercent(value: number | null) {
  if (value === null || Number.isNaN(value)) return "N/A";
  return `${Math.round(value * 1000) / 10}%`;
}

function formatDurationMs(value: number | null) {
  if (value === null || value <= 0) return "N/A";
  const totalSeconds = Math.floor(value / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
}

function formatDay(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export default function Profile() {
  const { authenticated, loading, logIn, logOut, playerToken, profile, refreshSession, signUp, username } = useAuth();
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [signupUsername, setSignupUsername] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [mergeGuestData, setMergeGuestData] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"login" | "signup" | "profile" | "logout" | null>(null);

  const [resolvedProfile, setResolvedProfile] = useState<PlayerProfileType | null>(profile ?? null);
  const [profileLoading, setProfileLoading] = useState(false);
  const [displayNameDraft, setDisplayNameDraft] = useState("");
  const [visibilityDraft, setVisibilityDraft] = useState(true);
  const [avatarPresetDraft, setAvatarPresetDraft] = useState<string | null>(null);

  const [days, setDays] = useState<7 | 30 | 90>(30);
  const [gameType, setGameType] = useState<PuzzleGameType>("crossword");
  const [sessionIds, setSessionIds] = useState<string[] | null>(null);
  const [stats, setStats] = useState<PersonalStats | null>(null);
  const [statsLoading, setStatsLoading] = useState(false);
  const [statsError, setStatsError] = useState<string | null>(null);

  useEffect(() => {
    setSessionIds(loadSessionIds());
  }, []);

  useEffect(() => {
    if (authenticated && profile) {
      setResolvedProfile(profile);
      return;
    }
    if (!playerToken) return;
    setProfileLoading(true);
    getPlayerProfile({ playerToken })
      .then(setResolvedProfile)
      .catch(() => setResolvedProfile(null))
      .finally(() => setProfileLoading(false));
  }, [authenticated, playerToken, profile]);

  useEffect(() => {
    setDisplayNameDraft(resolvedProfile?.displayName ?? "");
    setVisibilityDraft(resolvedProfile?.leaderboardVisible ?? true);
    setAvatarPresetDraft(resolvedProfile?.avatarPreset ?? null);
  }, [resolvedProfile?.avatarPreset, resolvedProfile?.displayName, resolvedProfile?.leaderboardVisible]);

  useEffect(() => {
    if (!authenticated && sessionIds === null) return;
    setStatsLoading(true);
    setStatsError(null);
    const loadStats = authenticated ? getPlayerStats({ days }) : getPersonalStats({ days, sessionIds: sessionIds ?? undefined });
    loadStats
      .then(setStats)
      .catch((err) => setStatsError(err instanceof Error ? err.message : "Failed to load stats."))
      .finally(() => setStatsLoading(false));
  }, [authenticated, days, sessionIds]);

  const currentBucket = useMemo<PersonalStatsBucket | null>(() => {
    if (!stats) return null;
    return stats[gameType];
  }, [gameType, stats]);

  const currentHistory = useMemo(() => {
    if (!stats) return [];
    return stats.historyByGameType[gameType] ?? [];
  }, [gameType, stats]);

  const currentGameLabel = useMemo(
    () => GAME_OPTIONS.find((option) => option.value === gameType)?.label ?? "Crossword",
    [gameType],
  );

  const hasProgress = useMemo(() => {
    if (!currentBucket) return false;
    return currentBucket.pageViews > 0 || currentBucket.completions > 0;
  }, [currentBucket]);

  const maxCompletions = useMemo(() => {
    if (currentHistory.length === 0) return 1;
    return Math.max(1, ...currentHistory.map((day) => day.completions));
  }, [currentHistory]);

  const guestPlayerToken = getStoredPlayerToken() || playerToken;

  const onLogin = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusyAction("login");
    setStatus(null);
    try {
      const session = await logIn({
        username: loginUsername,
        password: loginPassword,
        guestPlayerToken,
        mergeGuestData,
      });
      setStatus(session.mergedGuestToken ? "Logged in and merged this device's guest progress." : "Logged in.");
      setLoginPassword("");
      await refreshSession();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Login failed.");
    } finally {
      setBusyAction(null);
    }
  };

  const onSignup = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusyAction("signup");
    setStatus(null);
    try {
      await signUp({
        username: signupUsername,
        password: signupPassword,
        guestPlayerToken,
      });
      setStatus("Account created and this device's guest progress claimed.");
      setSignupPassword("");
      await refreshSession();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Signup failed.");
    } finally {
      setBusyAction(null);
    }
  };

  const onSaveProfile = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!resolvedProfile) return;
    setBusyAction("profile");
    setStatus(null);
    try {
      const nextProfile = await putPlayerProfile({
        playerToken: resolvedProfile.playerToken,
        displayName: displayNameDraft,
        leaderboardVisible: visibilityDraft,
        avatarPreset: avatarPresetDraft,
      });
      setResolvedProfile(nextProfile);
      await refreshSession();
      setStatus("Profile updated.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Profile update failed.");
    } finally {
      setBusyAction(null);
    }
  };

  const onLogout = async () => {
    setBusyAction("logout");
    setStatus(null);
    try {
      await logOut();
      setStatus("Logged out. Guest mode remains available on this device.");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Logout failed.");
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <Layout>
      <section className="page-section profile-page" aria-labelledby="profile-heading" aria-busy={loading || statsLoading || profileLoading}>
        <div className="profile-page__header">
          <ProfileAvatar
            className="profile-page__avatar"
            displayName={resolvedProfile?.displayName ?? username ?? "Player"}
            avatarPreset={resolvedProfile?.avatarPreset ?? null}
            size="lg"
          />
          <div className="section-header">
            <h2 id="profile-heading">Profile</h2>
            <p>Manage your public identity, account state, and personal puzzle stats from one place.</p>
            <p className="panel__meta">
              {authenticated
                ? `Signed in as ${username ?? resolvedProfile?.displayName ?? "player"}.`
                : "Guest mode is active on this device. You can still edit your local public profile and stats view."}
            </p>
          </div>
        </div>

        {status ? <div className="card panel__meta">{status}</div> : null}

        <div className="profile-page__grid">
          <form className="card profile-card" onSubmit={onSaveProfile}>
            <div className="profile-card__header">
              <div>
                <h3>Public Profile</h3>
                <p className="panel__meta">This identity is used on leaderboards and your public player page.</p>
              </div>
              <ProfileAvatar
                displayName={displayNameDraft || resolvedProfile?.displayName || "Player"}
                avatarPreset={avatarPresetDraft}
                size="md"
              />
            </div>

            <label>
              <span>Display Name</span>
              <input value={displayNameDraft} onChange={(event) => setDisplayNameDraft(event.target.value)} maxLength={40} />
            </label>

            <div className="profile-card__avatar-picker">
              <span>Avatar Style</span>
              <div className="profile-card__avatar-options">
                <button
                  className={`profile-card__avatar-option${avatarPresetDraft === null ? " is-selected" : ""}`}
                  type="button"
                  onClick={() => setAvatarPresetDraft(null)}
                >
                  <ProfileAvatar displayName={displayNameDraft || "Player"} avatarPreset={null} size="sm" />
                  <span>Initials</span>
                </button>
                {AVATAR_PRESETS.map((preset) => (
                  <button
                    key={preset.id}
                    className={`profile-card__avatar-option${avatarPresetDraft === preset.id ? " is-selected" : ""}`}
                    type="button"
                    onClick={() => setAvatarPresetDraft(preset.id)}
                  >
                    <ProfileAvatar displayName={displayNameDraft || "Player"} avatarPreset={preset.id} size="sm" />
                    <span>{preset.label}</span>
                  </button>
                ))}
              </div>
            </div>

            <label className="archive-checkbox">
              <input
                type="checkbox"
                checked={visibilityDraft}
                onChange={(event) => setVisibilityDraft(event.target.checked)}
              />
              <span>Show me in leaderboards</span>
            </label>

            <div className="leaderboard-profile__actions">
              <button className="button" type="submit" disabled={busyAction !== null || !resolvedProfile}>
                {busyAction === "profile" ? "Saving..." : "Save Profile"}
              </button>
              {resolvedProfile ? (
                <Link className="button ghost" to={`/players/${resolvedProfile.publicSlug}`}>
                  View Public Page
                </Link>
              ) : null}
            </div>
          </form>

          {!authenticated ? (
            <>
              <form className="card profile-card" onSubmit={onSignup}>
                <h3>Create Account</h3>
                <label>
                  <span>Username</span>
                  <input value={signupUsername} onChange={(event) => setSignupUsername(event.target.value)} maxLength={32} />
                </label>
                <label>
                  <span>Password</span>
                  <input
                    type="password"
                    value={signupPassword}
                    onChange={(event) => setSignupPassword(event.target.value)}
                    minLength={8}
                  />
                </label>
                <p className="panel__meta">This will claim the guest progress currently stored on this device.</p>
                <button className="button" type="submit" disabled={busyAction !== null}>
                  {busyAction === "signup" ? "Creating..." : "Create Account"}
                </button>
              </form>

              <form className="card profile-card" onSubmit={onLogin}>
                <h3>Log In</h3>
                <label>
                  <span>Username</span>
                  <input value={loginUsername} onChange={(event) => setLoginUsername(event.target.value)} maxLength={32} />
                </label>
                <label>
                  <span>Password</span>
                  <input
                    type="password"
                    value={loginPassword}
                    onChange={(event) => setLoginPassword(event.target.value)}
                    minLength={8}
                  />
                </label>
                <label className="archive-checkbox">
                  <input type="checkbox" checked={mergeGuestData} onChange={(event) => setMergeGuestData(event.target.checked)} />
                  <span>Merge this device&apos;s guest progress into the account</span>
                </label>
                <button className="button secondary" type="submit" disabled={busyAction !== null}>
                  {busyAction === "login" ? "Logging in..." : "Log In"}
                </button>
              </form>
            </>
          ) : (
            <div className="card profile-card">
              <h3>Session</h3>
              <p className="panel__meta">Signed in as <strong>{username}</strong>.</p>
              <p className="panel__meta">Canonical player token: {playerToken}</p>
              <button className="button ghost" type="button" onClick={() => void onLogout()} disabled={busyAction !== null}>
                {busyAction === "logout" ? "Logging out..." : "Log Out"}
              </button>
            </div>
          )}
        </div>

        <section className="card profile-page__stats" aria-labelledby="profile-stats-heading">
          <div className="section-header">
            <h3 id="profile-stats-heading">Your Stats</h3>
            <p>{authenticated ? "Server-side performance metrics for your account." : "Local performance metrics from this device's sessions."}</p>
          </div>

          <div className="stats-controls" role="group" aria-label="Stats game filter">
            {GAME_OPTIONS.map((option) => (
              <button
                key={option.value}
                className={`button ghost${gameType === option.value ? " is-active" : ""}`}
                type="button"
                onClick={() => setGameType(option.value)}
                aria-pressed={gameType === option.value}
              >
                {option.label}
              </button>
            ))}
          </div>

          <div className="stats-controls" role="group" aria-label="Stats window filter">
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option}
                className={`button ghost${days === option ? " is-active" : ""}`}
                type="button"
                onClick={() => setDays(option)}
                aria-pressed={days === option}
              >
                {option} days
              </button>
            ))}
          </div>

          {statsError ? (
            <div className="error" role="alert">
              {statsError}
            </div>
          ) : null}

          {!authenticated && sessionIds !== null && sessionIds.length === 0 ? (
            <div className="card">No local sessions found yet. Play a puzzle first, then return to see your stats.</div>
          ) : null}

          {stats ? (
            <>
              <div className="stats-grid">
                <article className="card stats-card">
                  <h3>Completion Rate</h3>
                  <strong>{formatPercent(currentBucket?.completionRate ?? null)}</strong>
                </article>
                <article className="card stats-card">
                  <h3>Median Solve Time</h3>
                  <strong>{formatDurationMs(currentBucket?.medianSolveTimeMs ?? null)}</strong>
                </article>
                <article className="card stats-card">
                  <h3>Clean-Solve Rate</h3>
                  <strong>{formatPercent(currentBucket?.cleanSolveRate ?? null)}</strong>
                </article>
                <article className="card stats-card">
                  <h3>Current Streak</h3>
                  <strong>{currentBucket?.streakCurrent ?? 0}</strong>
                </article>
                <article className="card stats-card">
                  <h3>Best Streak</h3>
                  <strong>{currentBucket?.streakBest ?? 0}</strong>
                </article>
                <article className="card stats-card">
                  <h3>Completions</h3>
                  <strong>{currentBucket?.completions ?? 0}</strong>
                </article>
              </div>

              {!hasProgress ? (
                <div className="card">No {currentGameLabel.toLowerCase()} activity in this window yet. Try switching games or expanding the date range.</div>
              ) : (
                <section className="card stats-history" aria-label={`${currentGameLabel} history`}>
                  <h3>{currentGameLabel} History</h3>
                  <div className="stats-history__rows">
                    {currentHistory.map((day) => {
                      const width = Math.round((day.completions / maxCompletions) * 100);
                      return (
                        <div className="stats-history__row" key={day.date}>
                          <div className="stats-history__date">{formatDay(day.date)}</div>
                          <div className="stats-history__bar-wrap" aria-hidden="true">
                            <div className="stats-history__bar" style={{ width: `${width}%` }} />
                          </div>
                          <div className="stats-history__value">
                            {day.completions} solved
                            {day.cleanCompletions > 0 ? ` (${day.cleanCompletions} clean)` : ""}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </section>
              )}
            </>
          ) : null}
        </section>
      </section>
    </Layout>
  );
}
