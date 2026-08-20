# AlphaDesk v2 — Handoff & Operator Runbook

**Status (2026-08-16):** the v2 build is **complete** — all 14 plan cards
(C0→L1) built, reviewed, merged, and deployed. `main` is clean at the latest
commit; backend live on the HF Space; frontend live and deliberately gated to
its **safe pre-launch state** until the operator runs go-live. Nothing is
blocked on an agent — the only remaining work is the operator go-live steps in
§2 and the optional follow-ups in §5.

This file is the single handoff doc. A fresh agent with zero conversation
history should be able to pick up any task from here plus `docs/STATUS.md` (the
card ledger) and `docs/SPECS/`+`docs/TESTING/` (per-card contracts). No secrets
are in this file — it is committed.

---

## 1. Fast facts (coordinates a fresh agent needs)

| Thing | Value |
| --- | --- |
| What it is | Multi-user Indian-equity **portfolio analyzer** (net worth / allocation / history / AI overview) + a labelled research **Lab** (simulation). FastAPI + LangGraph backend, Next.js frontend. **No real orders ever placed.** |
| Plan of record | `V2_PLAN.md` (§0 protocol, §2 locked decisions). Card ledger: `docs/STATUS.md`. Per-card: `docs/SPECS/<card>.md`, `docs/TESTING/<card>.md`. |
| SDD build ledger | `.superpowers/sdd/V2_PLAN/progress.md` (gitignored via `.git/info/exclude`; the overnight build record + every ruling). |
| Live frontend | `https://alphadesk.ishanavasthi.in` (Vercel project `alphadesk`, alias `alphadesk-two.vercel.app`). Currently **flag-off** (public landing + `/demo`, no auth wall). |
| Live backend | HF Space `heyavasthi/alphadesk` → `https://heyavasthi-alphadesk.hf.space`. `/portfolio/*` is JWT-only (401 until sign-in). |
| Database | Neon Postgres, **at head (migration 0005)**. Connection string is in local `backend/.env` and the Space `DATABASE_URL` secret. |
| Identity | Clerk app `leading-sheepdog-6215` (instance `leading-sheepdog-6215.clerk.accounts.dev`). CLI authenticated locally. |
| Repo | Public GitHub `ishanavasthi/alphadesk`. `main` tracked by Vercel; the Space deploys from the binary-free `space-deploy` snapshot branch (see §6). |
| Backend imports | resolve with `backend/` as root (`api.main`, `graph.*`, `tools.*`, `db.*`, `portfolio.*`) — **no `backend.` prefix**. Run from inside `backend/`. |
| Venv | repo-root `.venv/` (Python 3.12). Tests: `pip install -r requirements.txt -r requirements-dev.txt`. |

---

## 2. Go-live sequence (operator only — do IN ORDER to invite people)

Nothing reaches a real user until all of these are done.

1. **IND Money re-login.** Your broker link is revoked at the source again
   (tokens die server-side within hours). Ask any agent for a login URL, or
   locally: run the backend with `ALPHADESK_SINGLE_TENANT=1`, `POST /auth/login`,
   open the returned URL. This also proves F3 end-to-end (see §5 "unverified").
2. **Enable Clerk Waitlist mode** — Clerk Dashboard → Configure → Restrictions
   → Sign-up mode → **Waitlist**. Not exposed via API; manual toggle. Without
   it, flipping the flag = open sign-up.
