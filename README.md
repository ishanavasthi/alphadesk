---
title: AlphaDesk
emoji: 📈
colorFrom: blue
colorTo: indigo
sdk: docker
pinned: false
---
# AlphaDesk

AlphaDesk is a **multi-user portfolio analyzer for Indian retail investors**.
You sign in, link your IND Money account, and see your net worth, allocation,
holdings and daily history — with an AI overview that narrates *verified,
computed numbers* (never invented ones). The original multi-agent stock
research desk lives on as a clearly-labelled **Lab** — impressive machinery,
explicitly a simulation.

A LangGraph + FastAPI backend serves a Bloomberg-adjacent Next.js frontend.
Market and portfolio data come from the read-only **IND Money MCP** server;
identity is **Clerk**; state persists to **Neon Postgres**.

> **No real orders are ever placed.** The broker layer is a stub by design.
> The product is **descriptive analytics only** — analysis of what *is*, never
> forward forecasts or instrument-level buy/sell advice on real holdings.

> **Build status:** v2 is complete — see `V2_PLAN.md` (plan of record),
> `docs/STATUS.md` (card ledger), and `docs/MORNING.md` (the operator runbook /
> handoff). Per-card contracts are in `docs/SPECS/` and `docs/TESTING/`.

## The two surfaces

| Surface | Route | What it is |
| --- | --- | --- |
| **Portfolio** | `/portfolio` | Your real net worth, allocation, sortable holdings, net-worth trend, and a multi-agent **AI overview** over computed metrics. |
| **Demo** | `/demo` | The full dashboard rendered from synthetic fixtures + a pre-generated narrative. Public, no sign-in, no LLM call — how anyone without an IND Money account sees the product. |
| **Lab** | `/lab` | The research desk: scans NSE movers, writes analyst reports, enforces risk guardrails, and stages picks onto a **paper** watchlist behind a human gate. A labelled simulation, never shown next to real holdings. |

## Architecture

```mermaid
flowchart LR
  subgraph Browser
    UI[Next.js UI - shadcn portfolio + terminal Lab]
  end
  subgraph Vercel
    UI
  end
  subgraph Backend[FastAPI on HF Space]
    API[REST + SSE]
    PGraph[Portfolio: metrics + AI overview graph]
    LGraph[Lab: research pipeline]
    Conn[Per-source connectors -> Holding model]
    Auth[Per-user OAuth AuthStore - encrypted]
    Snap[Snapshot service]
  end
  subgraph External
    Clerk[Clerk identity]
    Neon[(Neon Postgres)]
    MCP[IND Money MCP]
    OpenAI[OpenAI - overview]
    Groq[Groq - Lab]
    FX[frankfurter.dev USD/INR]
  end
  UI -->|JWT| API
  Clerk -->|verify JWT networklessly| API
  API --> Conn --> MCP
  API --> PGraph --> OpenAI
  API --> LGraph --> Groq
  Auth -->|per-user token| MCP
  Snap --> Neon
  Snap --> FX
  API --> Neon
```

Everything downstream of a broker reads **one shape** — a normalized `Holding`
model (`backend/portfolio/models.py`). Each source (IND Money today, a `stub`
connector for the demo/tests) maps its vendor payload into `Holding`; no vendor
field name appears above the connector boundary. The dashboard, allocation
math, snapshots, and AI metrics all consume `Holding` and know nothing about
IND Money.

## Identity & multi-tenancy

- **Clerk** for sign-in (Waitlist-gated for launch). The backend verifies Clerk
  session JWTs networklessly (RS256 against the JWKS), holding **no Clerk
  secret**; it upserts a `users` row on first sight. `azp` and `sid` checks are
  mandatory (fail-closed 503/401).
- **Per-user broker links.** Each user's IND Money OAuth link is bound to their
  Clerk identity and stored **Fernet-encrypted** in Postgres, with the OAuth
  `state` bound to the user server-side (no cookie). There is no shared,
  ambient, or admin-secret credential path — every endpoint derives identity
  from the verified token, and cross-user access returns 404 (never leaks
  existence).

