# AlphaDesk v2 — Agent Execution Plan

**Product:** a multi-user portfolio analyzer for IND Money accounts. The existing
multi-agent stock research desk becomes one page inside it.

**Read first:** `CLAUDE.md` (repo conventions), then this file. `v2brief.md`
(gitignored, local only) holds the longer auth/DB rationale; everything an agent
needs to execute is duplicated here.

---

## 0. Protocol for agents

- Take **one task card** (§5). Work only in the files that card lists as *owns*.
  If you must change a file another card owns, stop and flag it instead.
- Branch naming is given per card. Branch off the base the card names, never off
  another feature branch.
- Definition of done = the card's acceptance criteria, verified by running the
  commands. Do not report done on unverified work.
- Backend imports resolve with `backend/` as root (`api.main`, `graph.*`,
  `tools.*`) — **no `backend.` prefix**. Run from inside `backend/`.
- Keep the existing `alphaDesk_*` mixed-case naming. Match surrounding style.
- Never construct chat models directly — go through `agents/llm.py::get_chat_llm`.

## 1. v1 scope

**In:** platform sign-in (Clerk) · per-user IND Money linking · net-worth
dashboard (snapshot, allocation breakdowns, row-level holdings with XIRR) · daily
snapshot history + trend chart · multi-agent AI overview (concentration,
diversification, SIP health, performance) · existing research desk, still a
separate page, now per-user.

**Out (v2+):** portfolio-aware research ("what should I buy given my holdings") ·
MF screener (`get_mf_by_category`) · US stocks (`get_us_stocks_details`) ·
liabilities/EMI view · options analytics. Do not build these; leave the tool
wrappers extensible so they slot in later.

## 2. Locked decisions

| Area | Decision |
|---|---|
| Identity | **Clerk**. Next.js SDK + FastAPI verify via `clerk-backend-api` (networkless RS256/JWKS). Not IND Money — its OAuth is not OIDC (no `userinfo_endpoint`, no `id_token`), so it has no stable subject and can only be a *linked credential*. |
| DB | **Postgres (Neon)** + SQLModel + Alembic. Required: HF Spaces disk is ephemeral. |
| Secrets at rest | IND Money refresh tokens encrypted (Fernet, `TOKEN_ENCRYPTION_KEY`). Never returned to the frontend. |
| History | Daily `networth_snapshot` per linked user, stored JSONB. MCP is point-in-time only, so without this there are no trends. |
| AI overview | Multi-agent LangGraph fan-out → synthesizer. **Numbers are computed in Python; agents narrate verified metrics and must not invent figures.** |
| Charts | Recharts (not currently a dependency — added in P3). |

## 3. Why the foundation comes first

Every portfolio tool (`networth_*`, `*_sips`) is per-user and read-only against
the caller's own IND Money link. Today `tools/ind_money_auth.py:306` is a single
process-wide `_auth = _Auth()` over one token file, so **one visitor's IND Money
account currently backs every visitor's request**, and any visitor can log
everyone out. The portfolio analyzer is unbuildable — and unsafe — until F3 lands.

## 4. Workstream map

```
F1 db+migrations ─→ F2 clerk identity ─→ F3 per-user IND Money   (sequential, one agent)
                                              │
                              ┌───────────────┼───────────────┬──────────────┐
                              ↓               ↓               ↓              ↓
                        P1 mcp tools    P2 snapshots     P3 dashboard   P4 ai overview
                         (parallel)      (needs P1)       (needs P1)     (needs P1+P2)
```

F1→F3 all touch `api/main.py` and the schema — running them in parallel produces
merge conflicts, not speed. Merge each to `main` as it completes. P-cards fan out
once F3 is on `main`.

---

## 5. Task cards

### F1 — Persistence layer
- **Branch:** `v2-foundation` (base `main`)
- **Owns:** `backend/db/` (new), `backend/alembic/`, `requirements.txt`, `backend/.env.example`
- **Build:** SQLModel models + Alembic for the §6 schema (all tables, including
  `portfolio_snapshots` — later cards only fill them). `db/crypto.py` with
  Fernet `encrypt()/decrypt()` keyed on `TOKEN_ENCRYPTION_KEY`. Async session
  dependency. Also wire **pytest** (`backend/tests/`) — every later card ships tests.
