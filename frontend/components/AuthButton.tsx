"use client";

import { AlertTriangle, KeyRound, Loader2, LogOut, ShieldCheck } from "lucide-react";
import { useAuth } from "@/components/AuthProvider";

export function AuthButton() {
  const { authed, busy, error, connect, disconnect } = useAuth();

  if (authed) {
    return (
      <span className="inline-flex items-center gap-1">
        <span className="pill pill-pass" title="Backend is authenticated with IND Money">
          <ShieldCheck className="h-3 w-3" />
          IND Money
        </span>
        <button
          onClick={disconnect}
          disabled={busy}
          aria-label="Disconnect IND Money"
          title="Disconnect IND Money"
          className="pill pill-flag transition hover:brightness-125 disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <LogOut className="h-3 w-3" />}
        </button>
      </span>
    );
  }

  // While the first status check is in flight (authed === null) we still render
  // the Connect button — disabled with a spinner — so it is always visible on
  // the home page even if the backend is slow/cold-starting.
  const checking = authed === null;

  return (
    <button
      onClick={connect}
      disabled={busy || checking}
      className={`pill transition hover:brightness-125 disabled:opacity-60 ${
        error ? "pill-reject" : "pill-flag"
      }`}
      title={error ?? "Authenticate the backend with IND Money"}
    >
      {busy || checking ? (
        <Loader2 className="h-3 w-3 animate-spin" />
      ) : error ? (
        <AlertTriangle className="h-3 w-3" />
      ) : (
        <KeyRound className="h-3 w-3" />
      )}
      {error ? "Connect failed - retry" : "Connect IND Money"}
    </button>
  );
}
