# AlphaDesk — Deferred features & ideas

Not scoped into the current plan. Everything here is parked deliberately, with
the reason it's parked and what has to be true before it's picked up.
`V2_PLAN.md` is the plan of record; this file is the queue behind it.

Grilling session of 2026-08-14 settled the frame these are judged against:
public but **waitlist-gated**; **one normalized portfolio model** with per-source
connectors; **descriptive analytics only** in v2 — scenario projection is itself
deferred to this backlog (no forward forecasts, no instrument-level advice on
real holdings; `V2_PLAN.md` §8.3 is the wording of record).

---

## Deferred connectors

### Groww
**Status:** deferred entirely — no Groww account to test against.

Verified 2026-08-14 (so it doesn't get re-researched):

- `https://mcp.groww.in/mcp` is a live MCP server. `GET` unauthenticated → 401;
  `/.well-known/oauth-protected-resource` →
  `{"resource":"https://mcp.groww.in/","authorization_servers":["https://api.groww.in/"]}`.
- Authorization server metadata at `https://api.groww.in/.well-known/oauth-authorization-server`:
  - `authorization_endpoint`: `https://groww.in/oauth/authorize`
  - `token_endpoint`: `https://api.groww.in/oauth2/v1/token`
  - `registration_endpoint`: `https://api.groww.in/oauth2/v1/register` (DCR supported)
  - `code_challenge_methods_supported`: `["plain","S256"]`
  - `token_endpoint_auth_methods_supported`: `["client_secret_basic"]`
- **`grant_types_supported`: `["authorization_code"]` only — no `refresh_token`.**
  A Groww link cannot silently refresh; it expires and the user must re-link.
  The connector abstraction must therefore model *link health* without assuming
  refreshability, and the UI needs a "re-link required" state.
- No `scopes_supported` and no `revocation_endpoint` advertised. Unlike IND
  Money there may be nothing to call on unlink — decide whether that's
  acceptable before shipping.
- `token_endpoint_auth_methods` is `client_secret_basic`, where the IND Money
  code posts `client_secret` in the body — the shared OAuth helper must support
  both.

**Pick up when:** a test Groww account exists, and the normalized model +
connector interface have shipped and survived at least one real user.

**Separate, do not confuse:** Groww's *Trading API* (`groww.in/trade-api`) is a
different product — API key + TOTP, and it **places orders**. All the public
"Groww MCP" GitHub projects wrap that, not the OAuth MCP above. Storing an
order-capable credential for other people is a risk class this project has not
accepted. If it's ever considered, it needs its own written decision.

### Broker statement / CAS import
Chosen over per-broker integrations as the coverage mechanism: one parser
(NSDL/CDSL CAS, contract notes) covers Zerodha, Angel, Groww, and anything else,
with **zero third-party credentials held**. Also the natural home for the FD gap
below.

Known cost: CAS PDFs are password-protected, format-drifting, and per-depository.
Non-trivial parser + a "we may have mis-read your statement" review step.

---

## User-supplied holdings

### Manual investments
"People can add their own investment too." Anything the connectors can't see:
FDs, physical gold, unlisted equity, real estate, EPF held elsewhere.

Design constraints already agreed: manual rows are first-class rows in the same
normalized model (same aggregates, same AI metrics), which forces answers to
who computes their current value and how double-counting against a broker row is
prevented.

### FD tracking
IND Money's MCP is unreliable for FDs (user-reported). FDs are the clearest case
for manual entry because their value is *computable*, not quoted: principal +
rate + compounding + start/maturity date → accrued value, no price feed needed.
Good first manual asset type for exactly that reason.

---

## Analytics & AI

### Portfolio projection
Scoped as **scenario arithmetic, not forecast**: user-set CAGR assumptions
(e.g. 8/12/15%), corpus over time, SIP contributions included. Labelled as
arithmetic on chosen assumptions. Explicitly *not* an AI prediction of returns.

### Goal tracking
"Retirement by 2050 needs ₹X; you're at Y% of the run-rate." Reuses the
projection engine and the snapshot history. High perceived value, low new
machinery.

### Allocation-drift alerts
User sets a target allocation; snapshots already run daily; alert when drift
exceeds a band. Cheap once `portfolio_snapshots` exists, and it's the feature
that gives daily snapshots a *user-facing* reason to exist beyond a trend line.

### Tax-lot / capital-gains view
Realised vs unrealised, STCG/LTCG split, ITR season utility. Needs transaction
history the current tools may not expose — gated on the data spike.

---

## Cut or heavily deferred

### "Worldmonitor" (macro / global market context, Indian lens)
A different product wearing the same login. It shares no data model with the
portfolio analyzer and would be a third unrelated page. Revisit only if it can
be expressed *through* the portfolio ("your portfolio's exposure to crude" is
portfolio analytics; "here is a world markets dashboard" is not).

### Portfolio-aware research ("what should I buy given my holdings")
Was listed as v2+ scope. Now blocked on product grounds, not effort: fusing
instrument-level recommendations with a real portfolio is the thing the
descriptive-only framing exists to avoid. The research desk stays a labelled
paper simulation.

### MF screener (`get_mf_by_category`), US stocks (`get_us_stocks_details`), liabilities/EMI, options analytics
Tools exist on the IND Money MCP; all out of scope. Keep the connector wrappers
extensible so they slot in without a refactor.

---

## Live order placement (broker execution)

**Status:** deferred — and not merely on effort. It conflicts with the product
framing settled on 2026-08-14.

What exists today: `backend/broker/base.py` defines `BrokerAdapter` (abstract
`place_order(action) -> OrderResult`) plus `load_broker()`, which reads the
`BROKER` env var and returns `None` because no concrete adapter ships. The
Execution agent (`backend/agents/execution.py:57`) already calls
`broker.place_order(...)` when an adapter is present and otherwise logs
"Broker integration not configured" and writes to the paper watchlist. So the
seam is built and dormant — nothing needs removing.

**Why it stays dormant.** The product is now a *descriptive* portfolio analyzer
with scenario projection, explicitly not instrument-level advice on real
holdings, and the research desk is a labelled simulation. Wiring real order
placement to the output of an LLM pipeline that emits `buy`/`avoid` with a
confidence score inverts every one of those decisions at once — and does it for
other people's money, on a public deployment.

**What would have to be true to revisit:** a deliberate reversal of the
descriptive-only framing with the regulatory position worked out first (SEBI
IA/RA), a real per-order human confirmation that is not the existing
`interrupt_before` graph gate, an audit trail, and a broker credential story
that does not involve storing order-capable secrets for strangers.

Keep the `BrokerAdapter` seam as-is. `BROKER` stays unset in every deployed
environment.

---

## Configurable model routing + NVIDIA NIM as a second provider

**Status:** deferred, but with a live trigger — on 2026-08-16 Groq decommissioned
`llama-3.3-70b-versatile`, which the Analyst and Risk Manager had **hardcoded**
(`ANALYST_MODEL`, `RISK_MODEL`). The swap to `openai/gpt-oss-120b` was a code
change and a redeploy, because there is no way to name a model from config. The
next such notice should be a `.env` edit, not a commit.

Two stages, in this order — the second is worthless without the first.

**Stage 1 — models configurable via `.env`.**
Every per-agent model constant (`SCANNER_MODEL`, `RESEARCH_MODEL`,
`ANALYST_MODEL`, `RISK_MODEL`, and the portfolio-overview models) becomes an env
override with the current value as its default, so an unset env keeps today's
behaviour exactly. Add NVIDIA NIM (`https://integrate.api.nvidia.com/v1`) as a
named provider in `get_chat_llm` — it is OpenAI-compatible, so it is closer to a
third `Provider` literal than to new transport code.

Design constraints, because this touches the one helper that A1 hardened:

- `provider=` must keep winning over the environment. The whole point of
  `agents/llm.py` is that a stray env var cannot reroute the portfolio agents
  off real OpenAI, and per-agent tiering in the Lab cannot silently collapse to
  one model. A config surface that re-opens that hole is a regression, not a
  feature — the existing `test_llm_routing.py` assertions are the contract.
- Prefer explicit per-agent vars (`ALPHADESK_ANALYST_MODEL=...`) over a single
  global override. One var that sets every agent's model *is* the collapsed
  tiering A1 spent effort preventing.
- The Analyst and Risk Manager both use `.with_structured_output`, and the
  Analyst's `confidence` feeds hard guardrail thresholds (0.70 REJECT / 0.75
  FLAG). Any model reachable from config must support structured output, and a
  swap needs a real pipeline run to check the confidence distribution — a green
  `pytest` proves nothing here, since no test exercises those two agents.
