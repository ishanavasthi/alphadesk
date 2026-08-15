// Typed client for the AlphaDesk FastAPI backend (SSE + approval).

// Default to 127.0.0.1 (not "localhost") so the browser doesn't try IPv6 ::1,
// where uvicorn isn't listening. Override with NEXT_PUBLIC_API_URL if needed.
export const API_BASE =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/$/, "") || "http://127.0.0.1:8000";

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
      const response = await fetch(`${API_BASE}/`, { cache: "no-store", signal });
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
  const response = await fetch(`${API_BASE}/analysis/${encodeURIComponent(runId)}`);
  if (response.status === 404) throw new Error("not_found");
  if (!response.ok) throw new Error(`Analysis fetch failed (${response.status}).`);
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
    response = await fetch(`${API_BASE}/analyze`, {
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
}

/** GET /auth/status — is the backend authenticated with IND Money? */
export async function getAuthStatus(): Promise<AuthStatus> {
  const response = await fetch(`${API_BASE}/auth/status`);
  if (!response.ok) throw new Error(`Auth status failed (${response.status}).`);
  return response.json();
}

/** POST /auth/login — begin OAuth; returns the URL to open in a browser. */
export async function startAuthLogin(): Promise<string> {
  const response = await fetch(`${API_BASE}/auth/login`, { method: "POST" });
  if (!response.ok) throw new Error(`Login start failed (${response.status}).`);
  const data = await response.json();
  return data.authorization_url as string;
}

/** POST /auth/logout — disconnect the backend from IND Money. */
export async function logoutAuth(): Promise<void> {
  const response = await fetch(`${API_BASE}/auth/logout`, { method: "POST" });
  if (!response.ok) throw new Error(`Logout failed (${response.status}).`);
}

export interface WatchlistItem {
  symbol: string;
  run_id?: string;
  query?: string | null;
  added_at?: string;
}

/** GET /watchlist — cumulative paper watchlist across runs. */
export async function getWatchlist(): Promise<WatchlistItem[]> {
  const response = await fetch(`${API_BASE}/watchlist`);
  if (!response.ok) throw new Error(`Watchlist failed (${response.status}).`);
  const data = await response.json();
  return (data.items as WatchlistItem[]) || [];
}

/** DELETE /watchlist/{symbol} — remove a stock from the paper watchlist. */
export async function removeFromWatchlist(symbol: string): Promise<void> {
  const response = await fetch(`${API_BASE}/watchlist/${encodeURIComponent(symbol)}`, {
    method: "DELETE",
  });
  if (!response.ok) throw new Error(`Remove failed (${response.status}).`);
}

// --------------------------------------------------------------------------- //
// Portfolio dashboard (card D1) — read-only, and gated
// --------------------------------------------------------------------------- //
/**
 * The interim C0 admin secret, sent on every `/portfolio/*` request.
 *
 * **Never set this in Vercel (or any hosted environment).** `NEXT_PUBLIC_*` values are
 * inlined into the JavaScript bundle every visitor downloads, so setting it in a
 * deployment publishes the operator's portfolio to the world. It belongs in
 * `frontend/.env.local` (gitignored) on the operator's own machine and nowhere
 * else. Production stays locked until F3 replaces this with per-user auth.
 */
export const ADMIN_SECRET = process.env.NEXT_PUBLIC_ALPHADESK_ADMIN_SECRET || "";

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
 * boundary), `locked` (no admin secret configured here).
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

async function portfolioFetch<T>(path: string, signal?: AbortSignal): Promise<T> {
  if (!ADMIN_SECRET) {
    throw new PortfolioError(
      0,
      "locked",
      "No admin secret is configured in this build.",
    );
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      headers: { "x-alphadesk-admin-secret": ADMIN_SECRET },
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

/** GET /portfolio/summary — totals, the snapshot's breakdowns, link health. */
export function getPortfolioSummary(signal?: AbortSignal): Promise<PortfolioSummary> {
  return portfolioFetch<PortfolioSummary>("/portfolio/summary", signal);
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
): Promise<HoldingsResponse> {
  return portfolioFetch<HoldingsResponse>(
    `/portfolio/holdings?asset_type=${encodeURIComponent(assetType)}`,
    signal,
  );
}

/** GET /portfolio/allocation — one (asset_type, by) slice, fetched on demand. */
export function getPortfolioAllocation(
  assetType: string,
  by: "assets" | "sector" | "market_cap",
  signal?: AbortSignal,
): Promise<AllocationResponse> {
  return portfolioFetch<AllocationResponse>(
    `/portfolio/allocation?asset_type=${encodeURIComponent(assetType)}&by=${by}`,
    signal,
  );
}

/** GET /portfolio/history — empty until S1 captures the first daily snapshot. */
export function getPortfolioHistory(days = 90, signal?: AbortSignal): Promise<HistoryResponse> {
  return portfolioFetch<HistoryResponse>(`/portfolio/history?days=${days}`, signal);
}

/** POST /approve — approve or reject the staged batch for a run. */
export async function approve(
  actionId: string,
  approved: boolean,
): Promise<ApproveResult> {
  const response = await fetch(`${API_BASE}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action_id: actionId, approved }),
  });
  if (!response.ok) {
    throw new Error(`Approve failed (${response.status}).`);
  }
  return response.json();
}
