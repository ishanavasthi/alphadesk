# ⭐ ALL BUILD CARDS COMPLETE — read this first

Every card in `V2_PLAN.md` (C0→L1, 14 cards) is built, reviewed, fixed, and
merged overnight. The backend is deployed to the HF Space; the frontend is
live **and deliberately kept in its safe pre-launch state** (see "Go-live"
below). What remains is entirely yours — no more code.

## Go-live sequence (do these IN ORDER when you're ready to invite people)

1. **IND Money re-login** (for YOUR own portfolio + to prove F3 end-to-end).
   Ask me — or any Claude session — for a login URL; your link is revoked at
   the source again. Once linked, your pre-F3 snapshot history auto-adopts to
   your Clerk account on first sign-in (F3), because I set
   `ALPHADESK_OPERATOR_EMAIL=hiavasthi@gmail.com`. **Confirm that's the email
   you'll sign in to Clerk with** — if not, tell me before you sign in.
2. **Enable Clerk Waitlist mode** — Clerk dashboard (app `leading-sheepdog-6215`)
   → Configure → Restrictions → Sign-up mode → **Waitlist**. Not exposed via
   API, so it's a manual toggle. Without it, flipping the flag = open sign-up.
3. **Set the Clerk keys on Vercel** — the `alphadesk` Vercel project currently
   has ONLY `NEXT_PUBLIC_API_URL`. Add `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and
   `CLERK_SECRET_KEY` (Production) — the real values are in your local
   `frontend/.env.local`. Also confirm the Space has `OPENAI_API_KEY` (I set
   it) and set a **provider-side OpenAI budget cap** in the OpenAI dashboard.
4. **Flip the site live** — in Vercel, change the `NEXT_PUBLIC_AUTH_ENABLED`
   production env var from **`false`** (what I set — see the decision below)
   to **`true`**, then redeploy. The site goes behind Clerk Waitlist.
5. **Approve your first users** from the Clerk dashboard.

## ⚠️ Decision I made on your behalf (Vercel — review this)

L1 flipped `NEXT_PUBLIC_AUTH_ENABLED` on via a committed
`frontend/.env.production`. The moment L1 merged, Vercel auto-built the
frontend **flag-on** — but Vercel has no Clerk keys, so the live site briefly
became the broken "host_invalid" Clerk page (the F2 landmine). That breaks the
plan's core rule (main stays deployable; the flag exists so the live site never
breaks). **I set a Vercel Production env override `NEXT_PUBLIC_AUTH_ENABLED=false`
and redeployed**, so the live site is back to its safe pre-launch state (public
landing + `/demo`, no auth wall, no broken page — verified 200 on
alphadesk.ishanavasthi.in). This is exactly what `.env.production`'s own comment
anticipates ("Vercel dashboard variables override this file, so the operator can
still gate a specific deploy"). **To go live, step 4 above reverses it.** If you'd
rather the code default were flag-off, say so and I'll change `.env.production`.

## Final integration audit — result (2026-08-16, after all cards merged)

A 3-lens cross-card audit (flow / docs / security) ran over the whole build.
**Flow coherence SOUND, security SOUND** — "no path to another user's data was
found"; identity never crosses users, the C0 admin path is gone everywhere,
migrations/models match, the delete cascade is total. It caught doc drift
(DEPLOY.md was frozen at the C0 era — now rewritten for the v2 end-state) and
one real thing I fixed:

- **★ Neon was stuck at migration 0003.** I first migrated Neon during the S1
  wiring, when only 0001–0003 existed; F3 (0004, `broker_links.redirect_uri`)
  and F4 (0005, `watchlist`) merged later and were never applied. Left as-is,
  your **first Connect would have 500'd** (the code queries a column the DB
  didn't have). **Fixed: Neon is now at head (0005)**, verified. Nothing for
  you to do — noting it because it's the kind of gap that only shows at first
  real use.

### One test-hygiene follow-up (not blocking, not a product bug)

The rate-limit tests use `TestClient(app)` directly, so they inherit whatever
`DATABASE_URL` is in your local `backend/.env` and, against a real async DB,
hit an asyncpg event-loop-reuse error (a TestClient harness limitation — the
production path works, proven by F3's 25/25 live `/auth/login` checks against
real Postgres). CI is green (no `.env` there); the full suite is **674 passed**
in the CI-equivalent environment. Follow-up: isolate those tests from the
ambient DB. Filed for a future session.

---

# Morning review — overnight build log for the operator

Running list of everything that needs your eyes or your hands. Newest at the
bottom of each section. (No secrets in this file — it is committed.)

## Needs your HANDS (blocking bits of wiring)

1. ~~S1 wiring~~ **DONE overnight** — Neon migrated (0001→0003, `alembic
   check` clean), `DATABASE_URL` + `CRON_SECRET` set on the Space (HF API),
   `CRON_SECRET` set as a GitHub secret, local env updated. A manual
   workflow run was fired to validate the chain (expect green with
   `skipped: 1` while the IND link is down).
2. **IND Money re-login** — your link is revoked at the source again (tokens
   are dying server-side within hours; F3 makes links durable). Needed for:
   nightly captures, F3's real-link verification. Ask me for a login URL.
3. ~~Clerk application~~ **mostly DONE overnight** — CLI authenticated, app
   `leading-sheepdog-6215` linked, real keys in `frontend/.env.local` +
   backend env (never committed). ONE dashboard click left: **enable
   Waitlist mode** (Configure → Restrictions → Sign-up mode → Waitlist) —
   not exposed via API. Needed before the L1 flag flip, not before.
4. **OpenAI provider-side budget cap** (before A1 is used in anger): set a
   hard monthly limit in the OpenAI dashboard — the one control an app bug
   cannot bypass. App-side ceilings ship in A1 code.
5. ~~**F3 needs four env vars**~~ — **DONE by you while I was building**
   (`TOKEN_ENCRYPTION_KEY`, `CLERK_AUTHORIZED_PARTIES`,
   `ALPHADESK_OPERATOR_EMAIL`, `CLERK_SECRET_KEY`, plus `CLERK_JWKS_URL`/
   `CLERK_ISSUER`, locally and on the Space). Kept below for the record and
   because each one has a failure mode worth recognising:
   - `TOKEN_ENCRYPTION_KEY` — **currently unset**. F1 added it; F3 is the
     first card that actually stores an encrypted credential, so without it
     the first Connect attempt fails outright. Generate:
     `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
     (rotating it later makes every stored link undecryptable — users re-link).
   - `CLERK_AUTHORIZED_PARTIES` — **now mandatory**, unset = 503 at auth time.
     `http://localhost:3000` locally; the Vercel origin on the Space. (This
     answers the question parked below: it became mandatory at F3, not L1.)
   - `ALPHADESK_OPERATOR_EMAIL` — your Clerk email. Adoption of the pre-F3
     `user_id="local"` rows (your broker link **and every S1 snapshot day**)
     runs only for this address, matched against your *verified primary*
     email. Unset ⇒ it never runs and your history stays under `"local"`.
     Nothing is lost either way; it just needs the variable to move.
   - `CLERK_SECRET_KEY` — used for exactly one thing: resolving that verified
     email (a Clerk session token carries no email claim). Without it,
     adoption cannot identify you and declines to run.