- Validate the model name at startup, not mid-pipeline: a typo in `.env` should
  fail the boot, not surface as a failed run three agents deep.

**Stage 2 — model switching in the frontend.**
Only after Stage 1 exists, and it needs its own plan. Open questions to settle
*before* building it: is the choice per-user (persisted where?) or per-run; is it
exposed for the Lab only, or for the portfolio overview too — where model choice
changes the cost and quality of *financial* output; and who absorbs the spend
when a user picks the expensive model. Related: **Bring-your-own LLM key** below,
which answers that last question by moving the bill to the user. If both ship,
they should ship as one coherent surface rather than two unrelated selectors.

**Pick up when:** the next model deprecation notice lands, or a second provider
is actually wanted for cost/latency reasons — whichever comes first.

---

## Small, cheap, not yet scheduled

### `segments` on `get_indian_stocks_details`
Verified against the live tool schema (`indmcp` v1.26.0): the signature is
`get_indian_stocks_details(ind_keys*:array, segments:?)` — the same optional
`segments` parameter its US counterpart has. The Research agent currently never
passes it, so analyst ratings and news sentiment are available and unused.
Cheap win for the Lab section whenever it gets attention. Not v2 scope.

### Bring-your-own LLM key
Let a user supply their own OpenAI (or compatible) API key in the frontend and
run the whole workflow on it, instead of the project's shared credits.

