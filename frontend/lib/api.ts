// Typed client for the AlphaDesk FastAPI backend (SSE + approval).

import { AUTH_ENABLED, withAuth } from "@/lib/auth";

// Default to 127.0.0.1 (not "localhost") so the browser doesn't try IPv6 ::1,
// where uvicorn isn't listening. Override with NEXT_PUBLIC_API_URL if needed.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

/**
 * `fetch`, plus the Clerk session token when there is one.
 *
 * **Every** call to the backend in this file goes through here, so "which
 * requests carry identity" has one answer rather than one per endpoint — the
 * failure mode of the alternative is a single forgotten call site that works
 * fine today and 401s the day F3 turns the gate on.
 *
 * With `NEXT_PUBLIC_AUTH_ENABLED` off (or nobody signed in) `withAuth` returns
 * the caller's headers unchanged and this is a plain `fetch` — same method,
 * same headers, same body as before card F2.
 *
 * Card F3 made the backend per-user, so the Clerk token is the only credential
 * that matters. The interim C0 admin-secret header is **gone** — card L1 removed
 * `withAuth`'s admin path and the backend no longer accepts one anywhere, so no
 * request from this client carries it, on `/portfolio/*` or elsewhere.
 */
async function apiFetch(url: string, init: RequestInit = {}): Promise<Response> {
  return fetch(url, { ...init, headers: await withAuth(init.headers) });
}

export type RiskDecision = "PASS" | "REJECT" | "FLAG";
export type AnalystAction = "buy" | "hold" | "avoid";

export interface AnalystRecommendation {
  symbol: string;
  action: AnalystAction;
  confidence: number;
  thesis?: string | null;
  bull_thesis: string;
  bear_thesis: string;
  key_risks: string[];
  catalysts: string[];
  target_price?: number | null;
  time_horizon?: string | null;
  citations: string[];
}

export interface RiskAssessment {
  symbol: string;
  sector?: string | null;
  approved: boolean;
  decision: RiskDecision;
  confidence: number;
  violations: string[];
  notes?: string | null;
}

export interface AgentUpdate {
  node: string;
  rejection_reason?: string | null;
  [key: string]: unknown;
}

export interface CompleteEvent {
  run_id: string;
  status: string;
  awaiting_approval: boolean;
  action_id: string | null;
  analyst_recommendations: AnalystRecommendation[];
  risk_assessments: RiskAssessment[];
  rejection_reason?: string | null;
}

export interface ApproveResult {
  run_id: string;
  status: string;
  state: {
    paper_watchlist?: string[];
    approved_actions?: unknown[];
    pending_actions?: unknown[];
    [key: string]: unknown;
  };
}

export interface AnalysisPayload {
  run_id: string;
  query: string;
  status: string;
  awaiting_approval: boolean;
  action_id: string | null;
  analyst_recommendations: AnalystRecommendation[];
  risk_assessments: RiskAssessment[];
  rejection_reason?: string | null;
  paper_watchlist?: string[];
  created_at?: string;
}

/**
 * GET / — cheap liveness ping. Resolves true once the backend answers.
 *
 * The backend runs on a free Hugging Face Space that sleeps when idle, and the
 * first request after a sleep only *starts* the container (~1 min of cold
 * start) while everything in flight fails. Poll the root route until it answers
 * so the rest of the app can wait instead of rendering a false "disconnected".
 */
export async function wakeBackend(
  { attempts = 24, intervalMs = 5000, signal }: WakeOptions = {},
): Promise<boolean> {
  for (let i = 0; i < attempts; i += 1) {
    if (signal?.aborted) return false;
    try {
      const response = await apiFetch(`${API_BASE}/`, { cache: "no-store", signal });
      if (response.ok) return true;
    } catch {
      // Network error while the Space boots — fall through and retry.
    }
    if (i < attempts - 1) {
      await new Promise((resolve) => setTimeout(resolve, intervalMs));
    }
  }
  return false;
}

export interface WakeOptions {
  attempts?: number;
  intervalMs?: number;
  signal?: AbortSignal;
}

/** GET /analysis/{id} — full stored analysis for the /a/<id> view. */
export async function getAnalysis(runId: string): Promise<AnalysisPayload> {
  const response = await apiFetch(`${API_BASE}/analysis/${encodeURIComponent(runId)}`);
  if (response.status === 404) throw new Error("not_found");
  if (!response.ok) throw new Error(`Analysis fetch failed (${response.status}).`);
  return response.json();
}

