# AlphaDesk Deploy Guide

Frontend on Vercel, backend on Hugging Face Spaces (Docker). Covers env vars and
the IND Money OAuth callback wiring so the in-app Connect button works in prod.

## Topology

```
Browser
  -> Vercel        (Next.js frontend, NEXT_PUBLIC_API_URL points at HF)
  -> HF Space      (FastAPI backend, port 7860)
       -> Groq          (LLM)
       -> IND Money MCP (market data, OAuth)
       -> LangSmith     (tracing)
```

The OAuth callback (`/auth/callback`) is served by the backend itself. The
Connect button opens the IND Money login in a popup; IND Money redirects the
popup straight back to the backend, which exchanges the code and stores the
token. The frontend only polls `/auth/status`. So the redirect URI must be the
public backend URL, not the Vercel URL.

---

## 1. Backend -> Hugging Face Spaces

### 1a. Create the Space

1. huggingface.co -> New Space.
2. SDK: **Docker** (blank template). Name e.g. `alphadesk`.
3. Public URL becomes: `https://<user>-alphadesk.hf.space` (note it, call it
   `BACKEND_URL` below).

### 1b. Push the code

The repo root already has a `Dockerfile` (serves `api.main:app` on port 7860).
Push backend + Dockerfile + data to the Space repo:

```bash
git remote add space https://huggingface.co/spaces/<user>/alphadesk
git push space main
```

The Dockerfile copies `backend/` and `data/`, installs `requirements.txt`, and
bakes the ChromaDB index at build time (`python -m rag.ingest`). RAG works with
no extra steps. Empty `data/nse_docs` is fine - ingest is a no-op.

### 1c. Backend env vars (Space -> Settings -> Variables and secrets)

Mark anything sensitive as a **Secret**.

| Var | Value | Notes |
| --- | --- | --- |
| `GROQ_API_KEY` | your Groq key | secret; omit only if using an OpenAI-compatible endpoint |
| `OPENAI_API_KEY` | compatible provider key | secret; required when using `OPENAI_BASE_URL` / `OPENAI_COMPATIBLE_MODEL` |
| `OPENAI_BASE_URL` | compatible provider base URL | optional; enables OpenAI-compatible LLM mode |
| `OPENAI_COMPATIBLE_MODEL` | compatible provider model | optional; enables OpenAI-compatible LLM mode |
| `IND_MONEY_MCP_URL` | `https://mcp.indmoney.com/mcp` | the MCP server |
| `IND_MONEY_AUTH_REDIRECT` | `https://<user>-alphadesk.hf.space/auth/callback` | **critical** - must be the public backend URL |
| `CORS_ALLOW_ORIGINS` | `https://alphadesk.ishanavasthi.in,https://<your-vercel>.vercel.app` | comma-separated frontend origins |
| `CORS_ALLOW_ORIGIN_REGEX` | `https://[a-z0-9-]+\.vercel\.app` | optional - allows Vercel preview deploys |
| `LANGCHAIN_API_KEY` | your LangSmith key | secret, recommended |
| `LANGCHAIN_TRACING_V2` | `true` | CLAUDE.md says keep tracing on |
| `LANGCHAIN_PROJECT` | `alphaDesk` | |
| `LANGSMITH_ENDPOINT` | region endpoint | e.g. `https://eu.api.smith.langchain.com` |
| `LANGCHAIN_ENDPOINT` | same as above | both vars needed |
| `BROKER` | leave blank | paper trading only |
| `ALPHADESK_ADMIN_SECRET` | `openssl rand -base64 32` output | **secret, required** — guards `/auth/login` + `/auth/logout` (header `x-alphadesk-admin-secret`); with it unset those endpoints lock (fail-closed) |
| `ALPHADESK_SINGLE_TENANT` | **never set on the Space** | local-dev-only flag; setting it here reopens the C0 hole |

Localhost origins stay allowed automatically, so local dev keeps working.

### 1d. Reconnecting IND Money after a restart

HF free Spaces have an **ephemeral filesystem and sleep when idle**. The token
cache (`backend/.ind_money_token.json`) and the in-memory run registry are lost
on every restart.