- **Acceptance:** `alembic upgrade head` builds a clean DB; `pytest` green;
  round-trip test proves an encrypted value never appears in plaintext in the DB.
  No behaviour change to existing endpoints.

### F2 — Clerk identity
- **Branch:** `v2-foundation` (after F1)
- **Owns:** `backend/api/deps.py` (new), `frontend/app/layout.tsx`, `frontend/middleware.ts`, `frontend/lib/api.ts`, `frontend/components/TopBar.tsx`
- **Build:** `current_user()` FastAPI dependency verifying Clerk JWTs, yielding
  `user_id`; lazily upsert the `users` row on first sight. `<ClerkProvider>`,
  middleware, sign-in page, `<UserButton>` in TopBar. Every `lib/api.ts` fetch
  attaches the JWT.
- **Also:** rename v1's `useAuth` → `useIndMoney` (`components/AuthProvider.tsx`)
  — it collides with Clerk's `useAuth`, and the new name is accurate: it means
  "has linked a broker", not "is signed in".
- **Acceptance:** unauthenticated request to any protected endpoint → 401;
  authenticated → 200 with a resolved `user_id`; `npx tsc --noEmit` and
  `npm run build` clean.

### F3 — Per-user IND Money linking  ← *the security fix*
- **Branch:** `v2-foundation` (after F2)
- **Owns:** `backend/tools/ind_money_auth.py`, `backend/tools/ind_money.py`, `backend/api/main.py`, `backend/graph/state.py`
- **Build:**
  - `_Auth` stops being a module singleton → `AuthStore.for_user(user_id)`,
    hydrated from `ind_money_links`. `_load/_persist/_invalidate` read/write that
    row, not `.ind_money_token.json`. The refresh/expiry logic in
    `status_verified()` and `_refresh_token()` is sound — carry it over unchanged.
  - Per-user `asyncio.Lock` (keyed dict) so one user's refresh serialises without
    blocking others.
  - **Bind `user_id` into the OAuth `state`, not a cookie.** The backend
    (`*.hf.space`) is a different site from the frontend, so a cookie at
    `/auth/callback` is third-party and unreliable. Replace the in-memory
    `_PENDING` dict with the `oauth_pending` table: `POST /auth/login` (has the
    JWT) writes `state → user_id`; the callback resolves the owner from `state`
    alone. Single-use + 10-min TTL, which also covers CSRF.
  - **Unlink revokes.** Today `logout()` only forgets locally, leaving a live
    token at IND Money. Call the `revocation_endpoint` from the discovery doc
    before deleting the row.
  - **Request both scopes:** `portfolio:read market:read` (`ind_money_auth.py:41`
    currently requests only `portfolio:read`; both are in `scopes_supported`).
    The `networth_*` tools need the former, market data the latter — this may
    also be why scan results are thin.
  - Gate all env/file credential fallbacks (`IND_MONEY_MCP_TOKEN`,
    `IND_MONEY_OAUTH_*`, and especially `_seed_from_claude()` reading
    `~/.claude/.credentials.json`) behind `ALPHADESK_SINGLE_TENANT=1`. **Never
    active in production** — on a multi-user server that hands the operator's own
    credentials to strangers.
  - Thread `user_id` through `PortfolioState` → `tools/ind_money.py` →
    `get_access_token(user_id)`.
  - Scope `_RUNS`/`_ANALYSES`/`_PAPER_WATCHLIST` to DB tables keyed by user;
    ownership checks on `/approve` and `/analysis/{id}` (404, not 403, on
    someone else's id). Swap `MemorySaver` for a Postgres checkpointer so a
    paused approval survives restart.
- **Acceptance:** two users linked simultaneously each see only their own status,
  runs and watchlist; user A cannot read or approve user B's run; unlink revokes
  upstream then deletes the row; with `ALPHADESK_SINGLE_TENANT` unset, no env
  fallback can authenticate anyone. Tests cover the cross-user isolation cases.

### P1 — Portfolio MCP wrappers
- **Branch:** `feat/portfolio-tools` (base `main`, after F3)
- **Owns:** `backend/tools/ind_money_portfolio.py` (new), tests
- **Build:** typed wrappers, same `_call_mcp_tool` + `_unwrap` pattern as
  `tools/ind_money.py` (responses arrive as `{"result": "<stringified JSON>"}`):
  `networth_snapshot()`, `networth_holdings(asset_type)`,
  `networth_allocation_breakdown(asset_type, breakdown_by)`,
  `indian_stocks_sips()`, `mf_sips()`. Pydantic models per response.
  - `asset_type` enum: `IND_STOCK, MF, US_STOCK, BOND, EPF, NPS, SA, FD, CRYPTO,
    INSURANCE, VEHICLE, RE, RD, AIF, PMS, PPF`. `breakdown_by`: `assets, sector, market_cap`.
  - **Data-quality caveat from the tool docs:** for linked (non-INDmoney)
    brokers `invested_amount` is often missing/0 — P&L and XIRR must degrade
    gracefully, never render a bogus -100%.
- **Acceptance:** each wrapper returns a typed model against a recorded fixture;
  a missing/0 `invested_amount` yields `None` P&L, not a wrong number.

### P2 — Snapshot history + cron
- **Branch:** `feat/portfolio-snapshots` (base `main`, after P1)
- **Owns:** `backend/services/snapshots.py` (new), `backend/api/routes/internal.py` (new), `frontend/vercel.json`
- **Build:** capture `networth_snapshot` + per-asset-type holdings into
  `portfolio_snapshots` (JSONB) for every linked user. Trigger:
  `POST /internal/snapshot` guarded by a `CRON_SECRET` header, called by
  **Vercel Cron** (HF Spaces has no reliable scheduler and sleeps). Idempotent
  per user per day. Skip and log users whose link is expired — never let one
  user's failure abort the batch.
- **Acceptance:** two runs on the same day produce one row per user; a user with
  a revoked link is skipped without failing the batch; wrong/absent secret → 401.

### P3 — Portfolio dashboard UI
- **Branch:** `feat/portfolio-dashboard` (base `main`, after P1)
- **Owns:** `frontend/app/portfolio/`, `frontend/components/portfolio/`, `backend/api/routes/portfolio.py` (new)
- **Build:** `GET /portfolio/summary|holdings|allocation|history` (§7), then the
  page: net-worth header (invested vs current, absolute + %), allocation charts
  (Recharts — by asset type, sector, market cap), sortable holdings table with
  per-row P&L% and XIRR, net-worth trend line from `portfolio_snapshots`.
  Terminal aesthetic — match existing `pill-*` / `eyebrow` classes and the
  Bloomberg-ish density of `ResultsDashboard.tsx`.
- **Acceptance:** loads for a linked user; unlinked user sees the existing
  Connect gate, not an error; empty/zero-holding asset types render as empty
  states; `npx tsc --noEmit` + `npm run build` clean; no horizontal page scroll
  at 375px.

### P4 — AI overview (multi-agent)
- **Branch:** `feat/ai-overview` (base `main`, after P1+P2)
- **Owns:** `backend/graph/portfolio_graph.py` (new), `backend/agents/portfolio/` (new), `backend/api/routes/overview.py` (new), frontend overview panel
- **Build:** compute metrics **deterministically in Python first** —
  Herfindahl index, top-N weight, single-holding %, sector drift, XIRR, week-over-week
  delta from snapshots. Then fan out parallel specialists over those verified
  numbers: `allocation_critic`, `concentration_risk`, `sip_health`,
  `performance_attribution` → `synthesizer` writes the narrative.
  - **Agents may not invent figures.** Every number in the output must trace to
    a computed metric passed in. Include the metric dict in the response so the
    UI can show the number next to the claim.
  - Stream via SSE, reusing the `start`/`update`/`complete` event contract in
    `api/main.py::_sse` and `frontend/lib/api.ts::streamAnalyze`.
  - **No human-approval gate and no risk guardrails here** — this pipeline is
    read-and-reason only. Do not reuse `interrupt_before`.
- **Acceptance:** every figure in the narrative appears in the returned metric
  dict; a portfolio with one holding produces a sane concentration warning rather
  than a crash; overview regenerates without duplicating snapshot rows.

---

## 6. Schema

```
users               id (clerk user_id, PK) | email | created_at
ind_money_links     user_id FK UNIQUE | access_token_enc | refresh_token_enc
                    | expires_at | client_id | client_secret_enc | token_url
                    | scope | linked_at | last_refresh_at
oauth_pending       state (PK) | user_id FK | verifier | redirect_uri | client_id
                    | client_secret_enc | token_url | created_at   (TTL 10 min, single use)
runs                id (uuid, = thread_id) | user_id FK | query | status | action_id | created_at
analyses            run_id FK | user_id FK | payload JSONB | created_at
watchlist           user_id FK | symbol | run_id | query | added_at   PK (user_id, symbol)
portfolio_snapshots id | user_id FK | captured_on DATE | snapshot JSONB
                    | holdings JSONB | total_value NUMERIC   UNIQUE (user_id, captured_on)
```

`ind_money_links` is 1:1 with `users` and cascade-deletes with it.
Registered OAuth client id/secret live on the link row and are reused on re-link
(dynamic client registration currently runs per login — `ind_money_auth.py:350`).

## 7. API contract — the interface between agents

| Endpoint | Auth | Returns |
|---|---|---|
| `POST /auth/login` | JWT | `{authorization_url}`; writes `oauth_pending` |
| `GET /auth/callback?code&state` | none | HTML page; resolves user from `state` |
| `GET /auth/status` | JWT | caller's link status |
| `POST /auth/logout` | JWT | revokes upstream, deletes link |
| `GET /portfolio/summary` | JWT | net worth, invested, current, P&L, asset-type allocation |
| `GET /portfolio/holdings?asset_type=` | JWT | rows: symbol, units, price, value, pnl, pnl_pct, xirr, broker |
| `GET /portfolio/allocation?asset_type=&by=` | JWT | breakdown buckets + weights |
| `GET /portfolio/history?days=` | JWT | `[{captured_on, total_value}]` from snapshots |
| `POST /portfolio/overview` | JWT | SSE: `start` / `update` per agent / `complete` with `{narrative, metrics[]}` |
| `POST /internal/snapshot` | `CRON_SECRET` | `{users_captured, skipped}` |
| `POST /analyze`, `/approve`, `GET /analyses`, `/analysis/{id}`, `/watchlist` | JWT | as today, scoped to caller |

Any endpoint touching another user's data returns **404, not 403** — don't leak existence.

## 8. Privacy rules — non-negotiable

This app now holds net worth, holdings and liabilities. Two failure modes agents
must actively prevent:

1. **LLM prompts.** Portfolio data goes to Groq for the overview. Send aggregates
   and instrument symbols only — never account numbers, broker ids, emails, or
   the Clerk `user_id`. Add `redact()` in `agents/portfolio/` and route every
   prompt through it.
2. **LangSmith tracing is on by default** (`LANGCHAIN_TRACING_V2`) and would ship
   full prompt payloads — i.e. users' financial positions — to LangSmith. Either
   disable tracing on the portfolio graph or make it opt-in per environment.
   **Decide before P4 ships; do not leave it on by accident.**

Also: never log decrypted tokens, never return a token to the frontend, and keep
`backend/.ind_money_token.json` gitignored (it stays only for single-tenant dev).

## 9. Env vars

**Backend (new):** `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `CLERK_JWKS_URL`,
`CLERK_ISSUER`, `CRON_SECRET`, `ALPHADESK_SINGLE_TENANT` (dev only).
**Frontend (new):** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`.
**Unchanged, must still agree:** `IND_MONEY_AUTH_REDIRECT` = `<backend>/auth/callback`,
`CORS_ALLOW_ORIGINS` ⊇ frontend origin, `NEXT_PUBLIC_API_URL` = backend URL.

## 10. Open questions — resolve before the dependent card

- **Does IND Money's dynamic client registration tolerate one client per user?**
  DCR runs per-login today so probably yes, but if `/register` is rate-limited or
  binds clients to an account, F3 needs a single pre-registered client with
  per-user tokens instead. **Verify before starting F3.**
- **Does `get_indian_stocks_details` accept `segments: [analyst, news]`** like its
  US counterpart? If so the Research agent is leaving analyst ratings and news
  sentiment unused. Probe and report; not v1 scope, but cheap to confirm.
- **Rate limiting.** An authenticated stranger can burn the Groq quota via
  `/analyze` and `/portfolio/overview`. Decide the per-user cap before sign-ups open.
- **Cold starts.** HF Spaces sleeps and Neon free tier idles; first request after
  idle is slow. The dashboard needs a real loading state, not a spinner that
  looks hung.
