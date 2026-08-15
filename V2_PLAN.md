# AlphaDesk v2 — Agent Execution Plan

**Product:** a multi-user **portfolio analyzer** for Indian retail investors.
Users sign in, link their IND Money account, and see their net worth, allocation,
holdings and history, plus an AI overview that narrates *verified computed
numbers*. The existing multi-agent stock research desk is demoted to a clearly
labelled **Lab** section — impressive machinery, explicitly a simulation.

**Read first:** `CLAUDE.md` (repo conventions), then this file. `BACKLOG.md` holds
everything deliberately deferred (Groww, statement import, manual holdings,
projections, BYO LLM key, live order placement) with the reason it's parked —
check it before proposing scope. `v2brief.md` (gitignored) is superseded by this
file wherever they disagree.

This plan is the output of two full design reviews (2026-08-14/15). The decisions
in §2 and the rules in §8 were argued and settled. An agent that wants to reverse
one must raise it, not quietly re-decide it. A pre-build verification review
(2026-08-15) re-verified every file/line claim in the cards against the repo and
added: the interim exposure gate (D1/S1), the `local` → Clerk adoption step (F3),
the cascade fix (§6), and the kill criterion (§10).

> ⚠️ **C0 is already publicly disclosed.** Commit `138a7d4` is pushed to the
> public repo and contains the C0 card verbatim — the unauthenticated bypass in
> the currently-deployed app, with file and line numbers. Rewriting history does
> not unpublish it (forks, caches, mirrors). The only remaining mitigation is to
> **ship C0 now**; treat it as the next action, not the first card in a queue.

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
- **`main` stays deployable at every commit.** Vercel tracks `main`; HF is a
  manual `git push space main`. Nothing may land that breaks the live site — see
  the `NEXT_PUBLIC_AUTH_ENABLED` flag in F2.

### Execution model

- **Orchestrator/executor split.** Execution runs in a **dedicated session with
  Fable 5 orchestrating**: it dispatches cards, arbitrates the human gates,
  verifies acceptance, and keeps docs + memory current. It does not write card
  code — with one deliberate exception, the D0 design demos (§5, D0). Cards are
  executed by **Opus 5 subagents**.
- **Kickoff for the execution session:** read `CLAUDE.md`, this plan, and
  `docs/STATUS.md` (the live card ledger), then take the next unfinished card.
  No other context is required by design — if a card cannot be picked up from
  those three files plus `docs/SPECS`/`docs/TESTING`, the docs discipline below
  was violated and fixing that comes first.
- **Serial, one agent per card.** After the resequencing in §4 there is almost no
  real parallelism left, and the two cards that could overlap (D1, S1) both
  consume the module M1 just created. Wall-clock saving is one card; merge risk
  is not worth it.
- **Dispatch vehicle, chosen per card by the orchestrator:** an **ultracode
  workflow** for the cards where a wrong assumption is expensive rather than
  merely annoying — **C2** (findings propagate into three cards), **M1** (the
  model everything downstream consumes), **F3** (the security fix), **L1**
  (deletion correctness) — and a **single Opus agent in a fresh git worktree**
  (Orca-managed where the orca-cli skill is available, plain `git worktree`
  otherwise) for the rest. Either vehicle executes the same card text; the
  choice is about verification depth, not scope.
- **Worktree discipline:** the agent works in its own worktree checked out on
  the card's branch (based off the base the card names, never another feature
  branch), commits from inside that worktree, and the worktree is **removed
  once its branch merges**. No card commits from the orchestrator's main
  checkout. Deploys to the HF Space go via the binary-free `space-deploy`
  snapshot branch (see `docs/STATUS.md`, deploy notes).