**Status:** deferred. Invite-only means a small, known user set, and project
credits cover it. Until then all users run on the project key; testing uses those
credits conservatively.

**Why it's wanted:** removes the project's LLM spend as a scaling ceiling and
removes the shared-quota abuse surface entirely — each user's usage is bounded by
their own billing.

**Design constraints when picked up (this is a credential feature, not a form
field):**
- Prefer **never persisting it server-side**: hold it in the browser session and
  send it per-request. If it must persist, it is Fernet-encrypted exactly like
  broker refresh tokens, never logged, never returned to the frontend.
- Either way the key **transits your backend**, so you can spend the user's
  money. That needs an explicit consent screen and a visible per-user usage
  readout, not a silent text input.
- Validate with one cheap call at entry so a bad key fails at setup, not
  mid-pipeline.
- Falling back to the project key when the user's key fails must be a deliberate,
  disclosed choice — never an invisible default.
- Privacy policy consequence: with a user's own key, prompts go to *their*
  provider account under *their* retention terms. The policy text differs between
  the two modes and must say which applies.

### Third-party error tracking
Sentry (or equivalent) on backend + frontend. Deferred in v2: with fewer than ten
waitlist-approved users you can ask them directly what broke, and structured
logging covers the rest.

**Why it isn't free to add:** Sentry captures request context, and this app's
requests carry financial data — it would need aggressive scrubbing (no request
bodies, no query params on portfolio routes) and would become a **third
subprocessor** named in the privacy policy alongside Groq and OpenAI.

**Pick up when:** user count outgrows "ask them directly", or before open sign-up.
