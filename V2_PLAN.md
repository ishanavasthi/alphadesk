# AlphaDesk v2 — Agent Execution Plan

**Product:** a multi-user **portfolio analyzer** for Indian retail investors.
Users sign in, link their IND Money account, and see their net worth, allocation,
holdings and history, plus an AI overview that narrates *verified computed
numbers*. The existing multi-agent stock research desk is demoted to a clearly
labelled **Lab** section — impressive machinery, explicitly a simulation.

**Read first:** `CLAUDE.md` (repo conventions), then this file. `BACKLOG.md` holds
everything deliberately deferred (Groww, statement import, manual holdings,
projections, live order placement) with the reason it's parked — check it before
proposing scope. `v2brief.md` (gitignored) is superseded by this file where they
disagree.

This plan is the output of a full design review (2026-08-14). Decisions in §2 and
the rules in §8 were argued and settled — an agent that wants to reverse one must
raise it, not quietly re-decide it.

---

## 0. Protocol for agents

- Take **one task card** (§5). Work only in the files that card lists as *owns*.
  If you must change a file another card owns, stop and flag it instead.
- Branch off the base the card names, never off another feature branch.
- Definition of done = the card's acceptance criteria, verified by running the
  commands. Do not report done on unverified work.
- Backend imports resolve with `backend/` as root (`api.main`, `graph.*`,
  `tools.*`) — **no `backend.` prefix**. Run from inside `backend/`.
- Keep the existing `alphaDesk_*` mixed-case naming. Match surrounding style.
- Never construct chat models directly — go through `agents/llm.py::get_chat_llm`.
- **Every function that touches user data takes an explicit `user_id` argument
  from the first line it is written.** Before F3 lands it is a constant
  (`"local"`); it is never implicit, never a global, never inferred. This one rule
  is what makes the sequencing in §4 safe instead of a rewrite.

## 1. Scope

**In (v2):** platform sign-in (Clerk, invite-gated) · per-user IND Money linking ·
normalized portfolio model with per-source connectors · net-worth dashboard
(snapshot, allocation breakdowns, row-level holdings) · daily snapshot history +
trend chart · multi-agent AI overview over computed metrics · the research desk,
demoted to Lab, now per-user · pre-launch privacy bar.

**Out — see `BACKLOG.md` for each:** Groww connector · broker statement/CAS import ·
manual/user-added holdings and FDs · portfolio projection · goal tracking ·
drift alerts · tax-lot view · MF screener · US stocks · liabilities/EMI · options
analytics · worldmonitor · portfolio-aware research · live order placement.

Do not build these. Do leave the connector interface and tool wrappers
extensible so they slot in without a refactor.

## 2. Locked decisions

| Area | Decision |
|---|---|
| Audience | **Public URL, invite-gated.** Clerk allowlist; you approve each user. Open sign-up is a later switch, not a launch requirement. |
| Identity | **Clerk**. Next.js SDK + FastAPI verify via `clerk-backend-api` (networkless RS256/JWKS). Not IND Money — its OAuth is not OIDC (no `userinfo_endpoint`, no `id_token`), so it has no stable subject and can only be a *linked credential*. |
| DB | **Postgres (Neon)** + SQLModel + Alembic. Required: HF Spaces disk is ephemeral. |
| Data model | **One normalized `Holding` model; every source is a connector that maps into it.** Never store a vendor payload shape as the app's model. |
| Holding identity | Keyed on `(source, external_id)`. **No cross-source auto-merge** — display groups by instrument and *asks* before combining. A silently wrong net worth is the one error a user cannot catch. |
| Valuation | Computed where a formula or price exists; user-entered only as fallback, always carrying a visible `as_of` staleness marker. |
| Secrets at rest | Broker refresh tokens encrypted (Fernet, `TOKEN_ENCRYPTION_KEY`). Never returned to the frontend. |
| History | Daily snapshot per linked user: **normalized rows + totals**, with the raw payload retained 90 days for forensics. MCP is point-in-time only. |
| Snapshot capture | **GitHub Actions** scheduled workflow (not Vercel Cron — Hobby caps at one run/day and cannot retry). Two attempts daily + retry; idempotent per `(user_id, captured_on)`. |
| AI overview | Multi-agent LangGraph fan-out → synthesizer. **Numbers are computed in Python; agents narrate verified metrics and must not invent figures.** |
| Product framing | **Descriptive analytics + scenario arithmetic only.** No forward forecasts, no instrument-level advice on real holdings. See §8. |
| Research desk | Demoted to a labelled **Lab / Simulation** area. Never fused with the portfolio view. |
| Tracing | LangSmith **on for the research graph, off for the portfolio graph**, set at graph config level — not by env var. |
| RAG | **Unplugged, not deleted.** `data/nse_docs` is empty, so it has been inert in production regardless. See card C1. |
| Charts | Recharts (not currently a dependency — added in D1). |