6. **F3 morning run — the real IND Money login.** Still the one thing that
   could not be done overnight. `docs/TESTING/F3.md` §6 is
   the ordered checklist. The short version: run `alembic upgrade head`
   (0003→0004), link IND Money, then **restart the backend and confirm the
   link survives** — that durability is the entire point of the card and the
   one thing a mock cannot prove. Note `/auth/login` is **JWT-only** now, so
   either link locally with `ALPHADESK_SINGLE_TENANT=1` or run the frontend
   locally with `NEXT_PUBLIC_AUTH_ENABLED=true` and sign in as yourself (the
   second also exercises adoption on your real account). Also worth watching:
   the granted `scope` — we now ask for `portfolio:read market:read`, and C2
   saw a `portfolio:read`-only grant come back from `/register`. And if the
   login fails with something that looks like a rejected *client* rather than a
   rejected grant, F3 is supposed to clear the stored registration and
   self-heal on the next press of Connect (the log line says so) — if it does
   not, `_is_invalid_client` in `backend/tools/ind_money_auth.py` is guessing at
   this vendor's error vocabulary and needs the real body. Manual recovery is
   one `POST /auth/logout`.

## Decisions I made overnight (review, undo if wrong)

- **react/react-dom 19.0.0 → 19.0.8** (F2): forced — Clerk's peer range
  excludes exactly 19.0.0 and a clean Vercel install would ERESOLVE-fail.
  Patch-level, pinned, both flag states build; pixel-diff showed zero visual
  change. Undo = drop Clerk (not an option) or pin react back and vendor
  Clerk's peer check (not worth it).