Since C0, the `IND_MONEY_OAUTH_*` env fallback **no longer authenticates in
production** — ambient credentials only load under `ALPHADESK_SINGLE_TENANT`,
which must stay unset on the Space (any visitor's queries would run on the
operator's token; per-user links land in F3). Remove those five secrets from
the Space if they are still set; they are dead weight.

After a restart, the operator re-connects via the gated login:

```bash
curl -s -X POST https://<user>-alphadesk.hf.space/auth/login \
  -H "x-alphadesk-admin-secret: $ALPHADESK_ADMIN_SECRET"
# -> {"authorization_url": "..."}  — open it in a browser and log in,
# or click Connect in the frontend (it will 401 without the header; use curl).
```

Restarts are rare — `.github/workflows/keepalive.yml` pings the Space every 6h
against a 48h sleep threshold. Durable per-user tokens (Postgres, encrypted)
arrive with F3.

Note: stored analyses and the paper watchlist are in-memory regardless - they
survive a browser refresh but not a backend restart. Known limitation; a DB is
future work.

---

## 2. Frontend -> Vercel

1. Import the repo in Vercel. Set **Root Directory = `frontend`** (the Next.js
   app is in a subfolder).
2. Framework auto-detects Next.js. Build `next build`, no overrides needed.
3. Env var (Project -> Settings -> Environment Variables):

   | Var | Value |
   | --- | --- |
   | `NEXT_PUBLIC_API_URL` | `https://<user>-alphadesk.hf.space` |

   No trailing slash needed - `lib/api.ts` strips it. This is a build-time
   `NEXT_PUBLIC_*` var, so **redeploy after changing it**.
4. Deploy.

### 2a. Custom domain

1. Vercel -> Project -> Settings -> Domains -> add `alphadesk.ishanavasthi.in`.
2. Add the CNAME (or A) record Vercel shows at your DNS host.
3. After it goes live, make sure that exact origin is in the backend's
   `CORS_ALLOW_ORIGINS`. Restart the Space if you changed it.

---

## 3. Wire-up checklist (the cross-references that bite)

These three must agree or auth/data calls fail:

- `IND_MONEY_AUTH_REDIRECT` (backend) = `<BACKEND_URL>/auth/callback`, exact.
- `CORS_ALLOW_ORIGINS` (backend) contains the live frontend origin
  (`https://alphadesk.ishanavasthi.in`), exact scheme + host, no trailing slash.
- `NEXT_PUBLIC_API_URL` (frontend) = `<BACKEND_URL>`, exact.

The IND Money MCP uses **dynamic client registration** - the redirect URI is
registered fresh on each Connect from `IND_MONEY_AUTH_REDIRECT`, so there is no
allow-list to pre-register on IND Money's side. Just set that env correctly.

---

## 4. Verify

1. Open `https://<user>-alphadesk.hf.space/` -> `{"service":"AlphaDesk",...}`.
2. Open the frontend domain. DevTools -> Network: `/auth/status` returns 200, no
   CORS error. CORS error here means `CORS_ALLOW_ORIGINS` is wrong.
3. Click **Connect IND Money** -> popup -> log in -> popup shows
   "IND Money connected." -> badge flips to authenticated. Failure here is
   almost always a wrong `IND_MONEY_AUTH_REDIRECT`.
4. Run a query (e.g. "analyse NDTV, Zee, Sun TV"). Pipeline animates over SSE,
   recommendation cards render, Approve adds to the paper watchlist.
5. Refresh on `/a/<run_id>` - analysis persists (until next backend restart).

---

## 5. Env var quick reference

**Backend (HF Space):** `GROQ_API_KEY`, `IND_MONEY_MCP_URL`,
`IND_MONEY_AUTH_REDIRECT`, `CORS_ALLOW_ORIGINS`, `CORS_ALLOW_ORIGIN_REGEX`
(optional), `LANGCHAIN_API_KEY`, `LANGCHAIN_TRACING_V2`, `LANGCHAIN_PROJECT`,
`LANGSMITH_ENDPOINT`, `LANGCHAIN_ENDPOINT`, `BROKER` (blank),
`ALPHADESK_ADMIN_SECRET` (secret). Do **not** set `ALPHADESK_SINGLE_TENANT` or
the `IND_MONEY_OAUTH_*` credentials on the Space — since C0 the latter only
work locally under single-tenant mode.

**Frontend (Vercel):** `NEXT_PUBLIC_API_URL`.