## 3. Architecture spine

Everything downstream of a broker reads **one shape**:

```python
Holding:
  source: str            # "ind_money" | "manual" | future connectors
  external_id: str       # stable id within that source; (source, external_id) is identity
  asset_type: AssetType  # IND_STOCK | MF | US_STOCK | BOND | EPF | NPS | SA | FD | ...
  symbol: str | None     # display/grouping key; may be None for opaque assets
  isin: str | None
  units: Decimal | None
  avg_cost: Decimal | None
  invested_amount: Decimal | None   # often missing/0 for linked brokers — see C2
  current_price: Decimal | None
  current_value: Decimal            # the only field that is always required
  as_of: datetime
  raw: dict                         # source payload, for forensics
```

A **connector** implements: `fetch_snapshot(user_id)`, `fetch_holdings(user_id, asset_type)`,
`fetch_allocation(user_id, asset_type, by)`, `fetch_sips(user_id)`, plus a
`link_health(user_id)` that reports `linked | expiring | needs_relink | revoked`.
`link_health` must not assume the source can refresh — a future connector may be
authorization-code-only (see `BACKLOG.md`, Groww).

The dashboard, allocation math, XIRR, snapshots and AI metrics consume `Holding`
and know nothing about IND Money. **No vendor field name appears above the
connector boundary.**

## 4. Sequencing

```
C0 mitigate (today, main)
 └→ C1 unplug RAG
      └→ F1 db+migrations
           └→ C2 data spike ──→ M1 model + connectors ─┬→ D1 dashboard
                                                       └→ S1 snapshots + capture job
                                                            └→ A1 ai overview
                          ┌─────────────────────────────────────────┘
                          ↓
                   F2 clerk ─→ F3 per-user linking ─→ F4 per-user state ─→ L1 pre-launch bar
                                                                            ‖
                                                                    ══ INVITE GATE ══
```

**Why this order, not foundation-first.** The original plan front-loaded F1–F3 on
the urgency of the live security hole. C0 removes that urgency in an afternoon,
and invite-gating removes it structurally. Meanwhile the normalized model (M1)
must be designed against *real payloads*, which is easiest while you are the only
user. F2–F4 are prerequisites of **inviting people**, not of building — so they
land immediately before the invite gate, and nothing goes out before L1.

The `user_id`-from-day-one rule in §0 is what keeps this honest. Without it, this
ordering is the refactor trap it looks like.

**Nothing is invited until F2, F3, F4 and L1 are all merged to `main`.**

---

## 5. Task cards

### C0 — Close the live hole (do this first, today)
- **Branch:** `fix/lockdown` (base `main`) — small, merge same day.
- **Owns:** `backend/api/main.py`, `backend/tools/ind_money_auth.py`
- **Problem:** `_auth = _Auth()` (`ind_money_auth.py:306`) is a process-wide
  singleton over one token file. On the public URL, whoever clicks Connect links
  their IND Money account to the **whole server**; every other visitor's queries
  then run on that person's token, and any visitor can `POST /auth/logout` and
  kill it. `_seed_from_claude()` (`ind_money_auth.py:108`) reads
  `~/.claude/.credentials.json` — locally, that hands the operator's own
  credential store to any caller.
- **Build:** gate `POST /auth/login` and `POST /auth/logout` behind a shared
  secret header (`ALPHADESK_ADMIN_SECRET`) until F3 lands. Gate
  `_seed_from_claude()` and the `IND_MONEY_MCP_TOKEN` / `IND_MONEY_OAUTH_*`
  fallbacks behind `ALPHADESK_SINGLE_TENANT=1`, unset in production.
