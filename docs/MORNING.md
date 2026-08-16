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