## Questions parked for you (non-blocking)

- ~~**CLERK_AUTHORIZED_PARTIES** (`azp` check): mandatory at L1?~~ **Answered by
  F3: mandatory now.** F2's review called it out as latent, and F3 is the card
  that wires `current_user` into real endpoints — a check that switches itself
  off when an env var is forgotten is not a check. Unset now answers 503.
- **Two throwaway Clerk users** were created on the dev instance for F3's live
  run — `f3alpha+clerk_test@example.com` and `f3bravo+clerk_test@example.com`.
  Delete them from the Dashboard whenever convenient.
- **`clerkMiddleware()` needs `CLERK_SECRET_KEY` at runtime on the frontend
  host** (found while driving a real sign-in): without it every route 500s with
  flag on. That is a Vercel env var for L1, separate from the backend — which
  still needs no Clerk secret to verify a token.

## Where things stood when this file was last updated

See `docs/STATUS.md` (always current) and the per-card `docs/SPECS/` +
`docs/TESTING/`.

## F3 morning items (per-user auth is merged & deployed)

- **Real IND Money login is the last unverified end-to-end.** Ask me for a
  login URL when you're up. It proves the 4 things a mock couldn't: the
  vendor accepting a **reused** client, the **two-scope** (`portfolio:read
  market:read`) grant, the **revocation** endpoint accepting our unlink call,
  and **link durability across a Space restart**. Until then per-user linking
  is proven only against mocked IND endpoints (Clerk side is fully live).
- **`_is_invalid_client` is an unverified guess** at IND's DCR error
  vocabulary (RFC-6749 default; C2 never provoked a rejected registration).
  If the login above hits a dead stored client and does NOT self-heal, that
  predicate is the fix — it fails visibly (logs) and recovery is one
  `/auth/logout`.
- **`ALPHADESK_OPERATOR_EMAIL` is set to `hiavasthi@gmail.com`** (your Clerk
  login email) on the Space + locally — this is what lets your first sign-in
  adopt the pre-F3 `local` snapshot history. Confirm it's the address you'll
  sign in with; if not, tell me and I'll change it before you sign in.

## F4 morning items (per-user Lab state is merged)

- **One real IND-backed `/analyze` run is the only F4 check a mock couldn't
  do.** F4's gating and per-user isolation are proven against a mocked MCP
  (401/409/runs, cross-user 404, watchlist persistence + cascade — 12 tests);
  what stays unverified is that a *real* linked run mints from your own
  `AuthStore` end-to-end and produces recommendations. Run it in
  **single-tenant dev** (`ALPHADESK_SINGLE_TENANT=1`, links as `local`) after a
  real IND login, or signed in on a flag-on build. If the operator's IND link
  is down when you read this, it's a morning item, not a blocker — the mocked
  path is green.
- **The Lab moved to `/lab`** (`/` now redirects there); `/lab/a/[id]` is the
  per-run view. U1 wires real nav later. Nothing at the root yet by design.
- **The paper watchlist now persists** to the `watchlist` table — it needs
  `DATABASE_URL` (Neon on the Space, local Postgres in dev) and
  `alembic upgrade head` for migration **0005**. With no DB it degrades to
  in-memory per-user, same as before, so local dev without Postgres still runs.

## A1 morning items (AI overview is built)

- **Set a provider-side hard budget cap on the OpenAI dashboard.** A1 ships two
  app-side daily ceilings (`OVERVIEW_DAILY_GLOBAL_MAX` default 500,
  `OVERVIEW_DAILY_USER_MAX` default 20) that fail toward the degraded state, but
  those are a courtesy, not a hard stop. Set a real monthly usage limit on the
  OpenAI account so a runaway loop cannot bill beyond a number you choose. Tune
  the two env ceilings on the Space if you want them tighter/looser.