- **Acceptance:** without the header, `/auth/login` and `/auth/logout` return 401;
  with `ALPHADESK_SINGLE_TENANT` unset, no env or file fallback can authenticate
  anyone; the deployed app still serves read-only pages.

### C1 — Unplug RAG, slim the image
- **Branch:** `chore/slim-image` (base `main`)
- **Owns:** `requirements.txt`, `Dockerfile`, `README.md`
- **Context:** `data/nse_docs` is **empty (0 bytes)**; `data/chroma_db` is a 184K
  empty collection. The Analyst has been running without filing context all
  along. `rag/retriever.py` already degrades gracefully — any import or query
  failure sets `_init_failed` and returns `[]`.
- **Build:** drop `chromadb` from `requirements.txt`; remove `build-essential`
  and the `python -m rag.ingest` step from the `Dockerfile`. **Change no Python.**
  Leave `backend/rag/` in the repo, dormant. Correct the README's RAG claim.
- **Why:** cold-start time on the HF Space becomes load-bearing for S1's capture
  job. Re-enabling later is `pip install chromadb` plus actually adding PDFs.
- **Acceptance:** image builds without `build-essential`/`chromadb`; the pipeline
  runs end to end and the Analyst produces a report with empty RAG context; no
  Python diff.

### F1 — Persistence layer
- **Branch:** `v2-foundation` (base `main`)
- **Owns:** `backend/db/` (new), `backend/alembic/`, `requirements.txt`, `backend/.env.example`
- **Build:** SQLModel models + Alembic for the §6 schema (all tables; later cards
  fill them). `db/crypto.py` with Fernet `encrypt()/decrypt()` keyed on
  `TOKEN_ENCRYPTION_KEY`. Async session dependency. Wire **pytest**
  (`backend/tests/`) — every later card ships tests.
- **Also:** set LangSmith tracing off on the portfolio graph at config level (a
  `RunnableConfig`, **not** an env var — env vars get flipped on by a future you
  debugging prod) and assert it in a test. §8.2 is a rule, and rules that live
  only in prose do not fail builds.
- **Acceptance:** `alembic upgrade head` builds a clean DB; `pytest` green;
  round-trip test proves an encrypted value never appears in plaintext in the DB;
  a test asserts the portfolio graph's config has tracing disabled. No behaviour
  change to existing endpoints.

### C2 — Data spike  ← *blocks M1, D1, A1*
- **Branch:** `spike/ind-money-portfolio` (base `main`, after F1)
- **Owns:** `backend/tests/fixtures/` (new), `docs/ind_money_payloads.md` (new)
- **Nobody has ever seen a `networth_*` response.** Three downstream commitments
  rest on unverified shapes, and all three are cheap to check and expensive to
  guess wrong.
- **Build:** against your own linked account, call `networth_snapshot()`,
  `networth_holdings(asset_type)` for every type, `networth_allocation_breakdown`
  for each `breakdown_by`, `indian_stocks_sips()`, `mf_sips()`. Save **redacted**
  JSON to `backend/tests/fixtures/`. Document in `docs/ind_money_payloads.md`:
  1. **Is per-row XIRR in the payload?** If not, D1's "holdings table with XIRR"
     and A1's XIRR metric are dead as specified — XIRR needs dated cashflows a
     point-in-time call may not carry. Report the alternative (or its absence).
  2. **How often is `invested_amount` missing or 0?** Per source/broker.
  3. **Does `networth_snapshot` return a usable total** to store as `NUMERIC`?
  4. **Does dynamic client registration tolerate one client per user?** DCR runs
     per-login today (`ind_money_auth.py:350`), so probably — but if `/register`
     is rate-limited or binds clients to an account, F3 needs one pre-registered
     client with per-user tokens instead.
- **Acceptance:** fixtures committed and redacted (no account numbers, no
  tokens); the doc answers all four questions explicitly, including "no" answers;
  M1's model is designed **after** reading it.

### M1 — Normalized model + connectors
- **Branch:** `feat/portfolio-model` (base `main`, after C2)
- **Owns:** `backend/portfolio/` (new: `models.py`, `connectors/base.py`, `connectors/ind_money.py`, `connectors/stub.py`), tests
- **Build:** the `Holding` model and connector interface from §3. The IND Money
  connector reuses the `_call_mcp_tool` + `_unwrap` pattern from
  `tools/ind_money.py` (responses arrive as `{"result": "<stringified JSON>"}`)
  and maps vendor fields onto `Holding`. `asset_type` enum: `IND_STOCK, MF,
  US_STOCK, BOND, EPF, NPS, SA, FD, CRYPTO, INSURANCE, VEHICLE, RE, RD, AIF, PMS,
  PPF`; `breakdown_by`: `assets, sector, market_cap`.