export interface RunStatusPayload {
  run_id: string;
  status: string;
  query?: string | null;
  action_id: string | null;
  awaiting_approval: boolean;
  next: string[];
  state: Record<string, unknown>;
}

/**
 * GET /status/{id} — the live status of a run, including one still in flight.
 *
 * `/analysis/{id}` only exists once the run has finished (the backend writes the
 * record on the `complete` event), so a run being re-attached mid-flight is a
 * 404 there and a `"running"` here. Same ownership rule as everything else in
 * the Lab: someone else's run is a 404, never a 403.
 */
export async function getRunStatus(runId: string): Promise<RunStatusPayload> {
  const response = await apiFetch(`${API_BASE}/status/${encodeURIComponent(runId)}`, {
    cache: "no-store",
  });
  if (response.status === 404) throw new Error("not_found");
  if (!response.ok) throw new Error(`Status fetch failed (${response.status}).`);
  return response.json();
}

interface StreamHandlers {
  onStart?: (e: { run_id: string; status: string }) => void;
  onUpdate?: (e: AgentUpdate) => void;
  onComplete?: (e: CompleteEvent) => void;
  /** status is the HTTP code when the request itself was rejected (e.g. 409 = not connected). */
  onError?: (message: string, status?: number) => void;
}

/**
 * POST /analyze and dispatch the Server-Sent Events as they stream in.
 * EventSource only supports GET, so we read the POST response body manually.
 */
