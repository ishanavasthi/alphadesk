# AlphaDesk Deploy Guide (v2)

Frontend on Vercel, backend on Hugging Face Spaces (Docker), database on Neon
(Postgres), identity via Clerk. This covers every env var the deployed code
**requires**, the IND Money OAuth callback wiring, and the go-live sequence
(the site ships gated behind a flag until you flip it).

> The overnight build wired the live deployment already; `docs/MORNING.md`
> records the exact state and the go-live steps. This file is the durable
> reference — if the two disagree, trust the running state + MORNING.md and
> fix this file.

## Topology

```
Browser
  -> Vercel        (Next.js frontend; NEXT_PUBLIC_API_URL -> HF, Clerk keys)
  -> HF Space      (FastAPI backend, port 7860)
       -> Neon          (Postgres: users, links, snapshots, watchlist)
       -> Clerk         (identity — JWT verified networklessly via JWKS)
       -> Groq          (Lab / research LLM)
       -> OpenAI        (portfolio AI overview)
       -> IND Money MCP (market data + portfolio, per-user OAuth)
       -> LangSmith     (tracing — research graph only; portfolio graph off)
  GitHub Actions   (snapshot.yml -> POST /internal/snapshot nightly)
```

The OAuth callback (`/auth/callback`) is served by the backend. Since F3 every
IND Money link is **per user**, bound to the signed-in Clerk identity, with the
refresh token Fernet-encrypted in Postgres. There is no shared/ambient
credential and no admin-secret path (both removed at F3/L1).

---

## 1. Database — Neon (Postgres)

Required — HF Spaces disk is ephemeral.

1. neon.tech -> new project -> copy the connection string
   (`postgresql://…?sslmode=require`). The app's async engine translates
   `sslmode` for asyncpg automatically; paste it verbatim.
2. Run migrations against it once (and after any future migration):
   ```bash
   cd backend
   DATABASE_URL="postgresql://…?sslmode=require" alembic upgrade head
   ```
3. Set `DATABASE_URL` as a Space secret (below).

## 2. Identity — Clerk

1. clerk.com -> create an application. Note the instance
   (`<slug>.clerk.accounts.dev`).
2. **Enable Waitlist mode:** Configure -> Restrictions -> Sign-up mode ->
   Waitlist (not exposed via API — manual toggle).
3. Keys: `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` + `CLERK_SECRET_KEY` go on
   **Vercel**; the backend needs only the public JWKS URL + issuer +
   authorized parties (below) — it holds **no** Clerk secret.

## 3. Backend — Hugging Face Spaces

SDK: **Docker** (blank). The repo-root `Dockerfile` serves `api.main:app` on
7860, copies `backend/` + installs `requirements.txt` only (RAG unplugged
since C1 — no `data/`, no chromadb, no apt layer). Deploy: the repo keeps
GitHub history that HF's binary policy rejects, so the Space is pushed from the
`space-deploy` snapshot branch — see `docs/STATUS.md` "Deploy notes".

### Backend env vars (Space -> Settings -> Variables and secrets)

Mark secrets as **Secret**.

