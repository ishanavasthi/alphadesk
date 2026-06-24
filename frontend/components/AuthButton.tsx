"use client";

import { useEffect, useRef, useState } from "react";
import { KeyRound, Loader2, ShieldCheck } from "lucide-react";
import { getAuthStatus, startAuthLogin } from "@/lib/api";

export function AuthButton() {
  const [authed, setAuthed] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  async function refresh(): Promise<boolean> {
    try {
      const s = await getAuthStatus();
      setAuthed(s.authenticated);
      return s.authenticated;
    } catch {
      setAuthed(false);
      return false;
    }
  }

  function stopPolling() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }

  useEffect(() => {
    refresh();
    return stopPolling;
  }, []);

  async function connect() {
    if (busy) return;
    setBusy(true);
    try {
      const url = await startAuthLogin();
      window.open(url, "_blank", "width=520,height=720");
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
    } catch {
      setBusy(false);
    }
  }

  if (authed === null) return null; // unknown until first check

  if (authed) {
    return (
      <span className="pill pill-pass" title="Backend is authenticated with IND Money">
        <ShieldCheck className="h-3 w-3" />
        IND Money
      </span>
    );
  }

  return (
    <button
      onClick={connect}
      disabled={busy}
      className="pill pill-flag transition hover:brightness-125 disabled:opacity-60"
      title="Authenticate the backend with IND Money"
    >
      {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <KeyRound className="h-3 w-3" />}
      Connect IND Money
    </button>
  );
}