- **The orchestrator verifies; the agent's word is not acceptance.** After an
  agent reports done, the orchestrator re-runs the card's acceptance criteria
  itself — commands actually run, outputs actually read — before the branch
  merges. Frontend-visible criteria are verified visually (see "Visual
  verification" below), not inferred from a green build.
- **Review between cards, not after all of them.** C2 and D0 have explicit human
  gates; every other card ends with its acceptance criteria run and read.
- The `owns` lists still matter under serial execution — their job is now telling
  each agent where the boundary is so it doesn't wander into files a later card
  will rewrite.

### Documentation discipline — every card, no exceptions

- Every card updates `docs/` **in the same branch as its code**:
  `docs/SPECS/<card>.md` (what was built, the contract it exposes, decisions
  made along the way) and `docs/TESTING/<card>.md` (how to run its tests, what
  they cover, and how to verify by hand). `docs/README.md` describes the
  layout; the orchestrator updates `docs/STATUS.md` at every card completion
  and gate.
- The bar: an agent in a **fresh session with zero conversation history** can
  pick up, debug, extend, and test the card's work from `docs/` + this plan
  alone. If understanding the work requires the chat transcript, the docs are
  incomplete and the card is not done.
- **Testing is per feature.** Each card ships tests alongside its code (pytest
  from F1 onward; frontend checks per card) and documents how to run them. A
  card with passing but undocumented tests is not done.

### Visual verification

Frontend acceptance criteria phrased as "renders", "shows", "banner appears",
or "no horizontal scroll at 375px" are verified **by looking at pixels**, not
by `npm run build` exiting 0. Drive the running app and screenshot the actual
states using the **computer-use** skill or **Stagehand** (Playwright
alternative — https://docs.stagehand.dev/v4/first-steps/introduction),
whichever fits the check. Applies to D0's demos, D1's dashboard states, S1's
staleness banner, U1's routes and demo banner, and L1's consent screen.

## 1. Scope

**In (v2):** platform sign-in (Clerk, waitlist-gated) · per-user IND Money
linking · normalized portfolio model with per-source connectors · net-worth
dashboard · daily snapshot history + trend chart · public demo mode on sample
data · multi-agent AI overview over computed metrics · the research desk, demoted
to Lab, now per-user · pre-launch privacy bar.

**Out — see `BACKLOG.md` for each:** Groww connector · broker statement/CAS
import · manual/user-added holdings and FDs · portfolio projection · goal
tracking · drift alerts · tax-lot view · BYO LLM key · third-party error tracking
· MF screener · US stocks · liabilities/EMI · options analytics · worldmonitor ·
portfolio-aware research · live order placement.

Do not build these. Do leave the connector interface and tool wrappers
extensible so they slot in without a refactor.

## 2. Locked decisions

| Area | Decision |
|---|---|
| Audience | **Public URL, waitlist-gated.** Clerk Waitlist mode; you approve from the dashboard. Open sign-up is a later switch, not a launch requirement. |
| Identity | **Clerk**. Next.js SDK + FastAPI verify via `clerk-backend-api` (networkless RS256/JWKS). Not IND Money — its OAuth is not OIDC (no `userinfo_endpoint`, no `id_token`), so it has no stable subject and can only be a *linked credential*. |
| DB | **Postgres (Neon)** + SQLModel + Alembic. Required: HF Spaces disk is ephemeral. |
| Data model | **One normalized `Holding` model; every source is a connector that maps into it.** Never store a vendor payload shape as the app's model. |
| Holding identity | Keyed on `(source, external_id)`. **No cross-source auto-merge** — display groups by instrument and *asks* before combining. A silently wrong net worth is the one error a user cannot catch. |
| Currency | **INR-only in v2, asserted not assumed.** `Holding.currency` exists from day one; a connector that yields anything but `INR` raises. Multi-currency is a card, not a field. |
| Valuation | Computed where a formula or price exists; user-entered only as fallback, always carrying a visible `as_of` marker. |
| Secrets at rest | Broker refresh tokens encrypted (Fernet, `TOKEN_ENCRYPTION_KEY`). Never returned to the frontend. |
| History | Daily snapshot per linked user: **normalized rows + totals**, raw payload retained 90 days for forensics. MCP is point-in-time only. |
| Snapshot meaning | **Net worth at Indian market close, all sources settled.** Captured ~23:45 IST after MF NAVs publish; `captured_on` is IST-derived. |
| Snapshot capture | **GitHub Actions** scheduled workflow, next to the existing `keepalive.yml` (not Vercel Cron — Hobby caps at one run/day and cannot retry). Idempotent per `(user_id, captured_on)`; retries; staleness surfaced in the UI. |
| Lab persistence | **Runs and analyses are ephemeral** (in-memory, keyed by `user_id`); `MemorySaver` stays. **The paper watchlist persists in Postgres**, denormalized so a row keeps its meaning after the run is gone. |
| LLM routing | Existing four Lab agents stay on **Groq** at their current tiers, untouched. New portfolio agents use **OpenAI** via an explicit `provider=` argument on `get_chat_llm`. `OPENAI_BASE_URL` / `OPENAI_COMPATIBLE_MODEL` stay **unset**. |
| Demo | Public `/demo` renders the full dashboard from stub fixtures with a **pre-generated** narrative artifact. **No LLM call at request time, ever.** |
| AI overview | Multi-agent LangGraph fan-out → synthesizer. **Numbers are computed in Python; agents narrate verified metrics and must not invent figures.** The dashboard must render completely when the LLM is unavailable. |
| Product framing | **Descriptive analytics only.** No forward forecasts, no instrument-level advice on real holdings. See §8.3. |
| Research desk | Demoted to a labelled **Lab / Simulation** area. Never fused with the portfolio view. |
| Tracing | LangSmith **on for the research graph, off for the portfolio graph**, set at graph config level — not by env var. |
| Observability | **Structured logging only.** No third-party error tracking in v2 — with fewer than ten invited users you can ask them directly, and Sentry would become a third subprocessor handling financial request context. |
| RAG | **Unplugged, not deleted.** `data/nse_docs` is empty, so it has been inert in production regardless. See C1. |
| Charts | Recharts (not currently a dependency — added in D1). D0's design choice may refine the treatment; shadcn/ui charts are Recharts-based, so the library survives either way. |
| Dashboard design | **Chosen at the D0 gate** from 4–5 complete Fable-built demos (shadcn/ui, Bloomberg-terminal, plus 2–3 distinct others). Until a demo is chosen and recorded (DECISION.md + §2 + memory), **no real dashboard frontend is written.** |

## 3. Architecture spine

Everything downstream of a broker reads **one shape**:

```python
Holding:
  source: str            # "ind_money" | "stub" | future connectors
  external_id: str       # stable id within that source; (source, external_id) is identity
  asset_type: AssetType  # IND_STOCK | MF | US_STOCK | BOND | EPF | NPS | SA | FD | ...
  symbol: str | None     # display/grouping key; may be None for opaque assets
  isin: str | None
  units: Decimal | None
  avg_cost: Decimal | None
  invested_amount: Decimal | None   # often missing/0 for linked brokers — see C2
  current_price: Decimal | None
  current_value: Decimal            # the only always-required numeric field
  currency: str                     # "INR" in v2; anything else raises
  as_of: datetime
  raw: dict                         # source payload, for forensics
```

A **connector** implements: `fetch_snapshot(user_id)`, `fetch_holdings(user_id, asset_type)`,
`fetch_allocation(user_id, asset_type, by)`, `fetch_sips(user_id)`, plus
`link_health(user_id)` reporting `linked | expiring | needs_relink | revoked`.
`link_health` must not assume the source can refresh — a future connector may be
authorization-code-only (see `BACKLOG.md`, Groww).

The dashboard, allocation math, snapshots and AI metrics consume `Holding` and
know nothing about IND Money. **No vendor field name appears above the connector
boundary.**

**Why `currency` when v2 is INR-only:** `US_STOCK` is in the asset-type enum, and
IND Money reports US equity for Indian users. Without the field, `sum(current_value)`
silently adds dollars to rupees and every number in the product — net worth,
weights, HHI, the narrative — is quietly wrong for anyone holding US stocks. A
raise converts an invisible wrong-number bug into a visible unimplemented feature.

## 4. Sequencing

```
C0 mitigate ─→ C1 unplug RAG ─→ F1 db+migrations ─→ C2 data spike
                                                      ‖  ← HUMAN GATE (§5, C2)
                                                      ↓
                                                    M1 model + connectors
                                                      ↓
                                                    D0 design bake-off
                                                      ‖  ← HUMAN GATE (design)
                                                      ↓
                                                    D1 dashboard ─→ S1 snapshots
                                                                      ↓
                                                    F2 clerk ─→ F3 linking ─→ F4 per-user state
                                                                                ↓
                                                                              A1 ai overview
                                                                                ↓
                                                                              U1 app shell
                                                                                ↓
                                                                              L1 pre-launch bar
                                                                                ‖
                                                                        ══ INVITE GATE ══
```

**Why this order, not foundation-first.** The original plan front-loaded F1–F3 on
the urgency of the live security hole. C0 removes that urgency in an afternoon,
and waitlist-gating removes it structurally. The normalized model (M1) must be
designed against *real payloads*, which is easiest while you are the only user.
F2–F4 are prerequisites of **inviting people**, not of building — so they land
immediately before the invite gate, and nothing goes out before L1.

The `user_id`-from-day-one rule in §0 is what keeps this honest. Without it, this
ordering is the refactor trap it looks like.

**Nothing is invited until F2, F3, F4, U1 and L1 are all merged to `main`.**

---

## 5. Task cards

### C0 — Close the live hole (do this first)
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
- **Known hole C0 does not close:** anonymous `POST /analyze` still burns Groq
  credits on the operator's key (it is 409-gated on IND Money being connected,
  nothing more). Accepted until F2 — noted so nobody mistakes C0 for full lockdown.
- **Then, and only then,** this plan file may be committed publicly.

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
- **Why (honestly):** image size and build time, not cold starts —
  `.github/workflows/keepalive.yml` pings the Space every 6h against a 48h sleep
  threshold, so it rarely sleeps. Re-enabling later is `pip install chromadb`
  plus actually adding PDFs.
- **Acceptance:** image builds without `build-essential`/`chromadb`; the pipeline
  runs end to end and the Analyst produces a report with empty RAG context; no
  Python diff.

### F1 — Persistence layer
- **Branch:** `v2-foundation` (base `main`)
- **Owns:** `backend/db/` (new), `backend/alembic/`, `requirements.txt`, `backend/.env.example`
- **Build:** SQLModel models + Alembic for the identity/link tables only —
  `users`, `broker_links`, `oauth_pending`. **M1 and S1 add their own tables in
  their own migrations**, after C2 has fixed the `Holding` shape; the plan's own
  argument (design the model against real payloads) applies to
  `snapshot_holdings`'s columns too, so F1 must not freeze them before the C2
  gate. `db/crypto.py` with Fernet `encrypt()/decrypt()` keyed on
  `TOKEN_ENCRYPTION_KEY`. Async session dependency. Wire **pytest**
  (`backend/tests/`) — every later card ships tests.
- **Also:** ship a `portfolio_runnable_config()` helper that disables LangSmith
  tracing at config level (a `RunnableConfig`, **not** an env var — env vars get
  flipped on by a future you debugging prod) and assert in a test that it does.
  The portfolio graph itself does not exist until A1; **A1's acceptance asserts
  the graph is invoked with this helper.** §8.2 is a rule, and rules that live
  only in prose do not fail builds.
- **Acceptance:** `alembic upgrade head` builds a clean DB; `pytest` green;
  round-trip test proves an encrypted value never appears in plaintext in the DB;
  a test asserts `portfolio_runnable_config()` disables tracing. No behaviour
  change to existing endpoints.

### C2 — Data spike  ← *human gate; blocks M1, D1, A1*
- **Branch:** `spike/ind-money-portfolio` (base `main`, after F1)
- **Owns:** `backend/tests/fixtures/` (new), `docs/ind_money_payloads.md` (new)
- **Nobody has ever seen a `networth_*` response.** Three downstream commitments
  rest on unverified shapes — all cheap to check, expensive to guess wrong.
- **Build:** against your own linked account, call `networth_snapshot()`,
  `networth_holdings(asset_type)` for every type, `networth_allocation_breakdown`
  for each `breakdown_by`, `indian_stocks_sips()`, `mf_sips()`. Document in
  `docs/ind_money_payloads.md`:
  1. **Is per-row XIRR in the payload?** If not, D1's holdings table and A1's
     XIRR metric are dead as specified — XIRR needs dated cashflows a
     point-in-time call may not carry. Report the alternative, or its absence.
  2. **How often is `invested_amount` missing or 0?** Per source/broker.
  3. **Does `networth_snapshot` return a usable total** to store as `NUMERIC`?
  4. **Is any value non-INR?** (`US_STOCK` especially — currency field, or not?)
  5. **Does dynamic client registration tolerate one client per user?** DCR runs
     per-login today (`ind_money_auth.py:350`), so probably — but if `/register`
     is rate-limited or binds clients to an account, F3 needs one pre-registered
     client with per-user tokens instead.
- **Fixtures are synthetic.** Capture real payloads locally; then hand-rewrite
  every value to fake-but-shaped data before committing. **The repo is public** —
  "redacted" real holdings are still your net worth in git history forever.
  Synthetic fixtures are also *better tests*: craft the missing-`invested_amount`,
  single-holding, and zero-value edge cases deliberately.
- **Acceptance:** the doc answers all five questions explicitly, including "no"
  answers, and ends with a **written go/no-go** naming any card whose scope
  changes. Committed fixtures contain no real position. **M1 does not start until
  a human has read the doc and confirmed the model shape** — this is the one
  point where a wrong assumption propagates into three cards.

### M1 — Normalized model + connectors
- **Branch:** `feat/portfolio-model` (base `main`, after the C2 gate)
- **Owns:** `backend/portfolio/` (new: `models.py`, `connectors/base.py`, `connectors/ind_money.py`, `connectors/stub.py`), `backend/tests/fixtures/demo/`, tests
- **Build:** the `Holding` model and connector interface from §3. The IND Money
  connector reuses the `_call_mcp_tool` + `_unwrap` pattern from
  `tools/ind_money.py` (responses arrive as `{"result": "<stringified JSON>"}`)
  and maps vendor fields onto `Holding`. `asset_type` enum: `IND_STOCK, MF,
  US_STOCK, BOND, EPF, NPS, SA, FD, CRYPTO, INSURANCE, VEHICLE, RE, RD, AIF, PMS,
  PPF`; `breakdown_by`: `assets, sector, market_cap`.
- **The stub connector is not test scaffolding.** It proves the interface has two
  implementations (a real seam, not a rename), makes F4's cross-user isolation
  testable in CI forever, and backs the public `/demo` route built in U1.
- **Degrade honestly:** a missing or 0 `invested_amount` yields `None` P&L and
  `None` XIRR — never a bogus -100%. A non-`INR` `currency` raises. Assert both.
- **Acceptance:** every connector method returns typed `Holding`s against the C2
  fixtures; stub and IND Money connectors are interchangeable behind the
  interface; missing `invested_amount` yields `None`, not a wrong number; a
  non-INR value raises rather than being summed; no vendor field name appears
  outside `connectors/`.

### D0 — Dashboard design bake-off  ← *human gate; blocks D1*
- **Branch:** none — demos are throwaway artifacts, not product code.
- **Owns:** `docs/design/` (new)
- **Trigger:** runs as soon as there is real portfolio data to render — a
  captured real snapshot (the operator's live IND Money link, re-established
  2026-08-15 via the admin-secret login) or the M1 stub fixtures — and **before
  any real dashboard frontend is written**. Moving to frontend work without
  passing this gate is a protocol violation, not a shortcut.
- **Build:** **4–5 complete, distinct design demos** of the portfolio
  dashboard, each a full static page over the *same* fixture data, covering the
  whole D1 surface: net-worth header, allocation charts, sortable holdings
  table, trend line, and the empty/null states ("—", not "-100%"). Required
  directions: at least one **shadcn/ui** treatment and one **Bloomberg-terminal**
  treatment (the current `pill-*`/`eyebrow` aesthetic, evolved); the remaining
  2–3 must be genuinely different directions, not recolors of each other.
  Self-contained HTML files in `docs/design/` — no build step, open in a
  browser — each screenshotted for the record.
- **Who builds them:** the **Fable orchestrator itself, at high/xhigh effort as
  the page demands** — not delegated to Opus. Load the design skills first:
  `frontend-design` if present, `artifact-design`, `dataviz` before any chart,
  `shadcn` for the shadcn variant. This is the one place the orchestrator
  writes code: design judgment is the point of the card, and fanning out would
  produce five mediocre pages instead of five deliberate ones.
- **The human picks one.** Hard gate, same force as C2's.
- **On choice, before D1 starts:**
  1. Record the locked design in `docs/design/DECISION.md` — component library,
     layout grid, chart treatment, spacing/type/color tokens, and per-component
     notes complete enough that an Opus subagent implements D1 and U1 **end to
     end with zero visual decisions left to make**.
  2. Add the choice to §2 of this plan (the "Dashboard design" row).
  3. Write it to the orchestrator's **persistent memory**, so any future
     session inherits the decision without re-reading the bake-off.
  4. Move the losing demos to `docs/design/rejected/` — they stay in the repo;
     the record of what was considered is cheap and useful.
- **Acceptance:** 4–5 demos exist and render from fixture data (verified
  visually — computer-use or Stagehand screenshots); a choice is recorded in
  all three places (DECISION.md, §2, memory); the D1 card can be executed by an
  agent that has seen only the docs.

### D1 — Portfolio dashboard
- **Branch:** `feat/portfolio-dashboard` (base `main`, after the D0 gate)
- **Owns:** `frontend/app/portfolio/`, `frontend/components/portfolio/`, `backend/api/routes/portfolio.py` (new)
- **Build:** `GET /portfolio/summary|holdings|allocation|history` (§7), then the
  page: net-worth header (invested vs current, absolute + %), allocation charts
  (Recharts — asset type, sector, market cap), sortable holdings table with
  per-row P&L% (and XIRR **only if C2 confirmed it exists**), net-worth trend
  line from snapshots. **Visual language: the design locked at D0**
  (`docs/design/DECISION.md`) — implement it faithfully, no per-component
  improvisation; anything DECISION.md leaves ambiguous goes back to the
  orchestrator, not into the code.
- Build every component so it renders from a `Holding[]` — it will be fed by both
  the real connector and the stub in U1's `/demo`.
- **Interim exposure gate:** until F3 lands, every `/portfolio/*` route requires
  the C0 `ALPHADESK_ADMIN_SECRET` header. These endpoints serve the operator's
  **real portfolio** under `user_id="local"`, and §7's JWT does not exist until
  F2 — without this gate, merging D1 and deploying (which S1 requires) publishes
  your net worth on the public backend URL. F3 replaces the gate with real
  per-user auth. The frontend attaches the header from a local-only env var.
- **Acceptance:** loads for a linked user; unlinked user sees the Connect gate,
  not an error; empty/zero-holding asset types render as empty states; a holding
  with no `invested_amount` renders "—" not "-100%"; **`/portfolio/*` without the
  admin header → 401**; `npx tsc --noEmit` and `npm run build` clean; no
  horizontal page scroll at 375px.

### S1 — Snapshots + capture job
- **Branch:** `feat/portfolio-snapshots` (base `main`, after D1)
- **Owns:** `backend/services/snapshots.py` (new), `backend/api/routes/internal.py` (new), `.github/workflows/snapshot.yml` (new), staleness banner in `frontend/components/portfolio/`
- **A missed snapshot can never be backfilled.** The MCP is point-in-time; there
  is no "what was my net worth last Tuesday". A failed run does not delay data,
  it destroys it. Postgres makes stored rows durable; it cannot create a row for
  a day the job never ran. Design for **acquisition** failure, not storage failure.
- **Build:** for every linked user, capture normalized `Holding` rows +
  `total_value` into `snapshot_days` / `snapshot_holdings`, and the raw payload
  into `snapshot_raw`. Trigger: `POST /internal/snapshot` guarded by a
  `CRON_SECRET` header, called by a **GitHub Actions** scheduled workflow modelled
  on the existing `keepalive.yml` — wake the Space, poll until ready, trigger,
  **retry with backoff**.
- **Timing:** primary run **~23:45 IST**, after mutual-fund NAVs publish (~23:00)
  — an earlier capture would pair today's equity prices with yesterday's NAVs and
  produce a portfolio that never existed at any instant. **Attribution is
  calendar-day with an explicit cutoff, not trading-day:** any run before
  **06:00 IST** attributes to the **previous** IST calendar day. This one rule
  covers both the ~01:00 IST retry *and* a late primary — GitHub cron is
  best-effort (`keepalive.yml` says so itself; 23:45 IST is 18:15 UTC, and a
  20-minute delay crosses midnight IST). Calendar-day semantics also delete the
  NSE-holiday-calendar dependency: weekend/holiday captures are idempotent and
  harmless. `captured_on` is derived through one IST helper used everywhere;
  never from server-local or UTC "today". Idempotency per
  `(user_id, captured_on)` makes the retry a free no-op.
- **Third net:** opportunistic capture when a user loads the dashboard and the
  most recent trading day's row is missing.
- **Daily USD/INR rate** (operator decision, 2026-08-15): each capture run
  also fetches `https://api.frankfurter.dev/v2/rate/USD/INR` (free, keyless,
  ECB reference; shape `{date, base, quote, rate}`; publishes once per working
  day ~20:30 IST, so the 23:45 IST run gets same-day data) and stores it as
  `snapshot_days.usd_inr_rate NUMERIC` for later INR/USD conversion math
  (US-stock exposure display, not re-summing — holdings stay vendor-INR).
  Weekend/holiday runs store the most recent published rate. A failed FX
  fetch must NOT fail the snapshot — store NULL and log.
- **Staleness is visible, not assumed.** `keepalive.yml` documents that GitHub
  disables scheduled workflows after 60 days of repo inactivity — so the job can
  silently stop, along with keepalive. The dashboard shows *"history paused — last
  captured N days ago"* derived from `max(snapshot_days.captured_at)` for that
  user. This catches an expired secret, a renamed Space, or a failing deploy too,
  not just the one cause.
- **Retention:** normalized rows forever; `snapshot_raw` pruned at 90 days.
- Skip and log users whose link is expired — never let one user's failure abort
  the batch.
- **This card deploys to the public Space before F3** — the GitHub Actions cron
  needs the live URL. D1's interim exposure gate (admin header on `/portfolio/*`)
  must already be in place; verify it is before pushing to the Space.
- **Acceptance:** two runs on the same day produce one `snapshot_days` row per
  user; a simulated 01:00 IST run attributes to the previous calendar day and a
  23:45 IST run to the current one (cutoff tested on both sides); a user with a
  revoked link is skipped without failing the batch; wrong/absent secret → 401; a
  simulated 502 on the first attempt still produces the row via retry; the banner
  appears when the newest capture is older than expected; the prune job deletes
  raw payloads older than 90 days and leaves normalized rows intact.

### F2 — Clerk identity
- **Branch:** `v2-foundation` (after S1)
- **Owns:** `backend/api/deps.py` (new), `frontend/app/layout.tsx`, `frontend/middleware.ts`, `frontend/lib/api.ts`, `frontend/components/TopBar.tsx`
- **Build:** `current_user()` FastAPI dependency verifying Clerk JWTs, yielding
  `user_id`; lazily upsert the `users` row on first sight. `<ClerkProvider>`,
  middleware, sign-in page, `<UserButton>` in TopBar. Every `lib/api.ts` fetch
  attaches the JWT. Configure Clerk in **Waitlist mode** — the `<Waitlist />`
  component lets a stranger register interest and you approve from the dashboard.
- **`main` must stay shippable:** put Clerk behind `NEXT_PUBLIC_AUTH_ENABLED`.
  With it off, the live site behaves exactly as it does today; you flip it once
  L1 lands. Without this flag the public site sits behind a login wall nobody has
  an invite for, through F3, F4, A1, U1 and L1.
- **Also:** rename v1's `useAuth` → `useIndMoney` (`components/AuthProvider.tsx`)
  — it collides with Clerk's `useAuth`, and the new name is accurate: it means
  "has linked a broker", not "is signed in".
- **Verify before building:** the Clerk specifics in this card (`clerk-backend-api`
  package name, networkless RS256/JWKS verification, Waitlist mode) are Likely,
  not repo-verified — check them against current Clerk docs first and flag any
  drift rather than adapting silently.
- **Acceptance:** with the flag on, unauthenticated requests to protected
  endpoints → 401 and authenticated → 200 with a resolved `user_id`; a
  non-approved email lands on the waitlist rather than signing up; with the flag
  off the site is unchanged; `npx tsc --noEmit` and `npm run build` clean.

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
    per-user DCR is not viable, in which case use one pre-registered client.
  - Replace C0's admin-secret gate with real per-user auth — including D1's
    interim gate on `/portfolio/*`.
  - **Adopt pre-F3 single-tenant data.** Everything D1/S1 accumulated is keyed
    `user_id="local"` — including snapshot history, which §5-S1 establishes can
    never be backfilled. One-off migration mapping the `"local"` rows
    (`snapshot_days` + children, `broker_links`) to the operator's Clerk user id,
    run once when the operator first signs in. Without this, F2 landing orphans
    the very history S1 exists to protect.
- **Acceptance:** two users (one real, one via the stub connector) linked
  simultaneously each see only their own link status; unlink revokes upstream
  *then* deletes the row; with `ALPHADESK_SINGLE_TENANT` unset, no env or file
  fallback can authenticate anyone; the operator's pre-F3 snapshot history is
  intact and visible after Clerk sign-in; tests cover the cross-user cases.

### F4 — Per-user Lab state
- **Branch:** `v2-foundation` (after F3)
- **Owns:** `backend/api/main.py`, `backend/graph/state.py`, `frontend/app/lab/`
- *(Split out of the original F3, which bundled the auth rewrite, per-user state
  and a checkpointer swap into one card — three separable concerns, three review
  surfaces. The split is safe because nobody is invited until L1.)*
- **This card is small by design.** The Lab is a labelled simulation, so it does
  not get a persistence layer:
  - Thread `user_id` through `PortfolioState`.
  - **Key `_RUNS` / `_ANALYSES` / `_ACTIONS` by `user_id`** and keep them in
    memory. **Keep `MemorySaver`** — no Postgres checkpointer, no `runs` or
    `analyses` tables. Label it in the UI: *"Lab runs are live simulations and
    aren't saved."* A paused approval lost on restart is an accepted trade.
  - **The paper watchlist does persist** — Postgres, per user, across logins, and
    **denormalized**: each row stores the full decision record (symbol, company,
    thesis, confidence, action, risk verdict, originating query, `added_at`) plus
    `run_id` as an **opaque non-FK reference that may no longer resolve**. A
    watchlist entry is a record of a decision at a point in time; it must not
    depend on a run that is gone, and should not silently change if one is
    recomputed. "View original run" degrades to *"this run is no longer
    available"*.
  - Ownership checks on `/approve`, `/analysis/{id}`, `/watchlist`.
  - Move the desk to `/lab` with a persistent "simulation — not investment
    advice" label on every view.
- **Acceptance:** user A cannot read or approve user B's run (**404, not 403** —
  don't leak existence); `/analyses` lists only the caller's; the watchlist
  survives a backend restart with its thesis intact and its run link degraded
  gracefully; the Lab label is present on every view.

### A1 — AI overview (multi-agent)
- **Branch:** `feat/ai-overview` (base `main`, after F4)
- **Owns:** `backend/graph/portfolio_graph.py` (new), `backend/agents/portfolio/` (new), `backend/agents/llm.py`, `backend/api/routes/overview.py` (new), frontend overview panel
- **Build:** compute metrics **deterministically in Python first** — Herfindahl
  index, top-N weight, single-holding %, sector drift, week-over-week delta from
  snapshots, XIRR *if C2 confirmed the inputs exist*. Then fan out parallel
  specialists over those verified numbers: `allocation_critic`,
  `concentration_risk`, `sip_health`, `performance_attribution` → `synthesizer`
  writes the narrative.
- **LLM routing lives here.** Extend `get_chat_llm` with an explicit `provider=`
  argument; the portfolio agents pass `provider="openai"`. Leave
  `OPENAI_BASE_URL` / `OPENAI_COMPATIBLE_MODEL` unset so the four Lab agents keep
  running Groq at their current tiers, entirely untouched. Do not refactor them.
- **Agents may not invent figures.** Every number in the output must trace to a
  computed metric passed in. Return the metric dict so the UI shows the number
  next to the claim.
- **Graceful degradation is a requirement, not a nicety.** Metrics are computed
  in Python; only the narrative needs an LLM. When the LLM is unavailable — no
  credits, provider down, rate limited — the dashboard renders **completely**,
  every computed number intact, with the narrative panel showing "AI overview
  unavailable". Never an error page.
- **Spend controls:** a hard budget limit set **provider-side** in the OpenAI
  dashboard (the one control an app bug cannot bypass), plus an app-side global
  daily ceiling, plus a low per-user cap. Testing uses credits conservatively.
- **Descriptive only.** No forward projections (scenario arithmetic is in
  `BACKLOG.md`), no instrument-level buy/sell on real holdings, ever. See §8.3.
- Route every prompt through `redact()` (§8.1). Tracing stays off on this graph.
- Stream via SSE, reusing the `start`/`update`/`complete` contract in
  `api/main.py::_sse` and `frontend/lib/api.ts::streamAnalyze`.
- **No human-approval gate and no risk guardrails** — read-and-reason only. Do
  not reuse `interrupt_before`.
- **Also produce the demo artifact:** run the overview once against the M1 stub
  fixtures and commit the resulting narrative + metric dict to
  `backend/tests/fixtures/demo/`. Document regenerating it as a manual step
  whenever the fixtures or prompts change. U1 serves it statically.
- **Acceptance:** every figure in the narrative appears in the returned metric
  dict; a one-holding portfolio produces a sane concentration warning, not a
  crash; a portfolio with no `invested_amount` anywhere produces an overview with
  no performance claims rather than fabricated ones; **with the LLM key removed,
  the dashboard still renders every computed number**; the demo artifact exists
  and matches the stub fixtures.

### U1 — App shell & information architecture
- **Branch:** `feat/app-shell` (base `main`, after A1)
- **Owns:** `frontend/app/page.tsx`, `frontend/app/demo/`, `frontend/app/(marketing)/`, nav
- **Why this card exists:** the app has exactly two routes today (`/` and
  `/a/[id]`) and v2 needs eight. Without one owner, F2, D1 and F4 would each
  half-edit `page.tsx` — the collision the `owns` protocol exists to prevent.
  It lands after F2 (which keeps `layout.tsx` and `TopBar.tsx`) and after A1
  (whose demo artifact `/demo` serves).
- **Build:**

  | Route | Who sees it | Content |
  |---|---|---|
  | `/` | anonymous | landing — what it is, CTA to `/demo` and the waitlist |
  | `/` | signed in + linked | redirect → `/portfolio` |
  | `/` | signed in, unlinked | Connect gate |
  | `/demo` | public, no sign-in | full dashboard from stub fixtures + the pre-generated narrative |
  | `/portfolio` | linked | D1's dashboard |
  | `/lab`, `/lab/a/[id]` | linked | research desk, labelled simulation |
  | `/sign-in`, `/waitlist` | public | Clerk components |
  | `/privacy`, `/terms` | public | L1 |

- **`/demo` makes no LLM call, ever** — it reads A1's committed artifact. A public
  route that generates narratives would let anonymous strangers burn credits, the
  one surface a per-user cap cannot cover. It also makes the demo instant instead
  of waiting on an SSE stream.
- The sample-data banner must be **unmissable and persistent** — a screenshot of
  fake net worth without context is genuinely misleading.
- **Why demo mode matters:** without it, nobody lacking an IND Money account can
  see the product at all — which is approximately everyone you would show it to.
- **Acceptance:** an anonymous visitor reaches `/demo` and sees a fully rendered
  dashboard with the banner on every scroll position; no network call from
  `/demo` hits an LLM; each signed-in state lands on the right route; `npx tsc
  --noEmit` and `npm run build` clean.

### L1 — Pre-launch bar  ← *the invite gate*
- **Branch:** `feat/prelaunch` (base `main`, after U1)
- **Owns:** `frontend/app/(legal)/`, `backend/api/routes/account.py` (new), rate-limit middleware
- **You become a data fiduciary under the DPDP Act the moment someone else's net
  worth is in your database.** Waitlist-gating does not exempt you.
- **Build:**
  - Privacy policy + terms. State plainly: what is read from the broker, why,
    where it is stored, retention, that no orders are ever placed, and that
    nothing here is investment advice. **Name the subprocessors: Groq (Lab
    prompts) and OpenAI (portfolio narration, not used for training by default,
    up to 30-day abuse-monitoring retention).**
  - **Consent at link time** — a screen before the OAuth redirect naming exactly
    what will be read. Not a checkbox buried in sign-up.
  - **Delete my data** — cascade-delete the user, revoke the broker token
    upstream first, and confirm. This is the one that is painful to retrofit,
    because by then there is live data and no dry run.
  - Enforce the global daily ceiling and per-user cap from A1.
  - Flip `NEXT_PUBLIC_AUTH_ENABLED` on.
- **Acceptance:** delete-my-data removes every row for that user across all
  tables and revokes upstream, verified by a test; the cap returns 429 past the
  ceiling; the consent screen is unskippable in the link flow; policy pages
  reachable from the footer of every page and name both LLM providers.

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

snapshot_days      id | user_id FK | captured_on DATE (IST-derived) | total_value NUMERIC
                   | currency | usd_inr_rate NUMERIC NULL | captured_at
                   UNIQUE (user_id, captured_on)

snapshot_holdings  id | snapshot_id FK | source | external_id | asset_type | symbol
                   | isin | units | avg_cost | invested_amount NULL
                   | current_price | current_value NUMERIC | currency

snapshot_raw       snapshot_id FK | source | payload JSONB   (pruned at 90 days)

watchlist          user_id FK | symbol | company | thesis | confidence | action
                   | risk_verdict | query | run_id (opaque, non-FK) | added_at
                   PK (user_id, symbol)
```

**Every table with a `user_id` FK cascade-deletes with `users`** —
`broker_links`, `oauth_pending`, `snapshot_days`, `watchlist`; `snapshot_holdings`
and `snapshot_raw` cascade with `snapshot_days`. (Stated exhaustively because
L1's delete-my-data depends on it: an unstated cascade on `snapshot_days` either
fails on FK or leaves the user's entire net-worth history behind.)
`broker_links.source` is what makes a second connector a row, not a migration.

**No `runs` or `analyses` tables** — Lab runs are ephemeral by decision (§2), held
in memory keyed by `user_id`. Staleness for S1's banner is derived from
`max(snapshot_days.captured_at)` per user; no extra column needed.

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
| `GET /portfolio/history?days=` | JWT | `[{captured_on, total_value}]` + `last_captured_at` |
| `POST /portfolio/overview` | JWT | SSE: `start` / `update` per agent / `complete` with `{narrative, metrics[]}` |
| `POST /internal/snapshot` | `CRON_SECRET` | `{users_captured, skipped, errors}` |
| `DELETE /account` | JWT | revokes upstream, cascade-deletes, confirms |
| `POST /analyze`, `/approve`, `GET /analyses`, `/analysis/{id}`, `/watchlist` | JWT | as today, scoped to caller |

Any endpoint touching another user's data returns **404, not 403** — don't leak
existence. Nullable fields (`pnl`, `xirr`) are genuinely nullable; the frontend
renders "—", never a computed-from-zero number. `/demo` is served entirely from
committed fixtures and calls none of these.

## 8. Non-negotiable rules

**1. LLM prompt hygiene.** Portfolio data goes to OpenAI for the overview. Send
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

**5. The repo is public.** No real portfolio data in fixtures, tests, docs,
screenshots or commit messages — ever, in any branch. Git history is forever.

## 9. Env vars

**Backend (new):** `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `CLERK_JWKS_URL`,
`CLERK_ISSUER`, `CRON_SECRET`, `OPENAI_API_KEY`, `ALPHADESK_ADMIN_SECRET` (C0,
removed at F3), `ALPHADESK_SINGLE_TENANT` (dev only).
**Backend (must stay unset):** `OPENAI_BASE_URL`, `OPENAI_COMPATIBLE_MODEL` —
setting either routes *all* agents, including the Lab's, through one model and
collapses their cheap/strong tiering.
**Frontend (new):** `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`,
`NEXT_PUBLIC_AUTH_ENABLED`.
**GitHub Actions (S1):** secret `CRON_SECRET`; variable `BACKEND_URL` (already
used by `keepalive.yml`).
**Unchanged, must still agree:** `IND_MONEY_AUTH_REDIRECT` = `<backend>/auth/callback`,
`CORS_ALLOW_ORIGINS` ⊇ frontend origin, `NEXT_PUBLIC_API_URL` = backend URL.

## 10. Open questions

- **All five data questions are C2's job**, and C2 is a human gate — do not start
  M1 before someone has read its go/no-go. Assumptions about XIRR,
  `invested_amount` and currency are the ones most likely to reshape D1 and A1.
- **Kill criterion (written 2026-08-15):** if C2 shows `networth_snapshot` /
  `networth_holdings` return no usable per-holding values, then D1, S1 and A1
  *as specified* are dead — stop and re-plan the product around what the MCP
  actually returns. Do not adapt silently; the whole dashboard rests on this one
  unverified assumption.
- **HF Spaces free tier** sleeps after 48h idle; `keepalive.yml` covers that today
  but is itself subject to the 60-day workflow-disable rule. If S1's error counts
  or the staleness banner show real gaps, the ~$9/mo upgrade (never sleeps) is a
  legitimate answer — decide with data, not in advance.

**Resolved, kept for the record:** `get_indian_stocks_details` **does** accept a
`segments` parameter (verified against the live tool schema, `indmcp` v1.26.0) —
so the Research agent is leaving analyst ratings and news sentiment on the table.
Not v2 scope; noted in `BACKLOG.md`.
