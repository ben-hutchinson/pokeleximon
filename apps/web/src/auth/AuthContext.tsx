import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import {
  getAuthSession,
  getOrCreatePlayerToken,
  logIn as apiLogIn,
  logOut as apiLogOut,
  setStoredPlayerToken,
  signUp as apiSignUp,
  type AuthSession,
  type PlayerProfile,
} from "../api/puzzles";

type AuthContextValue = {
  loading: boolean;
  authenticated: boolean;
  playerToken: string;
  username: string | null;
  profile: PlayerProfile | null;
  refreshSession: () => Promise<AuthSession>;
  signUp: (params: { username: string; password: string; guestPlayerToken?: string | null }) => Promise<AuthSession>;
  logIn: (params: {
    username: string;
    password: string;
    guestPlayerToken?: string | null;
    mergeGuestData?: boolean;
  }) => Promise<AuthSession>;
  logOut: () => Promise<AuthSession>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

function normalizeSession(session: AuthSession, fallbackPlayerToken: string) {
  const playerToken = (session.playerToken || "").trim() || fallbackPlayerToken;
  if (session.authenticated && session.playerToken) {
    setStoredPlayerToken(session.playerToken);
  }
  return {
    authenticated: Boolean(session.authenticated),
    playerToken,
    username: session.username?.trim() || null,
    profile: session.profile ?? null,
  };
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [authenticated, setAuthenticated] = useState(false);
  const [playerToken, setPlayerToken] = useState("");
  const [username, setUsername] = useState<string | null>(null);
  const [profile, setProfile] = useState<PlayerProfile | null>(null);

  const applySession = useCallback((session: AuthSession) => {
    const fallbackPlayerToken = getOrCreatePlayerToken();
    const next = normalizeSession(session, fallbackPlayerToken);
    setAuthenticated(next.authenticated);
    setPlayerToken(next.playerToken);
    setUsername(next.username);
    setProfile(next.profile);
    return session;
  }, []);

  const refreshSession = useCallback(async () => {
    const session = await getAuthSession();
    return applySession(session);
  }, [applySession]);

  const signUp = useCallback(async (params: { username: string; password: string; guestPlayerToken?: string | null }) => {
    const session = await apiSignUp(params);
    return applySession(session);
  }, [applySession]);

  const logIn = useCallback(async (params: {
    username: string;
    password: string;
    guestPlayerToken?: string | null;
    mergeGuestData?: boolean;
  }) => {
    const session = await apiLogIn(params);
    return applySession(session);
  }, [applySession]);

  const logOut = useCallback(async () => {
    const session = await apiLogOut();
    const fallbackPlayerToken = getOrCreatePlayerToken();
    setAuthenticated(false);
    setPlayerToken(fallbackPlayerToken);
    setUsername(null);
    setProfile(null);
    return session;
  }, []);

  useEffect(() => {
    const fallbackPlayerToken = getOrCreatePlayerToken();
    setPlayerToken(fallbackPlayerToken);
    getAuthSession()
      .then((session) => {
        applySession(session);
      })
      .catch(() => {
        setAuthenticated(false);
        setPlayerToken(fallbackPlayerToken);
      })
      .finally(() => setLoading(false));
  }, [applySession]);

  const value = useMemo<AuthContextValue>(
    () => ({
      loading,
      authenticated,
      playerToken,
      username,
      profile,
      refreshSession,
      signUp,
      logIn,
      logOut,
    }),
    [authenticated, loading, logIn, logOut, playerToken, profile, refreshSession, signUp, username],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const value = useContext(AuthContext);
  if (!value) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return value;
}
