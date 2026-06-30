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
| `GROQ_API_KEY` | your Groq key | secret |
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

Localhost origins stay allowed automatically, so local dev keeps working.

### 1d. (Recommended) Durable IND Money auth across restarts

HF free Spaces have an **ephemeral filesystem and sleep when idle**. The token
cache (`backend/.ind_money_token.json`) and the in-memory run registry are lost
on every restart. Two options:

- **Quick:** after each restart, click Connect IND Money again.
- **Durable:** do one local OAuth login, copy the refresh token from
  `backend/.ind_money_token.json`, and set these Space secrets so the backend
  re-mints access tokens on boot with no manual reconnect:

  | Var | From the cache file |
  | --- | --- |
  | `IND_MONEY_OAUTH_REFRESH_TOKEN` | `refresh_token` |
  | `IND_MONEY_OAUTH_CLIENT_ID` | `client_id` |
  | `IND_MONEY_OAUTH_CLIENT_SECRET` | `client_secret` |
  | `IND_MONEY_OAUTH_TOKEN_URL` | `token_url` |
  | `IND_MONEY_OAUTH_SCOPE` | `portfolio:read` |

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
`LANGSMITH_ENDPOINT`, `LANGCHAIN_ENDPOINT`, `BROKER` (blank), and optionally the
`IND_MONEY_OAUTH_*` set for durable auth.

**Frontend (Vercel):** `NEXT_PUBLIC_API_URL`.