- **Clear the stray `OPENAI_COMPATIBLE_MODEL` from `backend/.env` (and never set
  it on the Space).** It is a v1 leftover. A1 deliberately made the explicit
  `provider=` argument win and tightened the default so a *lone*
  `OPENAI_COMPATIBLE_MODEL` no longer reroutes anything (compat mode now requires
  `OPENAI_BASE_URL`) — so it is currently **inert**, not dangerous. But per plan
  §9 both `OPENAI_BASE_URL` and `OPENAI_COMPATIBLE_MODEL` must stay **unset** in
  prod: setting `OPENAI_BASE_URL` would route every Lab agent through one compat
  endpoint and collapse their Groq tiering. Recommended: remove the line locally
  so the dev env matches prod.
- **`OPENAI_API_KEY` must be a Space secret** for the overview narrative to
  generate; without it the dashboard still renders every computed number and the
  panel shows "AI overview unavailable" (verified). Optional
  `OPENAI_OVERVIEW_MODEL` overrides the default `gpt-4o-mini`.
- **The `/demo` overview artifact is static** (`backend/tests/fixtures/demo/
  overview.json`) and needs no key. Regenerate it with
  `cd backend && python -m agents.portfolio.demo` if the demo fixtures or the
  scripted prose ever change.
- **One real OpenAI call was spent** proving the happy path (the gated live
  test); the full multi-agent graph is proved with mocked LLMs. A real
  end-to-end narrative against your live linked account is the only thing a mock
  could not do — run `/portfolio` signed in (or single-tenant dev) with the key
  set to see it.

## L1 — THE INVITE GATE IS OPEN (built; your remaining steps to actually invite)

L1 is built and merged-ready on `feat/prelaunch`. The code side of the gate is
done: delete-my-data, consent-at-link-time, real privacy/terms, rate-limit 429s,
the F3 §5 admin removal, and `NEXT_PUBLIC_AUTH_ENABLED` flipped **on** (via
committed `frontend/.env.production`). The remaining steps are all **operator
wiring** — nothing ships to a real person until these are done:

1. **Enable Clerk Waitlist mode** in the Clerk Dashboard (Configure → Restrictions
   → Waitlist), so a stranger who visits registers interest instead of signing up.
2. **Set the real Clerk keys on Vercel** — `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` and
   `CLERK_SECRET_KEY` (plain, not `NEXT_PUBLIC_`). The flag is on now, so a build
   with placeholder keys is a **broken** site (F2 landmine: `clerk-js` navigates
   every page to a `host_invalid` error). Real keys, no exceptions. The Space
   already has `CLERK_JWKS_URL` / `CLERK_ISSUER` / `CLERK_AUTHORIZED_PARTIES` from
   F3 — confirm `CLERK_AUTHORIZED_PARTIES` includes the live frontend origin.
3. **Unset `ALPHADESK_ADMIN_SECRET` on the Space** (F3 §5 step 8). The code that
   read it is deleted, so this changes nothing functionally — it is hygiene, to
   retire the dead secret. After this, the operator reaches `/portfolio` and the
   Lab by **signing in with Clerk**, not the admin header (which no longer works).
4. **Re-link IND Money the real way:** sign in on the live site, click Connect,
   agree on the consent screen, complete the broker OAuth. (The old
   admin-header `POST /auth/login` reconnect is gone.) This is also the last
   unverified end-to-end path — the real link + a real `DELETE /account` against
   Neon.
5. **Approve the first users** from the Clerk Dashboard as invites go out.

Optional but recommended: tune `RATE_LIMIT_PER_CALLER_MAX` / `RATE_LIMIT_GLOBAL_MAX`
on the Space if the defaults (60 / 600 per 60s on `/analyze`, `/portfolio/overview`,
`/auth/login`) are looser or tighter than you want. And keep the OpenAI provider-side
budget cap from the A1 items above — the app-side ceilings degrade, they do not bill-stop.