- **Also build the stub connector** — fixture-backed, for a synthetic second
  user. It is not test scaffolding: it proves the interface has two
  implementations (so it is a real seam, not a rename), makes F4's cross-user
  isolation testable in CI forever, and gives you a "try with sample data" demo
  path for visitors without a broker account.
- **Degrade honestly:** a missing or 0 `invested_amount` yields `None` P&L and
  `None` XIRR — never a bogus -100%. Assert this.
- **Acceptance:** every connector method returns typed `Holding`s against the C2
  fixtures; stub and IND Money connectors are interchangeable behind the
  interface; missing `invested_amount` yields `None`, not a wrong number; no
  vendor field name appears outside `connectors/`.

### D1 — Portfolio dashboard
- **Branch:** `feat/portfolio-dashboard` (base `main`, after M1)
- **Owns:** `frontend/app/portfolio/`, `frontend/components/portfolio/`, `backend/api/routes/portfolio.py` (new)
- **Build:** `GET /portfolio/summary|holdings|allocation|history` (§7), then the
  page: net-worth header (invested vs current, absolute + %), allocation charts
  (Recharts — asset type, sector, market cap), sortable holdings table with
  per-row P&L% (and XIRR **only if C2 confirmed it exists**), net-worth trend
  line from snapshots. Terminal aesthetic — match existing `pill-*` / `eyebrow`
  classes and the density of `ResultsDashboard.tsx`.
- **Cold starts are a design constraint, not a polish item:** the HF Space sleeps
  after 48h idle and Neon idles. First load needs a real progressive loading
  state, not a spinner that looks hung.
- **Acceptance:** loads for a linked user; unlinked user sees the Connect gate,
  not an error; empty/zero-holding asset types render as empty states; a holding
  with no `invested_amount` renders "—" not "-100%"; `npx tsc --noEmit` and
  `npm run build` clean; no horizontal page scroll at 375px.

### S1 — Snapshots + capture job
- **Branch:** `feat/portfolio-snapshots` (base `main`, after M1)
- **Owns:** `backend/services/snapshots.py` (new), `backend/api/routes/internal.py` (new), `.github/workflows/snapshot.yml` (new)
- **A missed snapshot can never be backfilled.** The MCP is point-in-time; there
  is no "what was my net worth last Tuesday". A failed run does not delay data,
  it destroys it. The DB makes stored rows durable; it cannot create a row for a
  day the job never ran. Design for acquisition failure, not storage failure.
- **Build:** for every linked user, capture normalized `Holding` rows +
  `total_value` into `snapshot_days` / `snapshot_holdings`, and the raw payload
  into `snapshot_raw`. Trigger: `POST /internal/snapshot` guarded by a
  `CRON_SECRET` header, called by a **GitHub Actions** scheduled workflow that
  wakes the Space, polls until ready, triggers, and **retries with backoff**.
  Schedule **twice daily** (18:30 and 21:00 IST) — idempotency per
  `(user_id, captured_on)` makes the second run a free no-op if the first worked.
  Third net: opportunistic capture when a user loads the dashboard and today's
  row is missing. Skip and log users whose link is expired — never let one user's
  failure abort the batch.
- **Retention:** normalized rows forever; `snapshot_raw` pruned at 90 days.
- **Acceptance:** two runs on the same day produce one `snapshot_days` row per
  user; a user with a revoked link is skipped without failing the batch;
  wrong/absent secret → 401; a simulated 502 on the first attempt still produces
  the row via retry; the prune job deletes raw payloads older than 90 days and
  leaves normalized rows intact.

### F2 — Clerk identity
- **Branch:** `v2-foundation` (after F1)
- **Owns:** `backend/api/deps.py` (new), `frontend/app/layout.tsx`, `frontend/middleware.ts`, `frontend/lib/api.ts`, `frontend/components/TopBar.tsx`
- **Build:** `current_user()` FastAPI dependency verifying Clerk JWTs, yielding
  `user_id`; lazily upsert the `users` row on first sight. `<ClerkProvider>`,
  middleware, sign-in page, `<UserButton>` in TopBar. Every `lib/api.ts` fetch
  attaches the JWT. **Configure Clerk for invite-only** (restricted sign-up).