3. **Set Clerk keys on Vercel** — the `alphadesk` project has only
   `NEXT_PUBLIC_API_URL`. Add `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and
   `CLERK_SECRET_KEY` (Production; the real values are in your local
   `frontend/.env.local`). **With the flag on, placeholder/missing keys = a
   broken `host_invalid` site** — real keys are mandatory.
4. **OpenAI budget cap** — set a hard monthly limit in the OpenAI dashboard
   (the one control an app bug can't bypass; app-side ceilings only degrade).
   Confirm the Space has `OPENAI_API_KEY` (set overnight).
   - ⚠️ **UN-PAUSE THE AI OVERVIEW — it is currently off on purpose.**
     `OVERVIEW_DAILY_GLOBAL_MAX=0` on the Space *and* in local `backend/.env`,
     paused 2026-08-17 while the dashboard is reworked (it was regenerating too
     often during iteration). At `0` every overview degrades to "AI overview
     paused — the daily generation budget is reached", with all computed
     numbers still rendering — friends would see that box, not a narrative.
     **Set both back to `500`** (Space → Variables, and local `.env`). The value
     is re-read per request, but changing a Space variable restarts the Space.
     Verify by loading `/portfolio` and confirming a narrative renders.
5. **Flip the site live** — in Vercel, change the `NEXT_PUBLIC_AUTH_ENABLED`
   Production env var from `false` → `true`, redeploy. Site goes behind Clerk
   Waitlist. (This reverses the safe override from §4-decision below.)
6. **Optional hygiene** — unset `ALPHADESK_ADMIN_SECRET` on the Space if still
   set (the code that read it was deleted at L1; harmless, just dead). Delete
   the two throwaway Clerk test users `f3alpha+clerk_test@example.com` /
   `f3bravo+clerk_test@example.com`.
7. **Approve your first users** from the Clerk Dashboard.

---

## 3. What was wired overnight (done — for the record)

- **Neon:** provisioned, migrated to **head (0005)**, `DATABASE_URL` set on the
  Space + local. (First migrated at 0003 during S1 wiring; F3/F4 migrations
  0004/0005 applied later once merged — **the final audit caught and fixed
  this; without it your first Connect would have 500'd**.)
- **Space secrets:** `DATABASE_URL`, `TOKEN_ENCRYPTION_KEY`, `CRON_SECRET`,
  `CLERK_JWKS_URL`, `CLERK_ISSUER`, `CLERK_AUTHORIZED_PARTIES`
  (`https://alphadesk.ishanavasthi.in`), `ALPHADESK_OPERATOR_EMAIL`
  (`hiavasthi@gmail.com`), `OPENAI_API_KEY`. Stray `OPENAI_COMPATIBLE_MODEL`
  deleted from the Space (plan §9).
- **GitHub:** `CRON_SECRET` secret set; snapshot workflow ran green
  (`skipped:1` while the IND link is down — correct).
- **Clerk:** CLI authenticated, app linked, real keys in local env files
  (never committed).
- **Vercel:** `NEXT_PUBLIC_AUTH_ENABLED=false` override set + redeployed to
  keep the live site safe (see the decision below).

---

## 4. Decisions made on the operator's behalf (review; undo if wrong)

