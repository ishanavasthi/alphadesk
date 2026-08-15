# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> **V2 build in progress.** `V2_PLAN.md` is the plan of record (task cards,
> execution protocol, locked decisions) and `docs/STATUS.md` is the live card
> ledger — read both before picking up any v2 work. Per-card specs and test
> docs live in `docs/SPECS/` and `docs/TESTING/`.

AlphaDesk is a multi-agent Indian-equity research desk: a LangGraph pipeline (FastAPI backend) that scans NSE movers, researches candidates, writes analyst reports, enforces risk guardrails, and pauses for human approval before adding stocks to a paper watchlist. Market data comes from the read-only IND Money MCP server; reasoning runs on Groq (or any OpenAI-compatible endpoint). The frontend is a Bloomberg-terminal-style Next.js app. **No real orders are ever placed** — the broker layer is a stub.

## Commands

**Backend** — imports resolve with `backend/` as the root (modules are `api.main`, `graph.*`, `agents.*`, `tools.*`, `db.*`, `rag.*` — there is **no `backend.` prefix**). Always run from inside `backend/`, or pass `--app-dir backend`.

```bash
source .venv/bin/activate                       # repo-root venv
pip install -r requirements.txt                  # every dep pinned; bumps are deliberate commits
pip install -r requirements-dev.txt              # test-only deps; NOT in the Docker image
cd backend
cp .env.example .env                             # then fill values
alembic upgrade head                             # needs DATABASE_URL (Postgres)
uvicorn api.main:app --reload --port 8000        # API + interactive docs at /docs
pytest                                           # 461 tests; DB ones need Postgres
```

**Frontend**

```bash
cd frontend
npm install
npm run dev        # localhost:3000
npm run build
npm test           # vitest (added by S1); `npm run lint` is still unconfigured
```

**Tests:** `pytest` from inside `backend/` (config in `backend/pytest.ini`, suite in `backend/tests/`). The DB tests need a Postgres — one-line Docker container and the full walkthrough are in `docs/TESTING/F1.md`; without one they skip loudly rather than failing. The suite creates and **drops** a `<db>_test` database, so it refuses to inherit a non-loopback `DATABASE_URL`; name a remote target in `TEST_DATABASE_URL` deliberately. `backend/evals/test_cases.py` is a separate, still-unwritten eval stub. **Frontend tests are vitest + jsdom** (`frontend/vitest.config.ts`, suites in `frontend/tests/`), added by S1 as the repo's first frontend runner; `npm run lint` still drops into Next's interactive ESLint setup and is not wired.

**`.dockerignore` is load-bearing:** the Dockerfile's `COPY backend/` would otherwise bake `backend/.env` (`TOKEN_ENCRYPTION_KEY`, `GROQ_API_KEY`) and `.ind_money_token.json` into any locally-built image. Add new secret files there as well as to `.gitignore`. The Dockerfile also gates the build on `backend/tests/check_tracing_in_image.py` — see below.

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

**RAG is dormant as of C1.** The code stays in `backend/rag/` — `ingest.py` chunks NSE PDFs from `data/nse_docs/` into the `nse_filings` ChromaDB collection at `data/chroma_db/`, and the Analyst queries it via `retriever.py` — but the corpus is empty, `chromadb`/`pypdf`/`langchain-text-splitters` are **not installed**, and `retriever.get_relevant_context()` degrades to `[]`. Do not add RAG-dependent behavior without re-enabling it first; the path is in `docs/SPECS/C1.md`.

**State persistence is in-memory** (`_RUNS`, `_ANALYSES`, `_PAPER_WATCHLIST`, `_ACTIONS` dicts in `backend/api/main.py`). Runs, stored analyses, and the paper watchlist survive a browser refresh but **not a backend restart**. This is a known limitation — swap for a DB to make durable.