- **Also:** rename v1's `useAuth` → `useIndMoney` (`components/AuthProvider.tsx`)
  — it collides with Clerk's `useAuth`, and the new name is accurate: it means
  "has linked a broker", not "is signed in". Home page gate becomes two-stage:
  signed out → sign in; signed in but unlinked → the existing Connect banner.
- **Acceptance:** unauthenticated request to any protected endpoint → 401;
  authenticated → 200 with a resolved `user_id`; a non-invited email cannot
  complete sign-up; `npx tsc --noEmit` and `npm run build` clean.

### F3 — Per-user broker linking  ← *the security fix*
- **Branch:** `v2-foundation` (after F2)
- **Owns:** `backend/tools/ind_money_auth.py`, `backend/portfolio/connectors/ind_money.py`, `backend/api/main.py`
- **Build:**
  - `_Auth` stops being a module singleton → `AuthStore.for_user(user_id, source)`,
    hydrated from `broker_links`. `_load/_persist/_invalidate` read/write that
    row, not `.ind_money_token.json`. The refresh/expiry logic in
    `status_verified()` and `_refresh_token()` is sound — carry it over unchanged.
  - Per-user `asyncio.Lock` (keyed dict) so one user's refresh serialises without
    blocking others.
  - **Bind `user_id` into the OAuth `state`, not a cookie.** The backend
    (`*.hf.space`) is a different site from the frontend, so a cookie at
    `/auth/callback` is third-party and unreliable. Replace the in-memory
    `_PENDING` dict (`ind_money_auth.py:334`) with the `oauth_pending` table:
    `POST /auth/login` (has the JWT) writes `state → user_id`; the callback
    resolves the owner from `state` alone. Single-use + 10-min TTL, which also
    covers CSRF.
  - **Unlink revokes.** Today `logout()` only forgets locally, leaving a live
    token at IND Money. Call the `revocation_endpoint` from the discovery doc
    before deleting the row.
  - **Request both scopes:** `portfolio:read market:read` (`ind_money_auth.py:41`
    requests only the former; both are in `scopes_supported`). The `networth_*`
    tools need `portfolio:read`, market data needs `market:read` — this may also
    be why scan results are thin.
  - Store the registered client id/secret on the link row and reuse on re-link
    (DCR currently runs per login, `ind_money_auth.py:350`) — unless C2 found
    that per-user DCR is not viable, in which case use one pre-registered client.
  - Replace C0's admin-secret gate with real per-user auth.
- **Acceptance:** two users (one real, one via the stub connector) linked
  simultaneously each see only their own link status; unlink revokes upstream
  *then* deletes the row; with `ALPHADESK_SINGLE_TENANT` unset, no env or file
  fallback can authenticate anyone; tests cover the cross-user cases.

### F4 — Per-user application state
- **Branch:** `v2-foundation` (after F3)
- **Owns:** `backend/api/main.py`, `backend/graph/state.py`, `backend/graph/graph.py`
- *(Split out of the original F3, which bundled the auth rewrite, per-user state
  and the checkpointer swap into one card — three separable concerns, three
  separate review surfaces.)*
- **Build:** thread `user_id` through `PortfolioState` → connectors. Move
  `_RUNS` / `_ANALYSES` / `_PAPER_WATCHLIST` (`api/main.py:88`) to the §6 tables
  keyed by user. Ownership checks on `/approve`, `/analysis/{id}`, `/watchlist`.
  Swap `MemorySaver` for a Postgres checkpointer so a paused approval survives
  restart. Demote the research desk to `/lab` with a persistent "simulation —
  not investment advice" label.
- **Acceptance:** user A cannot read or approve user B's run (**404, not 403** —
  don't leak existence); `/analyses` lists only the caller's; a paused approval
  survives a backend restart; the Lab route carries its label on every view.

