# Config snapshot — 2026-09-11, before the all-deepseek switch

Taken immediately before pointing **every** LLM call (Lab *and* AI Overview) at
`deepseek/deepseek-v4.1-flash` via OpenRouter. This is the rollback record: to
undo the switch, restore the four variables in §2 and redeploy.

No secret **values** are recorded here — the HF API never returns them. Only
names, so you know which secrets existed and what to re-check.

## 1. Space identity

| | |
| --- | --- |
| Space | `heyavasthi/alphadesk` |
| Public URL | `https://heyavasthi-alphadesk.hf.space` |
| SDK / hardware | Docker / `cpu-basic` |
| Runtime stage at snapshot | `RUNNING` |
| Space last modified | 2026-09-04 08:51:03 UTC |
| Deploy path | `space-deploy` snapshot branch (see `docs/STATUS.md` "Deploy notes") |

## 2. Space **variables** before the change (plaintext, restorable)

```
BROKER                   =                                   # blank = paper-only
CORS_ALLOW_ORIGINS       = https://alphadesk.ishanavasthi.in
FRONTEND_BASE_URL        = https://alphadesk.ishanavasthi.in
IND_MONEY_MCP_URL        = https://mcp.indmoney.com/mcp
LAB_MODEL                = glm-5.3-flash                     # <-- CHANGED
LAB_PROVIDER             = bai                               # <-- CHANGED
LANGCHAIN_PROJECT        = alphaDesk
LANGCHAIN_TRACING_V2     = true
LANGSMITH_ENDPOINT       = https://eu.api.smith.langchain.com
OVERVIEW_DAILY_GLOBAL_MAX= 500
OVERVIEW_MODEL           = glm-5.3-flash                     # <-- CHANGED
OVERVIEW_PROVIDER        = bai                               # <-- CHANGED
```

**The four lines marked CHANGED are the entire rollback.** Set them back to the
values above and the Space returns to B.ai for both families. Nothing else in
this file needs touching to revert.

## 3. Space **secrets** present at snapshot (names only)

```
ALPHADESK_ADMIN_SECRET      CLERK_SECRET_KEY          LANGCHAIN_API_KEY
ALPHADESK_OPERATOR_EMAIL    CORS_ALLOW_ORIGIN_REGEX   NVIDIA_API_KEY
BAI_API_KEY                 CRON_SECRET               OPENAI_API_KEY
BAI_BASE_URL                DATABASE_URL              OPENROUTER_API_KEY
CLERK_AUTHORIZED_PARTIES    GROQ_API_KEY              TOKEN_ENCRYPTION_KEY
CLERK_ISSUER                IND_MONEY_AUTH_REDIRECT
CLERK_JWKS_URL
```

Notes:
- `BAI_API_KEY` / `BAI_BASE_URL` are **left in place** deliberately. They cost
  nothing unused and are what makes the §2 rollback a pure variable change.
- `ALPHADESK_ADMIN_SECRET` is dead as of L1 (no admin header authenticates
  anything). Present but inert; worth deleting in a separate cleanup.
- `OPENROUTER_API_KEY` was already set but its value is unreadable, so it could
  not be verified against the funded account. It is **overwritten** as part of
  this change — see §5.

## 4. Local `backend/.env` LLM config before the change

```
OVERVIEW_PROVIDER = bai                  OVERVIEW_MODEL = glm-5.3-flash
LAB_PROVIDER      = openrouter           LAB_MODEL      = deepseek/deepseek-v4.1-flash
OVERVIEW_DAILY_GLOBAL_MAX = 500
```

The Lab half was already switched earlier in this session; the pre-session state
is preserved in `backend/.env.bak.b11`.

## 5. OpenRouter keys (2026-09-11)

Three keys exist in `~/.zshrc`. They were **swapped** this session so the funded
one is the default — `~/.zshrc.bak.swap.*` holds the previous arrangement.

| Variable (after swap) | Fingerprint | Balance |
| --- | --- | --- |
| `OPENROUTER_API_KEY`, `OR_KEY` | `sk-or-v1-3ba…e427` | **$125.57** ($160 credited, $34.43 used) |
| `OPENROUTER2_API_KEY` | `sk-or-v1-57b…4fda` | $0.00, never used |
| `OPENROUTER3_API_KEY` | `sk-or-v1-942…2485` | **−$0.23**, unfunded |

`sk-or-v1-942…2485` was previously `OPENROUTER_API_KEY` and is the cause of the
retracted "blocked on billing" finding in `docs/SPECS/B11.md` §6.6 — it shadowed
the funded key in `backend/.env` because `load_dotenv()` defaults to
`override=False`.

## 6. Standing risk at the time of this snapshot

`deepseek/deepseek-v4.1-flash` is being deployed **unmeasured**. Its
`confidence_probe` run was still in flight when the switch was made. Every other
model in the B11 bake-off was measured before adoption, and the central finding
of that card is that `a2f2f74` broke the desk precisely by swapping a Lab model
that had only been checked for schema round-trip. If the probe comes back poorly,
§2 is the rollback.
