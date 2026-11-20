# snapshot-cron — on-time nightly snapshot trigger

A cron-only Cloudflare Worker that calls the backend's `POST /internal/snapshot`
at **23:45 IST** (retry **01:00 IST**) and `POST /internal/prune?days=90` on
Sundays. It is the **primary** trigger. `.github/workflows/snapshot.yml` is the
backup.

**Why not just GitHub Actions (#94):** GitHub's `schedule` event is best-effort.
By Nov 2026 the 23:45 run was starting a median 5 h 24 m late. Past 06:00 IST
the backend files a capture under the next day, so a late night lost its
snapshot and mislabelled the next. Cloudflare cron triggers fire on the minute.
The backup workflow now skips any scheduled capture that starts after 06:00 IST.

| File | What |
|---|---|
| `src/run.js` | All logic: wake the Space, trigger, retry only what a retry can fix, fail loudly. Side effects are injected. |
| `src/index.js` | The `scheduled()` entrypoint. No `fetch` handler, no public URL. |
| `test/run.test.js` | `node --test` on a virtual clock, including the 15-minute wall-time budget. |
| `wrangler.jsonc` | Cron expressions (UTC), `BACKEND_URL`, observability. |

## Operate

```bash
cd infra/snapshot-cron
npm ci
npm test
npx wrangler deploy                    # needs CLOUDFLARE_API_TOKEN (Edit Cloudflare Workers)
npx wrangler secret put CRON_SECRET    # must equal the Space's CRON_SECRET
```

- **Logs:** Cloudflare dashboard → Workers & Pages → `alphadesk-snapshot-cron`
  → Logs. A broken night shows up as a failed invocation, because the error is
  thrown, not swallowed.
- **Changing a time:** edit `triggers.crons` **and** `CAPTURE_CRONS`/`PRUNE_CRON`
  in `src/run.js`. Any cron missing from the code is refused as unknown. Keep the
  GitHub workflow's crons in step.
- **Free plan:** this uses 3 of the account's 5 cron triggers. Each invocation
  gets a 15-minute wall-time cap; the worst case here is 815 s, pinned by a test.
- **Rotating `CRON_SECRET`:** set it in three places, the Space, the GitHub
  secret and this Worker.