### A1 — AI overview (multi-agent)
- **Branch:** `feat/ai-overview` (base `main`, after S1 + F4)
- **Owns:** `backend/graph/portfolio_graph.py` (new), `backend/agents/portfolio/` (new), `backend/api/routes/overview.py` (new), frontend overview panel
- **Build:** compute metrics **deterministically in Python first** — Herfindahl
  index, top-N weight, single-holding %, sector drift, week-over-week delta from
  snapshots, XIRR *if C2 confirmed the inputs exist*. Then fan out parallel
  specialists over those verified numbers: `allocation_critic`,
  `concentration_risk`, `sip_health`, `performance_attribution` → `synthesizer`
  writes the narrative.
  - **Agents may not invent figures.** Every number in the output must trace to a
    computed metric passed in. Return the metric dict so the UI shows the number
    next to the claim.
  - **Descriptive only.** No forward projections in v2 (scenario arithmetic is in
    `BACKLOG.md`), no instrument-level buy/sell on real holdings, ever. See §8.
  - Route every prompt through `redact()` (§8.1). Tracing stays off on this graph.
  - Stream via SSE, reusing the `start`/`update`/`complete` contract in
    `api/main.py::_sse` and `frontend/lib/api.ts::streamAnalyze`.
  - **No human-approval gate and no risk guardrails** — read-and-reason only. Do
    not reuse `interrupt_before`.
- **Acceptance:** every figure in the narrative appears in the returned metric
  dict; a one-holding portfolio produces a sane concentration warning, not a
  crash; a portfolio with no `invested_amount` anywhere produces an overview with
  no performance claims rather than fabricated ones; regenerating does not
  duplicate snapshot rows.

### L1 — Pre-launch bar  ← *the invite gate*
- **Branch:** `feat/prelaunch` (base `main`, after F4)
- **Owns:** `frontend/app/(legal)/`, `backend/api/routes/account.py` (new), rate-limit middleware
- **You become a data fiduciary under the DPDP Act the moment someone else's net
  worth is in your database.** Invite-gating does not exempt you. Three of these
  four are already half-built by earlier cards.
- **Build:**
  - Privacy policy + terms pages. State plainly: what is read from the broker,
    why, where it is stored, retention, that no orders are ever placed, and that
    nothing here is investment advice.
  - **Consent at link time** — a screen before the OAuth redirect naming exactly
    what will be read. Not a checkbox buried in sign-up.
  - **Delete my data** — cascade-delete the user, revoke the broker token
    upstream first, and confirm. This is the one that is painful to retrofit,
    because by then there is live data and no dry run.
  - **Per-user rate cap** on `/analyze` and `/portfolio/overview` (start at 20
    runs/user/day) so an invited user cannot burn the Groq quota.
- **Acceptance:** delete-my-data removes every row for that user across all
  tables and revokes upstream, verified by a test; the cap returns 429 on the
  21st run; the consent screen is unskippable in the link flow; policy pages
  reachable from the footer of every page.

---

## 6. Schema

```
users              id (clerk user_id, PK) | email | created_at

broker_links       id | user_id FK | source | access_token_enc | refresh_token_enc
                   | expires_at | client_id | client_secret_enc | token_url | scope
                   | supports_refresh | status | linked_at | last_refresh_at
                   UNIQUE (user_id, source)

oauth_pending      state (PK) | user_id FK | source | verifier | redirect_uri
                   | client_id | client_secret_enc | token_url | created_at
                   (TTL 10 min, single use)

snapshot_days      id | user_id FK | captured_on DATE | total_value NUMERIC
                   | captured_at   UNIQUE (user_id, captured_on)

snapshot_holdings  id | snapshot_id FK | source | external_id | asset_type | symbol
                   | isin | units | avg_cost | invested_amount NULL
                   | current_price | current_value NUMERIC

snapshot_raw       snapshot_id FK | source | payload JSONB   (pruned at 90 days)

runs               id (uuid, = thread_id) | user_id FK | query | status | action_id | created_at
analyses           run_id FK | user_id FK | payload JSONB | created_at
watchlist          user_id FK | symbol | run_id | query | added_at   PK (user_id, symbol)
```

`broker_links` cascade-deletes with `users`; `snapshot_holdings` and
`snapshot_raw` cascade with `snapshot_days`. `broker_links.source` is what makes
a second connector a row, not a migration.

## 7. API contract — the interface between agents

