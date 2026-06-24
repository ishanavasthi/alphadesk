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

interface StreamHandlers {
  onStart?: (e: { run_id: string; status: string }) => void;
  onUpdate?: (e: AgentUpdate) => void;
  onComplete?: (e: CompleteEvent) => void;
  onError?: (message: string) => void;
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
    handlers.onError?.(`Request failed (${response.status}).`);
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
