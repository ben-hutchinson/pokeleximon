import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { getStoredPlayerToken, putPlayerProfile } from "../api/puzzles";
import Layout from "../components/Layout";

export default function Account() {
  const { authenticated, loading, logIn, logOut, playerToken, profile, refreshSession, signUp, username } = useAuth();
  const [loginUsername, setLoginUsername] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [signupUsername, setSignupUsername] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [mergeGuestData, setMergeGuestData] = useState(true);
  const [displayNameDraft, setDisplayNameDraft] = useState("");
  const [visibilityDraft, setVisibilityDraft] = useState(true);
  const [status, setStatus] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<"login" | "signup" | "profile" | "logout" | null>(null);

  useEffect(() => {
    setDisplayNameDraft(profile?.displayName ?? "");
    setVisibilityDraft(profile?.leaderboardVisible ?? true);
  }, [profile?.displayName, profile?.leaderboardVisible]);

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
    if (!profile) return;
    setBusyAction("profile");
    setStatus(null);
    try {
      await putPlayerProfile({
        playerToken: profile.playerToken,
        displayName: displayNameDraft,
        leaderboardVisible: visibilityDraft,
      });
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
      <section className="page-section" aria-labelledby="account-heading" aria-busy={loading}>
        <div className="section-header">
          <h2 id="account-heading">Account</h2>
          <p>Claim your guest progress, sign in on other devices, and manage the public profile shown on leaderboards.</p>
        </div>

        {status ? <div className="card panel__meta">{status}</div> : null}

        {!authenticated ? (
          <div className="stats-grid">
            <form className="card leaderboard-profile" onSubmit={onSignup}>
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

            <form className="card leaderboard-profile" onSubmit={onLogin}>
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
                <span>Merge this device's guest progress into the account</span>
              </label>
              <button className="button secondary" type="submit" disabled={busyAction !== null}>
                {busyAction === "login" ? "Logging in..." : "Log In"}
              </button>
            </form>
          </div>
        ) : (
          <div className="stats-grid">
            <form className="card leaderboard-profile" onSubmit={onSaveProfile}>
              <h3>Public Profile</h3>
              <label>
                <span>Username</span>
                <input value={username ?? ""} readOnly />
              </label>
              <label>
                <span>Display Name</span>
                <input value={displayNameDraft} onChange={(event) => setDisplayNameDraft(event.target.value)} maxLength={40} />
              </label>
              <label className="archive-checkbox">
                <input
                  type="checkbox"
                  checked={visibilityDraft}
                  onChange={(event) => setVisibilityDraft(event.target.checked)}
                />
                <span>Show me in leaderboards</span>
              </label>
              <div className="leaderboard-profile__actions">
                <button className="button" type="submit" disabled={busyAction !== null}>
                  {busyAction === "profile" ? "Saving..." : "Save Profile"}
                </button>
                {profile ? (
                  <Link className="button ghost" to={`/players/${profile.publicSlug}`}>
                    View Public Page
                  </Link>
                ) : null}
              </div>
            </form>

            <div className="card leaderboard-profile">
              <h3>Session</h3>
              <p className="panel__meta">Signed in as <strong>{username}</strong>.</p>
              <p className="panel__meta">Canonical player token: {playerToken}</p>
              <button className="button ghost" type="button" onClick={() => void onLogout()} disabled={busyAction !== null}>
                {busyAction === "logout" ? "Logging out..." : "Log Out"}
              </button>
            </div>
          </div>
        )}
      </section>
    </Layout>
  );
}