| Endpoint | Auth | Returns |
|---|---|---|
| `POST /auth/login` | JWT | `{authorization_url}`; writes `oauth_pending` |
| `GET /auth/callback?code&state` | none | HTML page; resolves user from `state` |
| `GET /auth/status` | JWT | caller's link status + `link_health` |
| `POST /auth/logout` | JWT | revokes upstream, deletes link |
| `GET /portfolio/summary` | JWT | net worth, invested, current, P&L, asset-type allocation |
| `GET /portfolio/holdings?asset_type=` | JWT | `Holding` rows + `pnl`, `pnl_pct`, `xirr` (nullable) |
| `GET /portfolio/allocation?asset_type=&by=` | JWT | breakdown buckets + weights |
| `GET /portfolio/history?days=` | JWT | `[{captured_on, total_value}]` from `snapshot_days` |
| `POST /portfolio/overview` | JWT | SSE: `start` / `update` per agent / `complete` with `{narrative, metrics[]}` |
| `POST /internal/snapshot` | `CRON_SECRET` | `{users_captured, skipped, errors}` |
| `DELETE /account` | JWT | revokes upstream, cascade-deletes, confirms |
| `POST /analyze`, `/approve`, `GET /analyses`, `/analysis/{id}`, `/watchlist` | JWT | as today, scoped to caller |

Any endpoint touching another user's data returns **404, not 403** — don't leak
existence. Nullable fields (`pnl`, `xirr`) are genuinely nullable; the frontend
renders "—", never a computed-from-zero number.

## 8. Non-negotiable rules

**1. LLM prompt hygiene.** Portfolio data goes to Groq for the overview. Send
aggregates and instrument symbols only — never account numbers, broker ids,
emails, or the Clerk `user_id`. Add `redact()` in `agents/portfolio/` and route
every prompt through it. Test it.

**2. Tracing.** LangSmith is on by default (`LANGCHAIN_TRACING_V2`) and would
ship users' financial positions to a third party. **On for the research graph
(market data + prompts), off for the portfolio graph (someone's finances)**, set
at graph config level so a future debugging session cannot silently re-enable it.
Asserted by a test in F1.

**3. Product framing — descriptive, not advisory.** Analysis of what *is*
("you are 47% financials; HHI 0.31; your largest holding is 22% of net worth").
No forward forecasts. No instrument-level buy/sell recommendations on real
holdings. The research desk's `buy`/`avoid` output stays a labelled simulation on
a paper watchlist and is **never rendered in the same view as real holdings** —
the moment "you hold too much IT" and "buy X" appear together for a real
portfolio, the framing is broken regardless of any disclaimer. Personalized
recommendations to the public are SEBI IA/RA territory; product shape is the
control, footers are not.

**4. Credentials.** Never log decrypted tokens. Never return a token to the
frontend. `backend/.ind_money_token.json` stays gitignored (single-tenant dev
only). `BROKER` stays unset in every deployed environment.

## 9. Env vars

**Backend (new):** `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `CLERK_JWKS_URL`,
`CLERK_ISSUER`, `CRON_SECRET`, `ALPHADESK_ADMIN_SECRET` (C0, removed at F3),
`ALPHADESK_SINGLE_TENANT` (dev only).
**Frontend (new):** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`.
**GitHub Actions secrets (S1):** `CRON_SECRET`, `BACKEND_URL`.
**Unchanged, must still agree:** `IND_MONEY_AUTH_REDIRECT` = `<backend>/auth/callback`,
`CORS_ALLOW_ORIGINS` ⊇ frontend origin, `NEXT_PUBLIC_API_URL` = backend URL.

## 10. Open questions

- **All four data questions are C2's job** — do not start M1 before that card's
  doc exists. Assumptions about XIRR and `invested_amount` are the ones most
  likely to reshape D1 and A1.
- **HF Spaces free tier** sleeps after 48h idle and cold-starts slowly. C1 helps.
  If snapshot reliability or dashboard first-load is still poor after S1's retry
  logic, the ~$9/mo upgrade (never sleeps) is a legitimate answer — decide with
  data from S1's error counts, not in advance.

**Resolved, kept for the record:** `get_indian_stocks_details` **does** accept a
`segments` parameter (verified against the live tool schema, `indmcp` v1.26.0) —
so the Research agent is leaving analyst ratings and news sentiment on the table.
Not v2 scope; noted in `BACKLOG.md`.
