"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { getAuthStatus, logoutAuth, startAuthLogin, wakeBackend } from "@/lib/api";

/** Turn a fetch/HTTP failure into something a user can act on. */
function describe(err: unknown): string {
  const msg = err instanceof Error ? err.message : String(err);
  // fetch() rejects with a bare TypeError for DNS/CORS/offline backends.
  if (/failed to fetch|networkerror|load failed/i.test(msg)) {
    return "Backend unreachable - is the API up and CORS configured?";
  }
  if (/\(50\d\)/.test(msg)) return `${msg} Backend is down or still starting.`;
  return msg;
}

interface AuthContextValue {
  /** null while the first status check is in flight. */
  authed: boolean | null;
  /** True while we are pinging a cold/sleeping backend back into service. */
  waking: boolean;
  busy: boolean;
  error: string | null;
  connect: () => Promise<void>;
  disconnect: () => Promise<void>;
  refresh: () => Promise<boolean>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

/**
 * Single source of truth for the IND Money connection, shared by the top-bar
 * button and the query form (which must not accept a query while logged out —
 * the whole pipeline is fed by the MCP).
 */
export function AuthProvider({ children }: { children: ReactNode }) {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [waking, setWaking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async (): Promise<boolean> => {
    try {
      const s = await getAuthStatus();
      setAuthed(s.authenticated);
      return s.authenticated;
    } catch {
      setAuthed(false);
      return false;
    }
  }, []);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  // Warm-up ping. The backend sleeps when idle (free Hugging Face Space), and
  // the first request after a sleep only kicks off a ~1 min cold start. Rather
  // than showing a false "disconnected", keep pinging until it answers.
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const s = await getAuthStatus();
        setAuthed(s.authenticated);
      } catch {
        setWaking(true);
        const up = await wakeBackend({ signal: controller.signal });
        if (controller.signal.aborted) return;
        setWaking(false);
        if (up) await refresh();
        else setAuthed(false);
      }
    })();
    return () => {
      controller.abort();
      stopPolling();
    };
  }, [refresh, stopPolling]);

  const connect = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    // Open the popup synchronously, inside the click's user activation — opening
    // it after the awaited fetch below gets blocked by popup blockers.
    const popup = window.open("", "_blank", "width=520,height=720");
    try {
      const url = await startAuthLogin();
      if (popup && !popup.closed) {
        popup.location.href = url;
      } else {
        // Popup blocked: fall back to navigating this tab to the login page.
        window.location.href = url;
        return;
      }
      // Poll until the backend reports authenticated (callback completed).
      stopPolling();
      pollRef.current = setInterval(async () => {
        if (await refresh()) {
          stopPolling();
          setBusy(false);
        }
      }, 2000);
      // Give up the spinner after 3 minutes regardless.
      setTimeout(() => {
        stopPolling();
        setBusy(false);
      }, 180_000);
    } catch (err) {
      popup?.close();
      setError(describe(err));
      setBusy(false);
    }
  }, [busy, refresh, stopPolling]);

  const disconnect = useCallback(async () => {
    if (busy) return;
    setBusy(true);
    try {
      await logoutAuth();
      setAuthed(false);
      setError(null);
    } catch (err) {
      setError(describe(err));
    } finally {
      setBusy(false);
    }
  }, [busy]);

  return (
    <AuthContext.Provider value={{ authed, waking, busy, error, connect, disconnect, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * The IND Money link state — **not** "is the visitor signed in to AlphaDesk".
 *
 * Renamed from `useAuth` by card F2 for two reasons. It collided outright with
 * Clerk's `useAuth`, and an `import { useAuth }` whose meaning depended on which
 * file it came from is exactly the kind of ambiguity that ends with a page
 * gating on the wrong thing. And the old name was never accurate: this hook
 * answers "has a broker been linked", which after F3 will be a per-user fact
 * distinct from identity.
 */
export function useIndMoney(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useIndMoney must be used inside <AuthProvider>");
  return ctx;
}