| Var | Value | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Neon connection string | secret; **required** — no DB ⇒ links/snapshots/watchlist don't persist |
| `TOKEN_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"` | secret; **required** — encrypts broker refresh tokens; first Connect fails without it |
| `CLERK_JWKS_URL` | `https://<slug>.clerk.accounts.dev/.well-known/jwks.json` | **required** |
| `CLERK_ISSUER` | `https://<slug>.clerk.accounts.dev` | **required** |
| `CLERK_AUTHORIZED_PARTIES` | the live frontend origin(s), comma-sep (`https://alphadesk.ishanavasthi.in`) | **required — unset ⇒ 503 on every auth** |
| `ALPHADESK_OPERATOR_EMAIL` | your Clerk sign-in email | one-off: adopts pre-F3 `local` snapshot history to your account on first sign-in; unset ⇒ adoption never runs |
| `CRON_SECRET` | `openssl rand -base64 32` | secret; guards `POST /internal/snapshot|prune`; also a **GitHub Actions secret** |
| `OPENAI_API_KEY` | your OpenAI key | secret; the portfolio AI overview (A1). Set a provider-side budget cap in the OpenAI dashboard |
| `GROQ_API_KEY` | your Groq key | secret; the Lab / research agents |
| `IND_MONEY_MCP_URL` | `https://mcp.indmoney.com/mcp` | the MCP server |
| `IND_MONEY_AUTH_REDIRECT` | `https://<user>-alphadesk.hf.space/auth/callback` | **critical** — exact public backend URL |
| `CORS_ALLOW_ORIGINS` | `https://alphadesk.ishanavasthi.in,https://<your-vercel>.vercel.app` | comma-separated frontend origins |
| `FRONTEND_BASE_URL` | `https://alphadesk.ishanavasthi.in` | optional — where `/auth/callback` sends the browser after linking. Defaults to the **first** `CORS_ALLOW_ORIGINS` entry, so set it only when that first entry is not the site users are on. Unset *and* no CORS origins ⇒ the callback renders its standalone page instead of redirecting (local single-tenant dev) |
| `CORS_ALLOW_ORIGIN_REGEX` | `https://[a-z0-9-]+\.vercel\.app` | optional — Vercel preview deploys |
| `LANGCHAIN_API_KEY` | LangSmith key | secret; **research-graph tracing only** — the portfolio graph is tracing-off at config level regardless |
| `LANGCHAIN_TRACING_V2` | `true` | on for the research graph |
| `LANGCHAIN_PROJECT` / `LANGSMITH_ENDPOINT` / `LANGCHAIN_ENDPOINT` | project + region endpoints | |
| `BROKER` | leave blank | paper only — no real orders ever |

**Must stay UNSET on the Space:** `ALPHADESK_SINGLE_TENANT` (local-dev only — if
set in prod it fail-opens every request to the operator identity),
`ALPHADESK_ADMIN_SECRET` (dead since L1 — the interim gate was removed),
`OPENAI_BASE_URL` / `OPENAI_COMPATIBLE_MODEL` (only meaningful with an explicit
`provider=compat`; leave them unset and use the per-family vars below instead).

### Swapping provider / model per family

The two LLM families are configured independently, each by its **own** vars.
Leave everything here unset for the shipped defaults — AI Overview on real
OpenAI `gpt-4o-mini`, Lab on Groq at its historical per-agent tiers. Valid
providers: `openai`, `groq`, `openrouter`, `compat`; a typo raises rather than
silently billing the wrong provider.

| Var | Example | Notes |
| --- | --- | --- |
| `OVERVIEW_PROVIDER` | `openrouter` | AI Overview only. Unset ⇒ `openai` |
| `OVERVIEW_MODEL` | `stealth/ox-alpha` | unset ⇒ `gpt-4o-mini`. Wins over the legacy `OPENAI_OVERVIEW_MODEL` |
| `LAB_PROVIDER` | `openrouter` | Lab only. Unset ⇒ the ambient default, which is Groq |
| `LAB_MODEL` | `stealth/ox-alpha` | blanket: all four Lab agents |
| `LAB_SCANNER_MODEL` / `LAB_RESEARCH_MODEL` / `LAB_ANALYST_MODEL` / `LAB_RISK_MODEL` | | per-agent, beats `LAB_MODEL`. Unset ⇒ the historical tier |
| `OPENROUTER_API_KEY` | `sk-or-v1-…` | secret; **required** for `provider=openrouter`. Never falls back to `OPENAI_API_KEY` |

Setting only `LAB_PROVIDER` keeps each agent's historical model id — swapping
the route never silently rewrites the tiering. The two families are fully
independent: moving the Lab does not move the Overview.

