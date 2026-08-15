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
