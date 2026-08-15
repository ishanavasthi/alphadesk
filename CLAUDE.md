# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **V2 build in progress.** `V2_PLAN.md` is the plan of record (task cards,
> execution protocol, locked decisions) and `docs/STATUS.md` is the live card
> ledger — read both before picking up any v2 work. Per-card specs and test
> docs live in `docs/SPECS/` and `docs/TESTING/`.

AlphaDesk is a multi-agent Indian-equity research desk: a LangGraph pipeline (FastAPI backend) that scans NSE movers, researches candidates, writes analyst reports, enforces risk guardrails, and pauses for human approval before adding stocks to a paper watchlist. Market data comes from the read-only IND Money MCP server; reasoning runs on Groq (or any OpenAI-compatible endpoint). The frontend is a Bloomberg-terminal-style Next.js app. **No real orders are ever placed** — the broker layer is a stub.

## Commands

**Backend** — imports resolve with `backend/` as the root (modules are `api.main`, `graph.*`, `agents.*`, `tools.*`, `rag.*` — there is **no `backend.` prefix**). Always run from inside `backend/`, or pass `--app-dir backend`.

```bash
source .venv/bin/activate                       # repo-root venv
pip install -r requirements.txt
cd backend
cp .env.example .env                             # then fill values
python -m rag.ingest                             # (re)build ChromaDB from data/nse_docs
uvicorn api.main:app --reload --port 8000        # API + interactive docs at /docs
```

**Frontend**

```bash
cd frontend
npm install
npm run dev        # localhost:3000
npm run build
npm run lint
```

There is no automated test runner wired up; `backend/evals/test_cases.py` is a stub.

## Architecture

**The pipeline is one linear LangGraph** over a single `PortfolioState` Pydantic model (`backend/graph/state.py`). Each agent is a pure `async (state) -> state` function that reads shared state and appends its output:

```
scanner → research → analyst → risk_manager ─┬─(any PASS/FLAG)→ execution → END
                                             └─(all REJECT)────────────────→ END
```

- Graph assembly, routing, and the human gate live in `backend/graph/graph.py`. Agents are in `backend/agents/`.
- **Human-in-the-loop:** compiled with `interrupt_before=["execution"]` + a `MemorySaver` checkpointer (the checkpointer is *required* for the interrupt to pause/resume). The graph runs to a pause **before** execution, returns recommendations + risk assessments, and only resumes once `human_approved=True` is set on the thread (`resume_after_approval`). Nothing reaches the watchlist without approval.
- **Run identity:** each run's UUID is used as three things at once — the LangGraph `thread_id`, the LangSmith trace root `run_id`, and the app-level run handle reachable at `/a/<run_id>`.

**LLM provider selection** is centralized in `backend/agents/llm.py` via `get_chat_llm(default_model)`. Default is Groq (`ChatGroq`). Setting either `OPENAI_BASE_URL` or `OPENAI_COMPATIBLE_MODEL` switches all agents to `ChatOpenAI` against an OpenAI-compatible endpoint. Never construct chat models directly in an agent — go through this helper.

**IND Money MCP** (`backend/tools/ind_money.py`, `ind_money_auth.py`): market data over streamable HTTP, wrapped as LangGraph tools. Two integration facts drive most of the code: (1) instruments are keyed by `ind_key` (e.g. `INDS00577`), **not** ticker — resolve tickers with `lookup_ind_keys`; (2) responses are wrapped as `{"result": "<stringified JSON>"}` and must be unwrapped. Auth is OAuth 2.0 with hourly-expiring access tokens auto-refreshed from a stored refresh token, cached to `backend/.ind_money_token.json` (gitignored). The in-app Connect button drives the full auth-code + PKCE + dynamic-client-registration flow; the OAuth callback is served by the **backend**, so `IND_MONEY_AUTH_REDIRECT` must be the public backend URL.

**RAG** (`backend/rag/`): ChromaDB with the built-in ONNX MiniLM embedding function (no torch, no paid embedding API). `ingest.py` chunks NSE PDFs from `data/nse_docs/` into the `nse_filings` collection at `data/chroma_db/`; the Analyst agent queries it via `retriever.py`. Scanned/image-only PDFs are skipped (no OCR).

**State persistence is in-memory** (`_RUNS`, `_ANALYSES`, `_PAPER_WATCHLIST`, `_ACTIONS` dicts in `backend/api/main.py`). Runs, stored analyses, and the paper watchlist survive a browser refresh but **not a backend restart**. This is a known limitation — swap for a DB to make durable.

**API ↔ frontend** (`backend/api/main.py` ↔ `frontend/lib/api.ts`): `POST /analyze` refuses with **409** unless IND Money is connected (an unauthenticated run can only yield an empty "0 candidates" pipeline), then streams Server-Sent Events (`start`, one `update` per agent node, then `complete` with recommendations/risk/`action_id`, or `error`). `POST /approve` resumes the paused graph. CORS: localhost/127.0.0.1 (any port) is always allowed; production origins come from `CORS_ALLOW_ORIGINS` (comma-separated) and optional `CORS_ALLOW_ORIGIN_REGEX`.

## Guardrails (enforced in `backend/agents/risk_manager.py`)

- Min confidence 0.70 to proceed (below → REJECT). Confidence in [0.70, 0.75) → FLAG (a caution label, still approvable), else PASS.
- Max 3 stocks per known sector (unknown-sector stocks exempt). Analyst action `avoid` → REJECT.
- Any `pending_actions` → `approved_actions` transition requires `human_approved=True`.

## Deployment

Frontend → Vercel (Root Directory = `frontend`, set `NEXT_PUBLIC_API_URL`). Backend → Hugging Face Spaces (Docker, port 7860; the repo-root `Dockerfile` runs `uvicorn api.main:app --app-dir backend` and bakes the ChromaDB index at build). See `DEPLOY.md` for the full env-var wiring — the three cross-references that must agree are `IND_MONEY_AUTH_REDIRECT` = `<backend>/auth/callback`, `CORS_ALLOW_ORIGINS` containing the live frontend origin, and `NEXT_PUBLIC_API_URL` = the backend URL.

## Conventions

- The `alphaDesk_graph` / `alphaDesk_*` naming (mixed case) is intentional and used across the codebase — match it.
- Broker integration is out of scope by design: implement `BrokerAdapter` in `backend/broker/` and set `BROKER=<name>`; the Execution agent already calls `broker.place_order` when one is configured. Leave `BROKER` blank for paper-only.