**Model must support tool-calling.** Structured output is pinned to
`method="function_calling"` (`agents.llm.structured`) because strict
`json_schema` is not universal — a model that lacks it answers in prose, the
Analyst swallows the parse error as "skip this stock", and the run comes back
empty with no error anywhere. Check `supported_parameters` includes `tools` on
[openrouter.ai/models](https://openrouter.ai/models) before pointing the Lab at
a new model.

### Reconnecting IND Money

Per-user now: sign in (Clerk) and click **Connect** — you're routed through a
consent screen, then IND Money's OAuth, and the link (encrypted) is stored in
Postgres, durable across restarts. There is no admin-header curl flow anymore.

## 4. Frontend — Vercel

Root Directory = `frontend`. Env vars (Project -> Settings -> Environment
Variables):

| Var | Value | Notes |
| --- | --- | --- |
| `NEXT_PUBLIC_API_URL` | `https://<user>-alphadesk.hf.space` | no trailing slash |
| `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` | Clerk publishable key | **required when auth is on** |
| `CLERK_SECRET_KEY` | Clerk secret key | secret; **required when auth is on** |
| `NEXT_PUBLIC_AUTH_ENABLED` | see go-live below | the launch switch |

The repo commits `frontend/.env.production` with `NEXT_PUBLIC_AUTH_ENABLED=true`
(the intended launched state), but **Vercel dashboard env vars override that
file**, so you gate the actual deploy from the dashboard.

> ### ⚠ Never set `CLERK_SECRET_KEY` as `NEXT_PUBLIC_*`, and never commit keys
> `NEXT_PUBLIC_*` values are inlined into the public bundle. The publishable key
> is meant to be public; the secret key is not. Both belong in Vercel env vars
> (and `frontend/.env.local`, gitignored), never in a committed file.

### Go-live sequence (gated until you're ready)

1. IND Money re-login (your own portfolio; proves the per-user flow).
2. Clerk Waitlist mode enabled (§2).
3. Clerk keys set on Vercel; `OPENAI_API_KEY` on the Space; OpenAI budget cap set.
4. Set Vercel `NEXT_PUBLIC_AUTH_ENABLED=true` (or remove a `false` override) and
   redeploy — the site goes behind Clerk Waitlist. **With auth on you MUST have
   real Clerk keys on Vercel** or the browser hits Clerk's `host_invalid` page.
5. Approve your first users from the Clerk dashboard.

Until step 4 the deployed site runs with the flag **off**: public landing +
`/demo` (fully rendered from committed fixtures, no auth, no LLM), no sign-in
wall — the safe pre-launch state.

### Custom domain

Vercel -> Domains -> add `alphadesk.ishanavasthi.in`; add the DNS record; then
ensure that exact origin is in the backend `CORS_ALLOW_ORIGINS` **and**
`CLERK_AUTHORIZED_PARTIES`.

## 5. Snapshots — GitHub Actions

`.github/workflows/snapshot.yml` calls `POST /internal/snapshot` nightly
(23:45 IST + a retry). Needs repo **secret** `CRON_SECRET` (matching the Space)
and repo **variable** `BACKEND_URL`. A run with no linked users is green with
`skipped`. GitHub disables scheduled workflows after 60 days of repo inactivity
— the staleness banner surfaces a stalled job.

## 6. Wire-up checklist (the cross-references that bite)

- `IND_MONEY_AUTH_REDIRECT` (backend) = `<BACKEND_URL>/auth/callback`, exact.
- `CORS_ALLOW_ORIGINS` (backend) ⊇ the live frontend origin, exact.
- `CLERK_AUTHORIZED_PARTIES` (backend) ⊇ the live frontend origin, exact.
- `NEXT_PUBLIC_API_URL` (frontend) = `<BACKEND_URL>`, exact.
- `CRON_SECRET` identical on the Space and as a GitHub secret.

## 7. Verify

1. `https://<user>-alphadesk.hf.space/` -> service JSON.
2. `https://<user>-alphadesk.hf.space/auth/status` -> 200 (unauthenticated).
3. Frontend `/demo` -> full dashboard, no network to an authed/LLM endpoint.
4. With auth on: sign in (Clerk), Connect (consent -> OAuth), `/portfolio`
   renders your holdings, the AI overview streams, `DELETE /account` removes
   everything.
