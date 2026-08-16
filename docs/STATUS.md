# AlphaDesk v2 — card ledger

Plan of record: [`../V2_PLAN.md`](../V2_PLAN.md). The orchestrator updates this
file at every card completion and gate. Newest facts win; keep entries terse.

**Last updated:** 2026-08-16 (A1 built on `feat/ai-overview` — the multi-agent AI overview: Python-computed metrics, agents narrate by token only, degrades to metrics-only when the LLM is down, `provider=` wins over env so the Lab stays on Groq; awaiting review. Operator: OpenAI provider-side budget cap + clear the stray local `OPENAI_COMPATIBLE_MODEL`, `docs/MORNING.md`)

| Card | Status | Notes |
| --- | --- | --- |
| C0 lockdown | ✅ **done 2026-08-15** | Admin gate on `/auth/login`+`/auth/logout` (`ALPHADESK_ADMIN_SECRET`, fail-closed); ambient credential fallbacks gated behind `ALPHADESK_SINGLE_TENANT` (local only). Verified live on the Space: 9/9 checks (401s, read-only 200s, status unauthenticated). Security review: no findings. |
| C1 slim image | ✅ **done 2026-08-15** | Merge `8d2e8bd`. chromadb/pypdf/text-splitters dropped (rag-only, grep-proven); all 10 direct deps pinned from verified freeze; Dockerfile loses `build-essential`, `COPY data/`, ingest step (image 370MB, builds+boots verified); screenshots PNGs removed from HEAD; README/DEPLOY/CLAUDE RAG claims corrected; docs/SPECS+TESTING/C1.md added. Review: 1 Critical (real run data in TESTING doc) fixed via branch history rewrite pre-merge. **The PNG removal does NOT retire the `space-deploy` dance** — verified 2026-08-15: HF's pre-receive hook scans all pushed history and rejects the historical PNGs; only a `main` history rewrite would fix that, not worth it. |
| F1 persistence | ✅ **done 2026-08-15** | Merged to `main`. Review: 0 Critical, 5 Important + 2 minors — all fixed and re-verified (fix round 1); orchestrator re-ran acceptance on the final tip (43/43, migration idempotent, FK cascades `c`). Three identity tables (`users`, `broker_links`, `oauth_pending`) with **DB-level** `ON DELETE CASCADE`; Fernet crypto on `TOKEN_ENCRYPTION_KEY`; async Alembic (asyncpg only — no second sync driver); pytest wired (43 tests, 6 need Postgres and skip loudly without it); `portfolio_runnable_config()` tracing kill switch, now **pinned + gated at Docker build time**. New env vars: `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`. Runtime deps +6 pinned incl. transitive `langchain-core==1.5.5` (image 370→426MB); test deps split into `requirements-dev.txt`. New `.dockerignore` keeps `backend/.env` + the IND Money token cache out of locally-built images. `git diff main -- backend/api backend/agents backend/graph/graph.py backend/tools` is empty. Verified on local Docker Postgres 16 (`:5433`); still no Neon. Docs: `docs/SPECS/F1.md`, `docs/TESTING/F1.md`. |
| C2 data spike | ✅ **done 2026-08-15, gate passed** | Merged to `main` 2026-08-15 (10-agent workflow + 2 fix rounds; independent audit reproduced every shape/count; leak gate PASS; history rewritten pre-merge to scrub 2 leaked values). 72 live calls captured (15-tool inventory, snapshot, all 16 `asset_type` holdings, full 16×3 breakdown grid, both SIP tools, 2× DCR). All five questions answered with count-based evidence in `docs/ind_money_payloads.md`; **verdict GO, kill criterion NOT triggered**, but A1/D1/M1/S1 all take scope changes and F3's plan default is confirmed. 18 synthetic fixtures + README in `backend/tests/fixtures/ind_money/`; 74 new tests (suite 43→111 passed, 6 skipped). Adversarial leak check (`backend/tests/leak_check_ind_money.py`, `--self-test` proves non-vacuous) run to PASS over 37 files; it caught 5 rounds of real overlap first. Raw captures retained in scratch (outside the tree) until this gate passes, then deleted. Docs: `docs/SPECS/C2.md`, `docs/TESTING/C2.md`. **M1 still must not start until a human reads the go/no-go.** |
| M1 model + connectors | ✅ **done 2026-08-15** | Merged to `main` (14 commits). `backend/portfolio/`: `Holding` model (Decimal money, nullable P&L, no xirr), 16-value `AssetType` + UNKNOWN tolerance (US_STOCK_WALLET lands on UNKNOWN — confirmed live), typed `PortfolioSourceError` hierarchy covering every failure incl. rate-limit body envelopes (both tiers), vendor error flags, malformed values; IND Money + stub connectors interchangeable behind one contract suite; vendor names banned above `connectors/` by an AST code-token test. 374 tests, 16 mutation probes killed, live smoke green. Carried: IND_STOCK stays UNVERIFIED (D1: no table until a populated capture); REVOKED idle-poll case → F3; code-less rows have position-dependent ids → S1 churn note; stub fixtures live under `backend/tests/fixtures/demo/` → U1 one-constant move. Pre-loaded scope changes from C2: `IND_STOCK` returns a *different* 19-key live-trading envelope (not the 14-key aggregator row) and **has never been seen populated** — keep it behind an explicitly-unverified boundary; all money/percent fields must be `float`/`Decimal` (the API emits `int` and `float` for the same field); `invested_amount == 0` means *unknown cost basis*, not zero — nullable, never fed into P&L; and **rate-limit errors come back as `isError: false` with an `error` body replacing the payload** — check for an `error` key before indexing `data`/`holdings`, budget by per-call `cost` (breakdown calls cost 2), honour `retry_after_seconds`. |
| D0 design bake-off | ✅ **done 2026-08-16, gate passed** | Five Fable-built demos in `docs/design/` (a-shadcn, b-terminal, c-passbook, d-annual, e-brutalist), all over the same synthetic dataset, full D1 surface incl. null states; palettes OKLab-validated; visually verified at 1280px + 375px via headless Chrome (screenshots in session scratchpad — repo stays binary-free). Operator picked **shadcn** (2026-08-16); direction extended with a2-overview / a3-insights / a4-shell surface mocks (AI overview, insights+SIP+projection, app-shell states). Locked in `docs/design/DECISION.md` + plan §2 + memory; losers in `rejected/`. D1 unblocked. |
| D1 dashboard | ✅ **done 2026-08-16** | Merged (7 commits). `/portfolio` page in the locked shadcn design + `GET /portfolio/summary|holdings|allocation|history` consuming M1 connectors only; interim admin gate on every route (fail-closed 401, single-tenant bypass local-only, both modes pytest-pinned); sector/cap ride the single snapshot call, allocation is click-lazy (no 16×3 sweep possible); honest empty-history trend until S1; IND_STOCK boundary state; Return % only (no XIRR); NEXT_PUBLIC admin secret loudly never-on-Vercel (DEPLOY.md + .env.local.example); legacy pages pixel-untouched (conditional chrome, [data-adp]-scoped tokens). Review: 0 Critical, 2 Important + 8 minors, all fixed & re-verified. 411 tests. Visually verified 1280+375. |
| S1 snapshots | ✅ **done 2026-08-16 — awaiting operator wiring** | Merged (12 commits). `snapshot_days`/`holdings`/`raw` (migration 0002+0003, cascades for L1, `usd_inr_rate`, `buckets_failed` partiality marker with a none_as_null SQL fix); capture service (IST calendar-day attribution w/ 06:00 cutoff, first-wins idempotency, skip-and-log, paced buckets, FX NULL-on-failure); `POST /internal/snapshot|prune` behind fail-closed `CRON_SECRET`; GitHub workflow (18:15+19:30 UTC, deadline-based wake, body-code 503 disambiguation, red on final failure); staleness banner + live Capture button; vitest wired (31 tests incl. D1 race guard). 469 pytest. Review: 0 Critical, 2 Important + 9 minors, all fixed & mutation-re-verified. **Not live until the operator wires: Neon `DATABASE_URL` + `CRON_SECRET` on the Space, `CRON_SECRET` GitHub secret, alembic upgrade, IND Money re-login (link revoked at source again). Runbook: `docs/TESTING/S1.md` §7.** |
| F2 clerk | ✅ **done 2026-08-16** | Reviewed (0 Critical; 3 Important, all LATENT since `current_user` is wired into nothing — carried to F3 as REQUIRED: negative-cache unknown JWKS kids; require session-token evidence (`sid`); `CLERK_AUTHORIZED_PARTIES` mandatory in the wiring commit) and merged. Real keys exist locally (app leading-sheepdog-6215); Waitlist-mode dashboard toggle = operator morning item. Clerk landed with `NEXT_PUBLIC_AUTH_ENABLED` **off**, so the live site is unchanged. Backend: `api/deps.py` `current_user` — RS256 against `CLERK_JWKS_URL`, networkless after one JWKS fetch (cached 300 s), issuer-pinned, optional `azp`, lazy `users` upsert on first sight; **wired into no endpoint** (F3/F4 consume it). Fail-closed 503 on missing config *and* on an unreachable JWKS — never a 401, which would blame the caller. `PyJWT==2.13.0` chosen over `clerk-backend-api` (the SDK wants a `CLERK_SECRET_KEY` + httpx Request for the same local check); the backend now holds **no Clerk secret**. Frontend: `<ClerkProvider>` inside `<body>`, `middleware.ts`, `/sign-in` + `/waitlist` (Waitlist mode), top-bar `<UserButton>`, token on every `lib/api.ts` call; v1's `useAuth` → `useIndMoney`. **Flag off = downloads no Clerk**, enforced structurally (server-component gate in `components/Identity.tsx`; `next/dynamic` in `UserMenu` because it sits under a client component; `notFound()` on both routes) and pinned by a source-scan test with a positive control. Measured flag-off vs a pre-branch build: `/portfolio` **0/1,296,000 differing pixels**; `/` 230 px inside the same box that one unchanged build self-differs by (242) — its own pulse animations; First Load JS 132→133 kB on `/`, unchanged on `/portfolio`; shared chunks keep their content hashes. 510 pytest (41 new; 32 run with no Postgres), 56 vitest (25 new), `tsc --noEmit` clean, builds green flag-off **and** flag-on with placeholder keys. **Two carried facts.** (1) `middleware.ts` now exists and Next invokes it on matching requests where before there was none — `config.matcher` must be a static literal (a ternary fails the build), so the matcher is unconditional and the body is a `NextResponse.next()` pass-through when off. (2) **Flag on + placeholder keys builds and serves 200s but is unusable in a browser**: a `pk_test_` key makes `clerk-js` run its dev-browser handshake, which navigates the page to the Clerk Frontend API and lands on `{"errors":[{"code":"host_invalid"}]}`. Flag on ⇒ real keys, no exceptions. Also: `react`/`react-dom` 19.0.0 → **19.0.8** — Clerk's peer range (`~19.0.3 \|\| ~19.1.4 \|\| ~19.2.3`) excludes 19.0.0 and an unmet peer is an ERESOLVE failure on a clean Vercel install (Clerk v6 has the same range). Clerk-docs drift found: `<ClerkProvider>` must be **inside `<body>`** (Core 3), `<SignedIn>/<SignedOut>/<Protect>` removed in favour of `<Show>`, `getToken` now *throws* `clerk_runtime_not_browser` during SSR, `clerkMiddleware` does not protect routes by default, Next 16 renames `middleware.ts` → `proxy.ts`. **Operator wiring pending (blocks L1, not this card):** Clerk instance + Waitlist mode in the Dashboard, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` on Vercel, `CLERK_JWKS_URL` + `CLERK_ISSUER` + `CLERK_AUTHORIZED_PARTIES` on the Space. Runbook: `docs/TESTING/F2.md` §4. Docs: `docs/SPECS/F2.md`, `docs/TESTING/F2.md`. |
| F3 per-user linking | ✅ **done 2026-08-16** | Merged (12 commits). `_Auth` singleton → `AuthStore.for_user` (Fernet-encrypted `broker_links`, per-user asyncio locks); OAuth `state`→user in `oauth_pending` (single-use+10min TTL, no cookie); both scopes; client reuse w/ invalid_client re-register; unlink revokes upstream first; `current_user` wired into `/auth/*` + `/portfolio/*` + snapshot batch; per-user connector (M1 singleton dead); identity-bound `local`-data adoption (verified-primary email == `ALPHADESK_OPERATOR_EMAIL`, never first-comer). F2's 3 latent Importants closed here (JWKS neg-cache, `sid` required, `azp` mandatory). Ultracode 3-lens review: found+fixed reflected XSS on `/auth/callback`, an adoption email-verification bypass, uncaught-decrypt 500s, admin-path fragmentation, 2 mutation-proven test gaps — all fixed, 9/9 mutations killed, 25/25 live checks w/ real Clerk users, 613 pytest. Env wired (Space+local): TOKEN_ENCRYPTION_KEY, CLERK_JWKS_URL/ISSUER, CLERK_AUTHORIZED_PARTIES, ALPHADESK_OPERATOR_EMAIL. **Interim: `/portfolio/*` still accepts the admin header until L1 (8-site removal checklist in SPECS/F3.md §5); `/analyze` stays ambient → F4 required.** Morning: real IND login is the last unverified E2E (reused-client + 2-scope + revoke + durability). |
| F3 — the C2 inputs it was built on | (kept for the record) | **C2 confirmed the plan default; the first C2 write-up inverted it and was corrected on review.** Per-user DCR is **viable** — the pre-F3 `begin_login()` registered a fresh confidential client on every login and carried it through `/authorize` + `/token` in production. F3 kept that default and stopped the churn: `client_id`/`client_secret` on the link row, reused on re-link. The "one pre-registered client" fallback was conditioned on C2 finding per-user DCR unviable — that trigger never fired; it stays documented for the day a restriction appears. Discovery advertises a **`revocation_endpoint`** (F3 uses it on unlink; it revokes *tokens*, not client registrations) and `scopes_supported = [portfolio:read, market:read]` — F3 requests both, and no write scope exists. **Open risk, unchanged: volume, not viability** — registrations accumulate with no known client-deletion path, though F3's reuse means one per user rather than one per login, and absent rate-limit headers prove nothing on a server that signals limits in response bodies. |
| F4 per-user Lab state | ✅ **done 2026-08-16** | Merged (5 commits). `PortfolioState.user_id` + run-user ContextVar (concurrency-proven safe — no cross-user token mint); `_RUNS/_ANALYSES/_ACTIONS` per user, MemorySaver kept, no runs/analyses tables; **`/analyze` gated on identity — last ambient path CLOSED** (401 no-id, 409 unlinked, per-user AuthStore, no admin path); ownership **404-not-403** on all Lab endpoints, `/analyses` self-only; persistent denormalized `watchlist` (migration 0005, opaque non-FK run_id, PK (user_id,symbol), cascade for L1); desk moved to `/lab` w/ persistent simulation label (terminal aesthetic kept). Review PASS: 0 Critical/Important, 2 latent minors ledgered. 625 pytest. |
| A1 AI overview | ✅ **done 2026-08-16** | Merged (9 commits). Metrics computed in Python (HHI, top-N, single-holding%, sector concentration, WoW delta — NO XIRR); 4 specialists (allocation_critic/concentration_risk/sip_health/performance_attribution) → synthesizer; **no-invented-numbers now STRUCTURAL** (numbers reach UI only as metric chips; any digit in free prose → scripted fallback — the substring hole found+closed in review); redact() on every prompt incl. synthesizer; `provider=` wins over env (portfolio→OpenAI, Lab→Groq untouched even with OPENAI_COMPATIBLE_MODEL set); portfolio_runnable_config() tracing-off asserted (F1's deferred test); **graceful degradation verified across all 5 LLM-failure modes** (dashboard renders every computed number, 'AI overview unavailable', never a 500/hang); app-side global+per-user spend caps + 30s timeout; committed demo artifact for /demo. Review (ultracode 3-lens): no-invention FAIL→fixed structural, redact bypass + missing integration test fixed; all mutations killed. 664 pytest. |
| U1 app shell | queued | |
| L1 pre-launch bar | queued — **INVITE GATE** | |

## Deploy notes (read before pushing to the Space)

- **GitHub `main`** keeps full history: `git push origin main`.
- **HF Space** rejects the two `docs/screenshots/` PNGs (binary policy). C1
  removed them from HEAD, but the pre-receive hook scans **all pushed
  history**, so a direct `git push space main` is still rejected (verified
  2026-08-15). The Space therefore keeps deploying from the **`space-deploy`
  snapshot branch**: `git checkout space-deploy && git read-tree -u --reset main
  && git commit && git push space space-deploy:main` (makes the snapshot tree
  identical to `main`'s). Retiring this would need a `main` history rewrite —
  deliberately not done.
- Space: `https://huggingface.co/spaces/heyavasthi/alphadesk`, live at
  `https://heyavasthi-alphadesk.hf.space`. Currently running `space-deploy` @
  the mcp-pin commit.

## Landmines found so far

- **Unpinned dependencies broke prod once already** (2026-08-15): `mcp` 2.0.0
  removed `streamablehttp_client`; first rebuild after its release crashed the
  Space at import. Pinned `mcp==1.28.1`. **Resolved by C1:** every direct dep
  now pinned `==`; bumps are deliberate commits re-verified via Docker build.
  (Transitives still float — pip-compile lockfile is the escalation if ever
  needed. Pins sourced from the py3.12 venv; image is py3.11 — bumps must be
  Docker-build-verified, not assumed.)
- **Prod IND Money auth does not survive a Space restart** (by design, since
  C0): the `IND_MONEY_OAUTH_*` env fallback is dead in production. Reconnect =
  `POST /auth/login` with the `x-alphadesk-admin-secret` header, open the
  returned URL. F3 makes links durable (Postgres, per user).
- **Local dev needs `ALPHADESK_SINGLE_TENANT=1`** in `backend/.env` (already
  set on the operator's machine) or the local Connect button 401s.
- **There is no `RunnableConfig` field that disables LangSmith tracing**
  (verified against langchain-core 1.4.9 / langsmith 0.10.3): `callbacks=[]`,
  `callbacks=None` and an empty `CallbackManager` all still resolve to a live
  `LangChainTracer` when `LANGCHAIN_TRACING_V2=true`. F1's
  `portfolio_runnable_config()` works by occupying the tracer slot with an
  inert `LangChainTracer` subclass — i.e. it **rides on a langchain-core
  internal**. Mitigated two ways: `langchain-core==1.5.5` is pinned even though
  it is transitive (it had already drifted — 1.5.5 in the image vs 1.4.9 in the
  venv), and the `Dockerfile` runs `tests/check_tracing_in_image.py` as a
  **build-time gate** so a bad resolution fails the build. Still re-run
  `backend/tests/test_portfolio_config.py` after any langchain/langsmith/
  langgraph bump.
- **`docker build` locally would have baked `backend/.env` into the image**
  until F1 added a `.dockerignore` (`COPY backend/` takes everything, and .env
  now carries `TOKEN_ENCRYPTION_KEY` as well as `GROQ_API_KEY`). If you add a
  new secret file under `backend/`, add it to `.dockerignore` too.
- **The pytest suite creates and DROPs a `<db>_test` database.** It refuses to
  run against a non-loopback `DATABASE_URL` inherited from the shell; a remote
  target must be named in `TEST_DATABASE_URL` on purpose.
- **Losing `TOKEN_ENCRYPTION_KEY` means every stored broker link is
  undecryptable** and every user must re-link. It is a Space *secret*; back it
  up before rotating anything.
- **`networth_holdings` returns two different payload shapes** (C2, verified):
  a 14-key aggregator row for MF/SA/FD/US_STOCK, but a 19-key live-trading
  envelope (positions, orders, pledge/MTF flags) for **`IND_STOCK`** — the asset
  type AlphaDesk exists for. One model will not fit both. Worse: the operator's
  account had **zero `IND_STOCK` rows**, so the populated Indian-stock row shape
  **has never been observed by anyone**. Anything built on it is a hypothesis
  until a capture from an account holding Indian stocks says otherwise.
- **The IND Money payloads carry no date field and no currency field. At all.**
  (C2, verified by a key-name walk over all 67 payload captures — 54 distinct key names, none date- or currency-shaped.) Consequences: XIRR is
  uncomputable (and the `xirr` field it does ship was 0 in 14/14 rows); anything
  time-based must be stamped by AlphaDesk at ingest; and there is no way to tell
  whether `US_STOCK` values are INR or USD, while `networth_snapshot` already
  sums them into its totals regardless.
- **The IND Money MCP server rate-limits in the response BODY, with
  `isError: false`** (C2, verified against a captured breach): a throttled call
  returns `{error: "rate_limit_exceeded", message, scope, window, tool, limit,
  current, cost, retry_after_seconds}` **in place of** the expected payload.
  There is no HTTP error and no `Retry-After` header. Any code that trusts
  `isError` and indexes straight into `data` / `holdings` crashes with a
  `KeyError` instead of retrying. **Two tiers:** per-tool 15/min
  (`scope: "tool"`, `window: "tool:min"` — captured) and global 30/min
  (`scope: "global"`, `window: "min"` — run-1 notes only). The per-tool tier is
  tighter and trips first on any single-tool burst, so **read `scope`, `limit`
  and `retry_after_seconds` off the body** instead of hard-coding a tier. Calls
  are not equally priced — `networth_allocation_breakdown` costs 2, tripping the
  per-tool limit after 7 calls. Invisible in a happy-path capture; the original
  C2 write-up missed it entirely and blamed batching on session timeouts.
- **`networth_snapshot` reports a bucket the holdings tool cannot enumerate**
  (C2): `investments[]` includes `asset_type: "US_STOCK_WALLET"`, which is
  **not** in `networth_holdings`' 16-value `asset_type` enum. Summed holdings sit
  ~2.3% below the snapshot total by construction, so any "holdings must sum to
  net worth" check or DB constraint is guaranteed to fail. Re-derived bucket by
  bucket: the wallet is the **principal** cause but over-explains the gap, and
  **per-type buckets do not equal their own holdings sums either** — SA and FD
  are exact to the paisa, MF is off +0.015% and US_STOCK +0.944% of their own
  buckets, consistent with the aggregate and the rows being priced from
  different refreshes (there is no `as_of` to check). **`sum(holdings) + wallet
  == total` fails too.** Use a documented tolerance, never equality.
- **`networth_snapshot` carries no `IND_STOCK` bucket at all** (C2): the empty
  `networth_holdings(IND_STOCK)` response is an empty portfolio slice, not a
  broken or permission-limited endpoint. The Indian-stock *row shape* is still
  unverified; its absence is not the mystery.
- **`broker` is not a safe grouping key** (C2): it was an empty string in 4 of 14
  real rows (all FD and SA). `investment` (the display name) was empty in 1 of
  14. Dedup or source-attribution keyed on either will silently collapse rows.
- **`NEXT_PUBLIC_AUTH_ENABLED=true` with a placeholder Clerk key builds, serves
  200s, and is still a broken site** (F2, verified): a `pk_test_` key makes
  `clerk-js` run its dev-browser handshake, which *navigates the browser* to the
  Clerk Frontend API — with a fake host every page lands on
  `{"errors":[{"code":"host_invalid"}]}`. The server is fine; the takeover is
  client-side, so a `curl` health check says everything is green. Never deploy
  the flag on without real keys. And it is a **build-time** value — flipping it
  needs a rebuild, not a restart.
- **Real payloads must never enter this public repo.** C2's procedure —
  scratch-only captures outside the working tree, hand-written synthetic
  fixtures, an adversarial leak check with a self-test, captures retained for
  review and deleted after the gate — is written up in `docs/TESTING/C2.md` and
  is the pattern for any future capture. The check found real overlap in 5
  successive rounds, including in prose that merely *described* the payloads,
  so do not skip it. **And do not trust a `PASS` without checking the scan
  scope:** a sixth leak sat in the checker's own source, which the checker did
  not scan until review widened it.