## Data model & persistence

- **Neon Postgres** via SQLModel + Alembic (migrations `0001`–`0005`). Tables:
  `users`, `broker_links`, `oauth_pending`, `snapshot_days` (+ `snapshot_holdings`,
  `snapshot_raw`), `watchlist`. Every user-scoped table cascade-deletes with the
  user (the basis for one-click **delete-my-data**).
- **Daily snapshots.** A GitHub Actions job (`snapshot.yml`, ~23:45 IST + a
  retry) captures each linked user's normalized holdings + total into
  `snapshot_days`, plus the day's **USD/INR rate** (frankfurter.dev). Attribution
  is IST calendar-day with a 06:00 cutoff; the first capture of a day wins; a
  missed snapshot can never be backfilled, so the design targets *acquisition*
  failure (skip a dead link, keep a partial bucket set, NULL the FX rate — never
  abort the batch). A staleness banner surfaces a stalled job.
- **Lab state is ephemeral** (in-memory, per-user, `MemorySaver`) except the
  **paper watchlist**, which persists denormalized (each row is a self-contained
  decision record; the originating run id is an opaque non-FK reference).

## AI overview (portfolio)

The overview's numbers are **computed in Python first** — Herfindahl index,
top-N and single-holding weights, sector concentration, week-over-week
net-worth delta. Then a fan-out of specialists (`allocation_critic`,
`concentration_risk`, `sip_health`, `performance_attribution`) → a synthesizer
narrates *those verified metrics*.

- **Agents may not invent figures.** A number reaches the UI only as a metric
  chip bound to a computed value; any digit in free-written prose trips a
  scripted fallback. Every figure in the narrative is shown beside its source
  metric.
- **Graceful degradation is a requirement.** With the LLM unavailable (no key,
  provider down, rate-limited, budget exceeded) the dashboard renders
  completely — every computed number intact — and the panel shows "AI overview
  unavailable". Never an error page.
