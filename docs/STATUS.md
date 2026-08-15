# AlphaDesk v2 — card ledger

Plan of record: [`../V2_PLAN.md`](../V2_PLAN.md). The orchestrator updates this
file at every card completion and gate. Newest facts win; keep entries terse.

**Last updated:** 2026-08-15 (C1 merged: RAG unplugged, all deps pinned, screenshot binaries dropped; `space-deploy` dance stays — HF scans pushed *history*, so a direct `main` push is still rejected)

| Card | Status | Notes |
| --- | --- | --- |
| C0 lockdown | ✅ **done 2026-08-15** | Admin gate on `/auth/login`+`/auth/logout` (`ALPHADESK_ADMIN_SECRET`, fail-closed); ambient credential fallbacks gated behind `ALPHADESK_SINGLE_TENANT` (local only). Verified live on the Space: 9/9 checks (401s, read-only 200s, status unauthenticated). Security review: no findings. |
| C1 slim image | ✅ **done 2026-08-15** | Merge `8d2e8bd`. chromadb/pypdf/text-splitters dropped (rag-only, grep-proven); all 10 direct deps pinned from verified freeze; Dockerfile loses `build-essential`, `COPY data/`, ingest step (image 370MB, builds+boots verified); screenshots PNGs removed from HEAD; README/DEPLOY/CLAUDE RAG claims corrected; docs/SPECS+TESTING/C1.md added. Review: 1 Critical (real run data in TESTING doc) fixed via branch history rewrite pre-merge. **The PNG removal does NOT retire the `space-deploy` dance** — verified 2026-08-15: HF's pre-receive hook scans all pushed history and rejects the historical PNGs; only a `main` history rewrite would fix that, not worth it. |
| F1 persistence | ⏭ **next** | Identity tables only (`users`, `broker_links`, `oauth_pending`) + pytest/Alembic/crypto scaffolding + `portfolio_runnable_config()` tracing-off helper. M1/S1 add their own tables post-C2. No Neon yet — verify on local Docker Postgres; Neon provisioning is an operator task before S1. |
| C2 data spike | queued — **HUMAN GATE** | Operator's real IND Money link is live on prod (admin-secret login, 2026-08-15), so live `networth_*` calls are possible. |
| M1 model + connectors | queued | Blocked on C2 gate. |
| D0 design bake-off | queued — **HUMAN GATE** | 4–5 Fable-built dashboard demos (shadcn/ui, Bloomberg-terminal, +2–3 others); human picks; lock in DECISION.md + plan §2 + memory. Blocks all real dashboard frontend. |
| D1 dashboard | queued | Blocked on D0. Interim: `/portfolio/*` behind the C0 admin secret until F3. |
| S1 snapshots | queued | Calendar-day attribution, 06:00 IST cutoff. |
| F2 clerk | queued | Verify Clerk specifics against current docs first. |
| F3 per-user linking | queued | Includes adopting pre-F3 `user_id="local"` rows and removing the C0 admin gate. |
| F4 per-user Lab state | queued | |
| A1 AI overview | queued | |
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