export async function streamAnalyze(
  query: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
): Promise<void> {
  let response: Response;
  try {
    response = await apiFetch(`${API_BASE}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
      signal,
    });
  } catch (err) {
    // A cancelled request (component unmount / re-query) is not a failure.
    if ((err as Error).name === "AbortError") return;
    handlers.onError?.(`Cannot reach AlphaDesk API at ${API_BASE}. Is the backend running?`);
    return;
  }

  if (!response.ok || !response.body) {
    // FastAPI puts the reason in `detail` — pass it through instead of a bare code.
    let detail = "";
    try {
      detail = ((await response.json()) as { detail?: string }).detail ?? "";
    } catch {
      // non-JSON body (proxy error page); fall back to the status code
    }
    handlers.onError?.(detail || `Request failed (${response.status}).`, response.status);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (event: string, data: string) => {
    let payload: unknown = {};
    try {
      payload = JSON.parse(data);
    } catch {
      return;
    }
    switch (event) {
      case "start":
        handlers.onStart?.(payload as { run_id: string; status: string });
        break;
      case "update":
        handlers.onUpdate?.(payload as AgentUpdate);
        break;
      case "complete":
        handlers.onComplete?.(payload as CompleteEvent);
        break;
      case "error":
        handlers.onError?.((payload as { error?: string }).error || "Run failed.");
        break;
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);

        let event = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length) dispatch(event, dataLines.join("\n"));
      }
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      handlers.onError?.((err as Error).message);
    }
  }
}

export interface AuthStatus {
  authenticated: boolean;
  source?: string | null;
  expires_at?: number | null;
  expires_in_sec?: number | null;
  /** The source definitively rejected the stored credential — re-link required. */
  revoked?: boolean;
  /** A stored link the server can no longer decrypt (the encryption key moved). */
  undecryptable?: boolean;
  /** Whose status this is, or null when the caller could not be identified. */
  user_id?: string | null;
}

/**
 * GET /auth/status — is **this caller** linked to IND Money?
 *
 * Per-user since F3, JWT-only since L1: the `withAuth` bearer is the credential.
 * The interim admin-secret header was removed with the rest of the F3 §5 path;
 * a caller with no session is answered for nobody, which is the point — this
 * endpoint used to tell the whole internet whether the operator was connected.
 */
export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await apiFetch(`${API_BASE}/auth/status`);
  if (!response.ok) throw new Error(`Auth status failed (${response.status}).`);
  return response.json();
}

/**
 * POST /auth/login — begin OAuth for the signed-in user; returns the URL to open.
 *
 * **JWT-only since F3.** The admin secret is deliberately not sent: a link made
 * under a shared operator secret would have no owner, which is exactly the
 * process-wide credential this card deleted. Signed out, this 401s — and in
 * single-tenant dev (`ALPHADESK_SINGLE_TENANT=1`) the backend links as `local`
 * with no token at all, so the operator's own machine is unaffected.
 */
export async function startAuthLogin(): Promise<string> {
  const response = await apiFetch(`${API_BASE}/auth/login`, {
    method: "POST",
  });
  if (!response.ok) throw new Error(`Login start failed (${response.status}).`);
  const data = await response.json();
  return data.authorization_url as string;
}

/** POST /auth/logout — disconnect the backend from IND Money. */
export async function logoutAuth(): Promise<void> {
  const response = await apiFetch(`${API_BASE}/auth/logout`, { method: "POST" });
  if (!response.ok) throw new Error(`Logout failed (${response.status}).`);
}

/** The confirmation `POST /auth/unlink` returns. */
export interface UnlinkResult {
  /** `unlinked` if a link was removed; `not_linked` if there was none to remove. */
  status: "unlinked" | "not_linked";
  /** True only if the grant was also killed at IND Money's end. */
  upstream_revoked: boolean;
}

/**
 * POST /auth/unlink — disconnect **this caller's** IND Money link (issue #13).
 *
 * Revokes the grant upstream first, then deletes the stored link. JWT-only, like
 * the rest of `/auth/*`; idempotent, so a second press answers `not_linked`
 * rather than failing.
 */
export async function unlinkIndMoney(): Promise<UnlinkResult> {
  const response = await apiFetch(`${API_BASE}/auth/unlink`, { method: "POST" });
  if (!response.ok) throw new Error(`Unlink failed (${response.status}).`);
  return response.json();
}

/** The confirmation `DELETE /account` returns. */
export interface DeleteAccountResult {
  deleted: boolean;
  user_id: string;
  /** True if the broker grant was also killed upstream; false/null otherwise. */
  revoked_upstream: boolean | null;
  revocation_error?: string | null;
}

/**
 * DELETE /account — the DPDP "delete my data" action (card L1).
 *
 * Revokes the broker token upstream, then cascade-deletes the signed-in user
 * and every row they own. JWT-only (the `withAuth` bearer); a user can only
 * delete their **own** data. Irreversible — the caller confirms first.
 */
export async function deleteAccount(): Promise<DeleteAccountResult> {
  const response = await apiFetch(`${API_BASE}/account`, { method: "DELETE" });
  if (!response.ok) throw new Error(`Delete failed (${response.status}).`);
  return response.json();
}

export interface WatchlistItem {
  symbol: string;
  /** The decision, frozen at approval (card F4 — the watchlist persists these). */
  company?: string | null;
  thesis?: string | null;
  confidence?: number | null;
  action?: AnalystAction | null;
  risk_verdict?: RiskDecision | null;
  query?: string | null;
  /** Opaque reference to the originating Lab run; may no longer resolve. */
  run_id?: string | null;
  /** True while the originating run is still openable at /lab/a/<run_id>. */
  run_available?: boolean;
  added_at?: string;
}

/** GET /watchlist — cumulative paper watchlist across runs. */
export async function getWatchlist(): Promise<WatchlistItem[]> {
  const response = await apiFetch(`${API_BASE}/watchlist`);
  if (!response.ok) throw new Error(`Watchlist failed (${response.status}).`);
  const data = await response.json();
  return (data.items as WatchlistItem[]) || [];
}

/** DELETE /watchlist/{symbol} — remove a stock from the paper watchlist. */
export async function removeFromWatchlist(symbol: string): Promise<void> {
  const response = await apiFetch(`${API_BASE}/watchlist/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`Remove failed (${response.status}).`);
}

// --------------------------------------------------------------------------- //
// Portfolio dashboard (card D1) — read-only, per-user
// --------------------------------------------------------------------------- //
// The interim C0 admin secret was removed at card L1 along with its backend
// half (the F3 §5 checklist). With `NEXT_PUBLIC_AUTH_ENABLED` on, the Clerk
// session token (`withAuth`) is the only credential `/portfolio/*` ever needs.

/** Money arrives as a decimal string — see `backend/api/routes/portfolio.py`. */
export type Money = string | null;

export interface AllocationSlice {
  label: string;
  asset_type: string | null;
  asset_type_raw: string | null;
  invested_amount: Money;
  current_value: string;
  pnl: Money;
  pnl_pct: Money;
  weight_pct: Money;
  us_exposure: boolean;
  currency: string;
}

export interface PortfolioSummary {
  user_id: string;
  source: string;
  as_of: string;
  currency: string;
  net_worth: string;
  current_value: Money;
  invested_total: Money;
  liabilities_total: Money;
  pnl: Money;
  pnl_pct: Money;
  by_asset_type: AllocationSlice[];
  by_asset_class: AllocationSlice[];
  by_sector: AllocationSlice[];
  by_market_cap: AllocationSlice[];
  link_health: "linked" | "expiring" | "needs_relink" | "revoked";
  last_captured_at: string | null;
}

export interface PortfolioHolding {
  source: string;
  external_id: string;
  asset_type: string;
  asset_type_raw: string | null;
  symbol: string | null;
  name: string | null;
  isin: string | null;
  units: Money;
  avg_cost: Money;
  invested_amount: Money;
  current_price: Money;
  current_value: string;
  pnl: Money;
  pnl_pct: Money;
  us_exposure: boolean;
  currency: string;
  as_of: string;
}

export interface HoldingsResponse {
  asset_type: string;
  currency: string;
  holdings: PortfolioHolding[];
}

export interface AllocationResponse {
  source: string;
  asset_type: string;
  by: "assets" | "sector" | "market_cap";
  as_of: string;
  currency: string;
  slices: AllocationSlice[];
}

/** One point of captured history. Empty until card S1 starts capturing. */
export interface HistoryPoint {
  date: string;
  net_worth: string;
}

export interface HistoryResponse {
  points: HistoryPoint[];
  last_captured_at: string | null;
  days: number;
  currency: string;
  note?: string;
}

/**
 * A `/portfolio/*` failure the UI can branch on.
 *
 * The backend never returns a bare 500 for a source failure, so `code` is
 * always one the dashboard has a state for: `not_linked` (Connect gate),
 * `rate_limited` (quiet retry notice), `unverified_shape` (the IND_STOCK
 * boundary), `locked` (sign-in not compiled into this build).
 */
export class PortfolioError extends Error {
  readonly status: number;
  readonly code: string;
  readonly retryAfter: number | null;

  constructor(status: number, code: string, message: string, retryAfter: number | null = null) {
    super(message);
    this.name = "PortfolioError";
    this.status = status;
    this.code = code;
    this.retryAfter = retryAfter;
  }
}

async function portfolioFetch<T>(
  path: string,
  signal?: AbortSignal,
  { method = "GET" }: { method?: "GET" | "POST" } = {},
): Promise<T> {
  // Flag off there is no way to produce a credential, so the build is locked.
  // Flag on, a signed-out visitor is an ordinary state and the backend's 401 is
  // the honest answer — refusing to make the request would render "locked" at
  // somebody who just needs to sign in.
  if (!AUTH_ENABLED) {
    throw new PortfolioError(
      0,
      "locked",
      "Sign-in is not switched on in this build.",
    );
  }

  let response: Response;
  try {
    response = await apiFetch(`${API_BASE}${path}`, {
      method,
      cache: "no-store",
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new PortfolioError(0, "unreachable", `Cannot reach AlphaDesk API at ${API_BASE}.`);
  }

  if (response.ok) return response.json() as Promise<T>;

  // FastAPI puts our structured body in `detail`; a proxy error page will not.
  type Detail = { code?: string; message?: string; retry_after?: number };
  let detail: Detail | string = "";
  try {
    detail = ((await response.json()) as { detail?: Detail | string }).detail ?? "";
  } catch {
    detail = "";
  }
  if (typeof detail === "string") {
    throw new PortfolioError(
      response.status,
      response.status === 401 ? "unauthorized" : "http_error",
      detail || `Request failed (${response.status}).`,
    );
  }
  throw new PortfolioError(
    response.status,
    detail.code || "http_error",
    detail.message || `Request failed (${response.status}).`,
    typeof detail.retry_after === "number" ? detail.retry_after : null,
  );
}

/**
 * `?fresh=1` — the backend's true cache bypass (issue #15).
 *
 * Only Refresh sends it. An ordinary page load may answer from the read-through
 * cache; a reader who pressed the button asked for the source itself.
 */
const freshParam = (fresh: boolean | undefined, separator: "?" | "&"): string =>
  fresh ? `${separator}fresh=1` : "";

/** GET /portfolio/summary — totals, the snapshot's breakdowns, link health. */
export function getPortfolioSummary(
  signal?: AbortSignal,
  fresh?: boolean,
): Promise<PortfolioSummary> {
  return portfolioFetch<PortfolioSummary>(
    `/portfolio/summary${freshParam(fresh, "?")}`,
    signal,
  );
}

/**
 * GET /portfolio/holdings — rows for **one** asset type.
 *
 * Singular on purpose: the source is queried per asset type and rate-limits per
 * tool, so callers ask for the buckets the summary actually reported instead of
 * walking the enum.
 */
export function getPortfolioHoldings(
  assetType: string,
  signal?: AbortSignal,
  fresh?: boolean,
): Promise<HoldingsResponse> {
  return portfolioFetch<HoldingsResponse>(
    `/portfolio/holdings?asset_type=${encodeURIComponent(assetType)}${freshParam(fresh, "&")}`,
    signal,
  );
}

/** GET /portfolio/allocation — one (asset_type, by) slice, fetched on demand. */
export function getPortfolioAllocation(
  assetType: string,
  by: "assets" | "sector" | "market_cap",
  signal?: AbortSignal,
  fresh?: boolean,
): Promise<AllocationResponse> {
  return portfolioFetch<AllocationResponse>(
    `/portfolio/allocation?asset_type=${encodeURIComponent(assetType)}&by=${by}` +
      freshParam(fresh, "&"),
    signal,
  );
}

/** GET /portfolio/history — one point per captured day, oldest first. */
export function getPortfolioHistory(days = 90, signal?: AbortSignal): Promise<HistoryResponse> {
  return portfolioFetch<HistoryResponse>(`/portfolio/history?days=${days}`, signal);
}

// --------------------------------------------------------------------------- #
// Top movers (card B8)
// --------------------------------------------------------------------------- #

/**
 * Why a row is in the list it is in — the honest-data core of the movers card.
 *
 * `price` rows carry units and a price at both ends, so their percentage is a
 * real market move and only they are ranked. `balance` rows (savings, FDs) have
 * no price: their delta is money moved, not a move. `opened`/`closed` existed at
 * only one endpoint and have no comparison at all — never a ±100%.
 */
export type MoverBasis = "price" | "balance" | "opened" | "closed";

export interface MoverRow {
  source: string;
  external_id: string;
  asset_type: string;
  name: string | null;
  symbol: string | null;
  basis: MoverBasis;
  start_price: Money;
  end_price: Money;
  start_value: Money;
  end_value: Money;
  change_abs: Money;
  change_pct: Money;
  currency: string;
}

/** A window's two ends. Either side is `null` when no day could be found. */
export interface MoversWindow {
  from: string | null;
  to: string | null;
}

/** A bucket that failed on one of the compared days, so its rows are unknown. */
export interface MoversExclusion {
  asset_type: string;
  reason: string;
}

export interface MoversResponse {
  requested: MoversWindow;
  compared: MoversWindow;
  note: string | null;
  gainers: MoverRow[];
  losers: MoverRow[];
  flows: MoverRow[];
  opened: MoverRow[];
  closed: MoverRow[];
  excluded: MoversExclusion[];
}

/**
 * GET /portfolio/movers — ranked gainers/losers between two captured days.
 *
 * Dates only: the presets (1D/1W/1M/3M/YTD) are a frontend concern, and the API
 * snaps whatever window it is given to the days it actually captured. Omitting
 * `to` means the latest captured day; omitting `from` means seven attributed
 * days before it.
 */
export function getMovers(
  from?: string,
  to?: string,
  limit?: number,
  signal?: AbortSignal,
): Promise<MoversResponse> {
  const params = new URLSearchParams();
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  if (limit !== undefined) params.set("limit", String(limit));
  const query = params.toString();
  return portfolioFetch<MoversResponse>(`/portfolio/movers${query ? `?${query}` : ""}`, signal);
}

/** The outcome of a capture attempt. `in_flight` means one was already running. */
export interface CaptureResult {
  status: "captured" | "already_captured" | "skipped" | "failed" | "in_flight";
  captured_on: string | null;
  holdings?: number;
  reason?: string | null;
}

/**
 * POST /portfolio/capture — take today's snapshot now.
 *
 * Behind the same gate as the reads, because it acts on the same account.
 * Idempotent: a day that already has a row answers `already_captured` rather
 * than taking a second reading, so this button cannot overwrite the nightly
 * capture — which ran at the time it was timed for — with a later, worse one.
 */
export function capturePortfolioSnapshot(signal?: AbortSignal): Promise<CaptureResult> {
  return portfolioFetch<CaptureResult>("/portfolio/capture", signal, { method: "POST" });
}

// --------------------------------------------------------------------------- #
// AI overview (card A1)
// --------------------------------------------------------------------------- #

/** One computed metric — the number is always Python-computed, never the model's. */
export interface OverviewMetric {
  key: string;
  label: string;
  unit: "inr" | "pct" | "ratio" | "count" | "text";
  available: boolean;
  /** The canonical rendering the narrative chips also use, e.g. "₹10,07,655". */
  display: string;
  value: string | null;
  text: string | null;
  detail: string | null;
  signed: boolean;
}

/** A narrative segment: literal prose, or a chip referencing a computed metric. */
export type OverviewSegment =
  | { text: string }
  | { metric: string; display: string; label: string; detail: string | null; available: boolean };

export interface OverviewParagraph {
  segments: OverviewSegment[];
}

export interface OverviewComplete {
  status: "complete" | "degraded";
  degraded: boolean;
  /** Why the narrative is absent: "llm_unavailable" | "spend_cap" | "error" | null. */
  reason: string | null;
  narrative: OverviewParagraph[];
  scripted: boolean;
  metrics: OverviewMetric[];
  agents: { node: string; status: string }[];
  /** True when the backend replayed today's already-written narrative. */
  saved?: boolean;
}

export interface OverviewHandlers {
  onStart?: (data: { status: string; agents: string[] }) => void;
  onUpdate?: (data: { node: string; status: string }) => void;
  onComplete?: (data: OverviewComplete) => void;
  onError?: (message: string, status?: number) => void;
}

/**
 * POST /portfolio/overview — stream the AI narrative over Python-computed metrics.
 *
 * Same gate as the rest of `/portfolio/*` (Clerk JWT). The stream always ends
 * in a `complete` event carrying every
 * metric; when the model is unavailable that event is flagged `degraded` and the
 * narrative is empty — the panel then renders "AI overview unavailable" while
 * every number still shows. A source failure (unlinked, throttled) is a normal
 * HTTP error **before** the stream opens, surfaced through `onError`.
 *
 * The narrative is written once per IST day: without `force` the backend replays
 * whatever it already wrote today (same events, no `update`s, no spend). Pass
 * `force` — the Regenerate button, and only that — to re-run the agents and
 * overwrite the day's saved copy.
 */
export async function streamOverview(
  handlers: OverviewHandlers,
  signal?: AbortSignal,
  options?: { force?: boolean },
): Promise<void> {
  if (!AUTH_ENABLED) {
    handlers.onError?.("Sign-in is not switched on in this build.", 0);
    return;
  }

  const url = `${API_BASE}/portfolio/overview${options?.force ? "?force=1" : ""}`;
  let response: Response;
  try {
    response = await apiFetch(url, {
      method: "POST",
      cache: "no-store",
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    handlers.onError?.(`Cannot reach AlphaDesk API at ${API_BASE}.`);
    return;
  }

  if (!response.ok || !response.body) {
    type Detail = { code?: string; message?: string };
    let message = `Request failed (${response.status}).`;
    try {
      const detail = ((await response.json()) as { detail?: Detail | string }).detail;
      if (typeof detail === "string") message = detail || message;
      else if (detail?.message) message = detail.message;
    } catch {
      /* non-JSON error page */
    }
    handlers.onError?.(message, response.status);
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  const dispatch = (event: string, data: string) => {
    let payload: unknown = {};
    try {
      payload = JSON.parse(data);
    } catch {
      return;
    }
    switch (event) {
      case "start":
        handlers.onStart?.(payload as { status: string; agents: string[] });
        break;
      case "update":
        handlers.onUpdate?.(payload as { node: string; status: string });
        break;
      case "complete":
        handlers.onComplete?.(payload as OverviewComplete);
        break;
      case "error":
        handlers.onError?.((payload as { error?: string }).error || "Overview failed.");
        break;
    }
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const block = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = "message";
        const dataLines: string[] = [];
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
        }
        if (dataLines.length) dispatch(event, dataLines.join("\n"));
      }
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") handlers.onError?.((err as Error).message);
  }
}

/** POST /approve — approve or reject the staged batch for a run. */
export async function approve(
  actionId: string,
  approved: boolean,
): Promise<ApproveResult> {
  const response = await apiFetch(`${API_BASE}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action_id: actionId, approved }),
  });
  if (!response.ok) {
    throw new Error(`Approve failed (${response.status}).`);
  }
  return response.json();
}
