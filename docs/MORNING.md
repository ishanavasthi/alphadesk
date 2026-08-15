# Morning review — overnight build log for the operator

Running list of everything that needs your eyes or your hands. Newest at the
bottom of each section. (No secrets in this file — it is committed.)

## Needs your HANDS (blocking bits of wiring)

1. **S1 wiring** (runbook `docs/TESTING/S1.md` §7): Neon signup → paste/set
   `DATABASE_URL` + `CRON_SECRET` on the HF Space, `gh secret set CRON_SECRET`,
   one `alembic upgrade head` against Neon. Until then the nightly snapshot
   workflow goes honestly red (or disable it).
2. **IND Money re-login** — your link is revoked at the source again (tokens
   are dying server-side within hours; F3 makes links durable). Needed for:
   nightly captures, F3's real-link verification. Ask me for a login URL.
3. **Clerk application** — create at clerk.com, enable **Waitlist** mode,
   then set `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY`
   (frontend env) and `CLERK_JWKS_URL` + `CLERK_ISSUER` (backend env).
   ⚠️ Flag-on with placeholder keys builds but is a broken site in a real
   browser (Clerk dev-browser handshake) — real keys or flag stays off.
4. **OpenAI provider-side budget cap** (before A1 is used in anger): set a
   hard monthly limit in the OpenAI dashboard — the one control an app bug
   cannot bypass. App-side ceilings ship in A1 code.

## Decisions I made overnight (review, undo if wrong)

- **react/react-dom 19.0.0 → 19.0.8** (F2): forced — Clerk's peer range
  excludes exactly 19.0.0 and a clean Vercel install would ERESOLVE-fail.
  Patch-level, pinned, both flag states build; pixel-diff showed zero visual
  change. Undo = drop Clerk (not an option) or pin react back and vendor
  Clerk's peer check (not worth it).

## Questions parked for you (non-blocking)

- **CLERK_AUTHORIZED_PARTIES** (`azp` check): implemented + tested but unset.
  Current plan: make it mandatory at L1. Flag if you want it earlier.

## Where things stood when this file was last updated

See `docs/STATUS.md` (always current) and the per-card `docs/SPECS/` +
`docs/TESTING/`.