- **Routing:** portfolio agents use OpenAI (`provider="openai"`); the four Lab
  agents stay on Groq at their existing tiers, untouched. Prompts are routed
  through `redact()` (aggregates + symbols only — never account numbers, broker
  ids, emails, or the Clerk `user_id`). LangSmith tracing is on for the Lab
  graph, off for the portfolio graph (someone's finances) at config level.

XIRR is intentionally absent — the MCP is point-in-time and carries no dated
cashflows (verified in the C2 data spike); the per-holding return metric is a
simple cumulative return, and a holding with no reported cost basis renders
"—", never a fabricated −100%.

## The Lab (research desk — labelled simulation)

A linear LangGraph over `PortfolioState`: Scanner → Research → Analyst →
RiskManager → (human gate) → Execution. Each agent is a pure
`async (state) -> state` function. The graph is compiled with
`interrupt_before=["execution"]` + a checkpointer, so it pauses before staging
anything; nothing reaches the paper watchlist without approval. Guardrails
(`backend/agents/risk_manager.py`): minimum confidence 0.70 (below → REJECT),
[0.70, 0.75) → FLAG, max 3 stocks per known sector, analyst `avoid` → REJECT.
Its picks are never rendered in the same view as real holdings.

## Security & privacy

- Per-user identity on every endpoint; cross-user access is 404, not 403.
- Broker tokens Fernet-encrypted at rest, never logged, never returned to the
  frontend. `/demo` is structurally networkless (no auth/LLM call). LLM prompts
  are redacted.
- **Delete-my-data** (`DELETE /account`) revokes the broker token upstream, then
  a single `DELETE FROM users` cascades every table atomically (+ clears
  per-user in-memory caches). Rate limits + app-side spend caps guard the
  expensive endpoints; the internal snapshot routes are `CRON_SECRET`-gated.
- Privacy/terms name every subprocessor (Groq, OpenAI, LangSmith, Clerk, Neon,
  Hugging Face, Vercel); a consent screen is unskippable before the OAuth
  redirect.

## Tech stack

- **Backend:** Python 3.11+, FastAPI, LangGraph, SQLModel + Alembic, asyncpg,
  `cryptography` (Fernet), PyJWT (Clerk verification), the `mcp` SDK. Every dep
  pinned (`==`).
- **Frontend:** Next.js 15, TypeScript, Tailwind, shadcn/ui (portfolio surfaces)
  + the evolved terminal aesthetic (Lab), Recharts, Clerk Next.js SDK.
- **Data/infra:** Neon Postgres, Clerk, IND Money MCP, OpenAI (overview), Groq
  (Lab), frankfurter.dev (FX), LangSmith (Lab tracing). Backend on Hugging Face
  Spaces (Docker, port 7860); frontend on Vercel.

## Getting started (local dev)

```bash
python -m venv .venv && source .venv/bin/activate     # repo-root venv
pip install -r requirements.txt -r requirements-dev.txt
cp backend/.env.example backend/.env                  # then fill values

# A local Postgres for the DB layer (see docs/TESTING/F1.md):
docker run --rm -d -e POSTGRES_PASSWORD=test -e POSTGRES_DB=alphadesk \
  -p 5433:5432 postgres:16
cd backend
DATABASE_URL="postgresql+asyncpg://postgres:test@localhost:5433/alphadesk" \
  alembic upgrade head
uvicorn api.main:app --reload --port 8000             # docs at /docs
```

Local single-tenant dev (no Clerk): set `ALPHADESK_SINGLE_TENANT=1` in
`backend/.env` and use the Connect button (links as `user_id="local"`).

```bash
cd frontend && npm install
npm run dev                                           # localhost:3000
```

Run the test suite the CI way — with `backend/.env` absent (or `DATABASE_URL`
unset) and a throwaway `TEST_DATABASE_URL` Postgres — for a clean **674 passed**
(see `docs/MORNING.md` §5 for the one rate-limit-test caveat).

## Deployment

Full env-var wiring and the go-live sequence are in **`DEPLOY.md`**; the operator
runbook (current state, what was wired, remaining steps) is in
**`docs/MORNING.md`**. In short: frontend → Vercel (root `frontend`), backend →
HF Space (from the binary-free `space-deploy` snapshot branch), database →
Neon, identity → Clerk (Waitlist mode). The site ships gated behind
`NEXT_PUBLIC_AUTH_ENABLED` — flip it on (with real Clerk keys on Vercel) to go
live.

## Project structure

```
alphadesk/
├── V2_PLAN.md · DEPLOY.md · CLAUDE.md
├── docs/            # STATUS.md (ledger), MORNING.md (runbook), SPECS/, TESTING/, design/
├── backend/
│   ├── api/         # main.py (Lab + auth), routes/ (portfolio, overview, internal, account)
│   ├── portfolio/   # Holding model + connectors (ind_money, stub)
│   ├── agents/      # Lab agents + agents/portfolio/ (metrics, redact, AI overview)
│   ├── graph/       # Lab pipeline + portfolio_graph + portfolio_config (tracing off)
│   ├── services/    # snapshots, adoption
│   ├── tools/       # IND Money MCP + per-user OAuth AuthStore
│   ├── db/          # SQLModel models, async session, Fernet crypto
│   ├── alembic/     # migrations 0001–0005
│   ├── rag/         # dormant (unplugged at C1)
│   └── tests/
├── frontend/        # app/ (portfolio, demo, lab, marketing, legal), components/, lib/
└── .github/workflows/  # keepalive.yml, snapshot.yml
```

## RAG (dormant)

The retrieval path over NSE filing PDFs is **unplugged as of v2**: the corpus is
empty and `chromadb`/`pypdf`/`langchain-text-splitters` are not installed, so the
Lab Analyst runs with no filing context. The code stays in `backend/rag/`
(degrades to `[]`). Re-enable path: `docs/SPECS/C1.md`.