**Postgres (`backend/db/`, added by F1; first consumer S1).** SQLModel tables — `users`, `broker_links`, `oauth_pending` (F1) and `snapshot_days`, `snapshot_holdings`, `snapshot_raw` (S1) — all with DB-level `ON DELETE CASCADE`, an async engine + `async_session` FastAPI dependency, Fernet helpers for the `*_enc` columns (`TOKEN_ENCRYPTION_KEY`), and Alembic migrations run on asyncpg — there is deliberately no sync Postgres driver. Details in `docs/SPECS/F1.md` and `docs/SPECS/S1.md`. **The database is optional at runtime:** with `DATABASE_URL` unset the dashboard still serves live totals and history is honestly empty — never a 500. Any deploy shipping a new migration needs `alembic upgrade head` against the production URL.

**Daily snapshots (S1).** `backend/services/snapshots.py` captures one row per user per **IST calendar day, with any run before 06:00 IST attributed to the previous day** — one helper (`attributed_day`) owns that rule and nothing derives a day from UTC or server-local "today". Three nets fill the same row through `UNIQUE (user_id, captured_on)`: the 23:45 IST cron, a ~01:00 IST retry, and an opportunistic capture fired when `/portfolio/summary` finds today missing. **The first capture of a day wins** — a retry rescues an empty day, it never overwrites a good reading. `POST /internal/snapshot` and `/internal/prune` are guarded by `CRON_SECRET` (fail-closed; **not** the admin secret — a CI runner must not hold a key that reads holdings). A missed snapshot cannot be backfilled: the MCP is point-in-time, so acquisition failures degrade (skip a dead link, keep a partial bucket set, store a NULL FX rate) rather than abort. Any future portfolio-graph invocation must pass `graph.portfolio_config.portfolio_runnable_config()`, which keeps LangSmith tracing off for holdings data even when `LANGCHAIN_TRACING_V2=true`. It does that by leaning on a langchain-core internal, so `langchain-core` is pinned despite being transitive and the Docker build runs `tests/check_tracing_in_image.py` as a gate — if you bump langchain/langsmith/langgraph, re-run `backend/tests/test_portfolio_config.py`.

**API ↔ frontend** (`backend/api/main.py` ↔ `frontend/lib/api.ts`): `POST /analyze` refuses with **409** unless IND Money is connected (an unauthenticated run can only yield an empty "0 candidates" pipeline), then streams Server-Sent Events (`start`, one `update` per agent node, then `complete` with recommendations/risk/`action_id`, or `error`). `POST /approve` resumes the paused graph. CORS: localhost/127.0.0.1 (any port) is always allowed; production origins come from `CORS_ALLOW_ORIGINS` (comma-separated) and optional `CORS_ALLOW_ORIGIN_REGEX`.

## Guardrails (enforced in `backend/agents/risk_manager.py`)

- Min confidence 0.70 to proceed (below → REJECT). Confidence in [0.70, 0.75) → FLAG (a caution label, still approvable), else PASS.
- Max 3 stocks per known sector (unknown-sector stocks exempt). Analyst action `avoid` → REJECT.
- Any `pending_actions` → `approved_actions` transition requires `human_approved=True`.

## Deployment

Frontend → Vercel (Root Directory = `frontend`, set `NEXT_PUBLIC_API_URL`). Backend → Hugging Face Spaces (Docker, port 7860; the repo-root `Dockerfile` runs `uvicorn api.main:app --app-dir backend`; it copies `backend/` only — no `data/`, no ingest step, no apt layer). See `DEPLOY.md` for the full env-var wiring — the three cross-references that must agree are `IND_MONEY_AUTH_REDIRECT` = `<backend>/auth/callback`, `CORS_ALLOW_ORIGINS` containing the live frontend origin, and `NEXT_PUBLIC_API_URL` = the backend URL.

## Conventions

- The `alphaDesk_graph` / `alphaDesk_*` naming (mixed case) is intentional and used across the codebase — match it.
- Broker integration is out of scope by design: implement `BrokerAdapter` in `backend/broker/` and set `BROKER=<name>`; the Execution agent already calls `broker.place_order` when one is configured. Leave `BROKER` blank for paper-only.