- **Vercel flag override → `false`.** L1 flips `NEXT_PUBLIC_AUTH_ENABLED` on via
  committed `frontend/.env.production`, so the merge auto-built the frontend
  flag-on — but Vercel has no Clerk keys, so the live site briefly became the
  broken `host_invalid` page (breaks the plan's "live site never breaks" rule).
  I set a Vercel Production override `=false` and redeployed → safe pre-launch
  state restored (verified 200, no Clerk refs). Go-live step 5 reverses it.
  If you'd rather the *code default* be flag-off, say so and I'll edit
  `.env.production`.
- **`ALPHADESK_OPERATOR_EMAIL=hiavasthi@gmail.com`** (Space + local) — the
  address whose first Clerk sign-in adopts your pre-F3 `local` snapshot history
  (matched against the verified primary email). **Confirm it's the email you'll
  sign in with**; if not, tell me before you sign in. Unset ⇒ adoption never
  runs, history stays under `local` (nothing lost, just not migrated).
- **react/react-dom 19.0.0 → 19.0.8** (F2) — forced by Clerk's peer range
  (19.0.0 ERESOLVE-fails a clean Vercel install). Patch-level, pinned,
  pixel-diff showed zero visual change.
- **`/analyze` gating deferred F3→F4** — F3 flagged the ambient path; F4 owns
  the Lab surface, so it closed it there. Done.

---

## 5. Follow-ups & known tech debt (for agents picking up work)

None blocking; all documented. Pick any up in a fresh session.

- **The 4 "unverified end-to-end" paths** need one real IND Money login (a mock
  can't prove them): the vendor accepting a **reused** DCR client; the
  **two-scope** (`portfolio:read market:read`) grant — C2 saw `portfolio:read`
  only come back; the **revocation** endpoint accepting our unlink call; and
  **link durability across a Space restart** (the whole point of F3). Ordered
  checklist: `docs/TESTING/F3.md` §6. Also: one real `/analyze` (F4) and one
  real `/portfolio/overview` (A1) narrative against a live account.
- **`_is_invalid_client`** (`backend/tools/ind_money_auth.py`) is an unverified
  guess at IND's DCR error vocabulary (RFC-6749 default). If a real login hits
  a dead stored client and does NOT self-heal, that predicate needs the real
  error body. Fails visibly (logs); manual recovery is one `POST /auth/logout`.
- **Rate-limit test hygiene (found by the final audit).** The `test_ratelimit.py`
  tests use `TestClient(app)` directly, so they inherit whatever `DATABASE_URL`
  is in local `backend/.env` and, against a real async DB, hit an asyncpg
  event-loop-reuse error (a TestClient harness limitation — the production path
  works, proven by F3's 25/25 live `/auth/login` checks). **CI is green** (no
  `.env`); full suite = **674 passed** in the CI-equivalent env. Fix: isolate
  those tests from the ambient DB. → **To run the full suite locally, run with
  `backend/.env` moved aside (or `DATABASE_URL` genuinely absent) and a
  throwaway `TEST_DATABASE_URL` Postgres.**
- **`graph/graph.py::run_graph`** defaults `PortfolioState` to `user_id="local"`
  and has zero non-test callers — latent footgun if ever wired to an endpoint.
  Make `user_id` required when someone touches it.
- **In-memory state is per-process** (Lab runs, rate-limit counters, spend
  tallies, AuthStore cache). Correct for the single HF Space; revisit if it
  ever scales to multiple replicas.
- **App-side spend ceilings are a courtesy, not a hard stop** — the OpenAI
  provider-side cap (go-live §4) is the real backstop. Env knobs on the Space:
  `OVERVIEW_DAILY_GLOBAL_MAX` (**currently `0` — paused, see go-live §2 step 4**),
  `OVERVIEW_DAILY_USER_MAX` (20),
  `RATE_LIMIT_PER_CALLER_MAX` / `RATE_LIMIT_GLOBAL_MAX`.
  Setting `OVERVIEW_DAILY_GLOBAL_MAX=0` is the supported **kill switch** for AI
  spend: `SpendLimiter.reserve` denies every request (`reason="spend_cap"`), the
  route degrades before any model call, and no tally is consumed — so flipping
  it back to `500` restores generation immediately. A narrative already saved
  for the current IST day still replays from `portfolio_cache` while paused;
  that replay is free.
- **`/demo` overview artifact is static** (`backend/tests/fixtures/demo/
  overview.json`, no LLM call). Regenerate with
  `cd backend && python -m agents.portfolio.demo` if fixtures/prompts change.

---

## 6. Environment & deploy mechanics (the non-obvious bits)

- **Deploy to GitHub:** `git push origin main`. Vercel auto-builds the frontend
  from `main` (root dir `frontend`).
- **Deploy to the HF Space:** the repo history contains binaries HF rejects, so
  the Space deploys from the **`space-deploy` snapshot branch**:
  ```
  git checkout space-deploy && git read-tree -u --reset main \
    && git commit -m "Deploy: <what>" && git push space space-deploy:main \
    && git checkout main
  ```
  (`docs/STATUS.md` "Deploy notes" has the canonical version.)
- **Every dep is pinned** (`==`) in `requirements.txt` / `requirements-dev.txt`;
  bumps are deliberate commits, re-verified via `docker build`. `langchain-core`
  is pinned despite being transitive (the tracing kill-switch rides a library
  internal; the Docker build gates on `tests/check_tracing_in_image.py`).
- **Local backend needs `ALPHADESK_SINGLE_TENANT=1`** in `backend/.env` for the
  Connect button to work without Clerk. Must stay **unset** on the Space (it
  fail-opens every request to the operator identity).
- **Tracing:** LangSmith on for the research/Lab graph, **off** for the
  portfolio graph (config-level, not env — `graph/portfolio_config.py`).

---

## 7. How to resume build work

1. Read `CLAUDE.md`, `V2_PLAN.md`, `docs/STATUS.md`. For a specific card, its
   `docs/SPECS/<card>.md` + `docs/TESTING/<card>.md`.
2. The overnight build used the superpowers **subagent-driven-development**
   flow: Fable orchestrates, Opus subagents implement in git worktrees,
   adversarial review (ultracode 3-lens workflows for C2/M1/F3/A1/L1) + fix
   loops + orchestrator acceptance before each merge. The full ruled record is
   the SDD ledger (§1 table). All 14 cards are `✅ done` in STATUS.
3. Run the suite the CI way (see §5 rate-limit note): `backend/.env` absent,
   throwaway `TEST_DATABASE_URL` Postgres → **674 passed**.
