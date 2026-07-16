import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { postJSON } from "../api/client";

type AuthStatus = "loading" | "authed" | "anon";

interface AuthContextValue {
  status: AuthStatus;
  username: string | null;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue>({
  status: "loading",
  username: null,
  login: async () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [username, setUsername] = useState<string | null>(null);

  const checkAuth = useCallback(() => {
    // Plain fetch, not apiFetch/getJSON — going through the CSRF wrapper here
    // would dispatch auth:unauthorized on a 401 and create a listen/dispatch
    // loop with this same effect.
    fetch("/api/auth/me", { headers: { Accept: "application/json" } })
      .then((res) => {
        if (!res.ok) throw new Error("not authenticated");
        return res.json();
      })
      .then((data: { username: string }) => {
        setUsername(data.username);
        setStatus("authed");
      })
      .catch(() => {
        setUsername(null);
        setStatus("anon");
      });
  }, []);

  useEffect(() => {
    checkAuth();
    const onUnauthorized = () => {
      setUsername(null);
      setStatus("anon");
    };
    window.addEventListener("auth:unauthorized", onUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", onUnauthorized);
  }, [checkAuth]);

  const login = useCallback(async (u: string, p: string) => {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username: u, password: p }),
    });
    if (!res.ok) {
      if (res.status === 429) throw new Error("Too many failed attempts. Try again later.");
      if (res.status === 503) throw new Error("Login is not configured on the server.");
      throw new Error("Invalid username or password.");
    }
    setUsername(u);
    setStatus("authed");
  }, []);

  const logout = useCallback(async () => {
    try {
      // postJSON (not plain fetch) so the CSRF header rides along — the
      // logout route sits behind require_auth like every other mutation.
      await postJSON("/api/auth/logout", {});
    } catch {
      /* falling through to anon either way */
    } finally {
      setUsername(null);
      setStatus("anon");
    }
  }, []);

  const value = useMemo(
    () => ({ status, username, login, logout }),
    [status, username, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  return useContext(AuthContext);
}
