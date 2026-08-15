# Auth & database providers — research record

**Status: no change. Clerk stays, Neon stays, `V2_PLAN.md` §2 is untouched.**
This document exists to record *why*, and what the alternatives actually look
like as of 2026-08-16, so the question does not have to be re-researched a
third time.

Written 2026-08-16, before F2 (Clerk identity) was started. Everything here was
verified live against vendor documentation on 2026-08-15/16 — not recalled.
Claims that could **not** be verified are flagged inline as such. Prices and
free-tier limits move; re-check anything cost-sensitive before acting on it.

## Why this document exists

The Clerk-vs-Better-Auth question was argued and settled during the v2 design
reviews (2026-08-14/15), and the verdict was written into `v2brief.md` §2
specifically so the decision "doesn't look arbitrary six weeks from now."

`v2brief.md` was gitignored, is superseded by `V2_PLAN.md`, and is no longer on
disk. `V2_PLAN.md` contains **zero mentions of Better Auth or Auth.js** — only
the decision itself, plus the reasoning for rejecting IND Money as an identity
provider. So the rationale was lost in exactly the way it was meant to prevent,
and the question was re-asked six weeks later.

That is the actual lesson here, independent of which provider wins: **a decision
recorded in a gitignored file is not recorded.** This file is in git.

## The decision, and what was originally traded

**Clerk**, on the grounds that it was faster to ship. The recorded trade was:

| | Clerk | Better Auth |
| --- | --- | --- |
| Advantage | First-party Python SDK, prebuilt sign-in UI, no email deliverability to wire. ~half a day saved on a 1–2 day project. | Its user table *is* your `users` table — real FK + cascade from `broker_links`, one migration story, no webhook sync drift, no user PII on a third party. |

The verdict was recorded as "a genuine preference fork, not a right answer,"
with an explicit revisit trigger: **PII residency, or wanting portability off
Vercel.**

Also settled then, and still true: **IND Money cannot be the identity
provider.** Its discovery document is plain OAuth 2.0 — no `userinfo_endpoint`,
no `id_token`, no `jwks_uri` — so there is no stable subject to key a user row
on. It can only ever be a *linked credential*. See `V2_PLAN.md` §2.

## What re-verification changed

Three things moved since the original decision, and all three point the same
way.

**Clerk's free tier grew 5×.** It went from 10,000 to **50,000 MRU on
2026-02-05**. The cost argument that might have favoured Better Auth is gone at
our scale.

**Both of F2's flagged-as-unverified assumptions now check out.** The F2 card
says the Clerk specifics are "Likely, not repo-verified" and tells the agent to
check them first. They are now checked — see the Clerk section below. Waitlist
mode is real and free; `clerk-backend-api` is the right package and is current.

**A third option appeared that did not exist when the decision was made.** Neon
rebuilt Neon Auth on top of Better Auth ("Managed Better Auth"), which collapses
the original trade — you get Better Auth's own-your-users-table advantage
without self-hosting it. It is the best-argued alternative, and it loses on one
specific thing. See below.

## Option 1 — Clerk (chosen)

Verified 2026-08-15/16.

**Pricing.** Hobby/free: **50,000 MRU per app**, unlimited apps, raised from
10,000 on 2026-02-05. Note Clerk bills *Monthly Retained Users* — a user counts
only once they return 24h+ after signup — which is narrower than MAU. Pro:
**$25/mo** ($20 annual), overage $0.02/user in the 50k–100k band, declining
after. Business: $300/mo ($250 annual), adds 10 dashboard seats (vs 3 on Pro),
SOC 2 report access, HIPAA.

**Paid-gated features:** MFA, passkeys, SMS codes, custom password
requirements, removing "Secured by Clerk" branding, SAML/OIDC enterprise
connections ($75/mo each), and **custom session lifetime**. Quoting the docs on
that last one: *"Setting a custom maximum lifetime requires a paid plan for
production use, but it's available in development mode."* Default session token
lifetime is **7 days**. Custom claims are available via JWT Templates.

**Waitlist mode — free, and confirmed.** `<Waitlist />` component
(`@clerk/nextjs@6.2.0+`), enabled by a Dashboard toggle. Users get a
confirmation email on joining and an invitation email once approved. Approval is
**manual and per-user from the Dashboard** — no bulk or automated approval is
documented. No plan restriction found. This is the mechanism `V2_PLAN.md` §2
locks and §4 leans on structurally, so its being free matters.

Note the adjacent trap: **allowlist and blocklist** *do* require a paid plan in
production (*"free to use in development mode so that you can try out what works
for you"*). Waitlist mode is not the same feature and is not gated. Don't
conflate them when reading the pricing page.

**Python backend.** Official package is **`clerk-backend-api`** (PyPI),
**v7.0.0, released 2026-08-11**, Python 3.10–3.14, maintained by Clerk staff. A
separate `clerk_backend_sdk` package exists — that is not the one to use.

It supports genuinely networkless verification: pass a PEM public key as
`jwt_key` in `AuthenticateRequestOptions` for zero network calls. Without it,
it fetches JWKS from `https://api.clerk.com/v1/jwks` with ~5 min in-memory
caching. The SDK reads `Authorization: Bearer` first and falls back to the
`__session` cookie, and FastAPI's `Request` satisfies its expected interface
directly.

There is an **official first-party FastAPI example**:
`https://github.com/clerk/fastapi-example` (env vars `CLERK_API_SECRET_KEY`,
`CLERK_AUTHORIZED_PARTIES`). Manual from-scratch verification is also documented
at `clerk.com/docs/backend-requests/manual-jwt`.

**The real argument against Clerk: residency.** Clerk stores all user data on
**US infrastructure with no region selection** — they state this plainly. EU/UK/
Swiss transfers rely on adequacy decisions plus Clerk's Data Privacy Framework
self-certification. There is no EU or India residency option.

For India's DPDP Act this is **legal but not free of consequence**. DPDP §16
uses a negative-list approach to cross-border transfers, and as of 2026 no
restricted-country list has been notified, so the transfer is permitted. The
consequence is that Clerk becomes a **third named subprocessor** in L1's privacy
policy, alongside Groq and OpenAI — L1's card currently names only those two.

*Unverified:* Clerk's cloud provider (sources disagreed between GCP+Cloudflare
and AWS), and the SOC 2 / HIPAA certification date. No Clerk-specific DPDP
statement exists; the DPDP processor characterisation above is inference from
their generic GDPR DPA, and is worth a legal read before launch rather than
after.

**Known downsides** (community sentiment, not primary sources): vendor lock-in
is real because UI and session management are tightly coupled, so migrating off
is a rewrite rather than a data export; there is no on-premises option; the v5
upgrade is cited as a past breaking-change pain point; and the pricing curve
gets steep well past our scale.

## Option 2 — Better Auth, self-hosted

Verified 2026-08-15/16. **v1.6.29** (2026-08-14), with v1.7.0-rc.6 cut the same
day. 29.5k stars, 2,801 forks, 651 open issues, MIT, first commit May 2024.
Near-daily patch releases, recently weighted toward session concurrency and
single-use-token race fixes (v1.6.18–1.6.26) — actively hardening in public.

**Free where Clerk charges:** 2FA, organizations/teams/RBAC, an admin plugin
(**API only — no hosted admin UI**, you build the frontend), rate limiting (on
by default), and Captcha/Turnstile bot protection. It does **not** send email —
you wire your own provider.

**Business-model update:** Better Auth launched its own paid tier in 2026 —
**$150/mo (Growth)** and **$500/mo (Growth Plus)** — bundling a hosted
dashboard, enterprise SSO/SCIM, and a "Sentinel" abuse-detection plugin. The
core remains free and MIT, but "the free one" is no longer the whole pitch.

**The cross-language question.** Better Auth is TypeScript-only, and our backend
is Python. The viable path is the **JWT plugin + JWKS**, not the Bearer plugin —
Bearer requires calling `auth.api.getSession()`, which is a TypeScript API on
the auth server itself and is not reachable from Python.

- JWKS at `/api/auth/jwks` (customizable via `jwksPath`, or point at a
  `remoteUrl`).
- Default algorithm is **EdDSA (Ed25519)**, configurable to RS256/ES256/PS256/
  ES512/ECDH-ES. PyJWT handles Ed25519 given `cryptography`, which we already
  depend on for Fernet.
- **Correction to an earlier claim in this research:** a subagent reported the
  docs contain explicit language-agnostic guidance ("No matter which language
  you use, the process is the same"). That sentence is **not** in the current
  docs source — checked against
  `docs/content/docs/plugins/jwt.mdx` on `main`. What the page actually says is
  *"The token can be verified in your own service, without the need for an
  additional verify call or database check. For this JWKS is used."* Both worked
  examples are JavaScript `jose`.

So: the mechanism is standard JWKS and language-agnostic in nature, but the
Python glue is ours to write (~50–100 lines). A community package
`fastapi-betterauth` exists on PyPI (v0.2.6, ~May 2026, single individual
maintainer) — reference material, not a dependency worth taking.

**Schema coexistence with Alembic.** Better Auth needs four tables — `user`,
`session`, `account`, `verification` — and table/field names are remappable via
`modelName`/`fields`. Its `migrate` CLI **only works with the built-in Kysely
adapter**; for anything else the documented path is `generate` once, then apply
and evolve through your own tool. So Alembic can own the schema, but every
plugin that adds a column means a manual re-translation. Open issue #5430 flags
non-`public`-schema CLI migration as a rough edge.

**Reported downsides, weighted for our deployment shape.** The most common
production failures are cookie attribute misconfiguration (`secure`, `sameSite`,
domain) in **cross-domain frontend/backend splits**, and `X-Forwarded-Proto`
detection failures behind reverse proxies — which is exactly the Vercel +
HF Spaces shape we have. Using the JWT path rather than cookies avoids most of
it. Also: Node-only APIs inside edge middleware break production builds that
work in dev. A SuperTokens blog argues its session handling is comparatively
basic (competitor, bias flagged), which the changelog partly corroborates.

## Option 3 — Neon Managed Better Auth (the closest call)

Verified 2026-08-16. Neon rebuilt Neon Auth on Better Auth in 2026. The previous
version was an external identity provider synced by webhooks, which could not
work with Neon's branching. Now users, sessions and roles live in a
`neon_auth.*` schema **inside your own Neon database** and clone with every
branch.

**Everything mechanical checks out for our stack, and better than self-hosted:**

- JWKS at `<NEON_AUTH_URL>/.well-known/jwks.json`
- **EdDSA (Ed25519)**, access tokens expire in **15 minutes**
- Issuer is the *origin* of the auth URL — e.g. for
  `https://ep-xx.aws.neon.tech/neondb/auth` the issuer is
  `https://ep-xx.aws.neon.tech`
- Session cookie `__Secure-neonauth.session_token` is opaque and HttpOnly; the
  JWT lives in `session.access_token` with `sub`, `email`, `role`, `exp`, `iat`
- **The JWT guide includes a Python (PyJWT + cryptography) example**, alongside
  Go and Node

That last point is the important one: it is *better documented for Python than
self-hosted Better Auth is*, and it removes the "off the documented path"
objection entirely.

**The upside is real.** Identity would live in the same Postgres as
`broker_links`, making `user_id` a genuine foreign key with a genuine cascade —
which is precisely what L1's delete-my-data card depends on. Free to **60,000
MAU**, included on every Neon plan. And it deletes a vendor: no third
subprocessor for the privacy policy, and no US-residency question separate from
wherever the database already lives.

**Why it loses anyway.** Managed Better Auth has **no waitlist and no
invite-only mode.** Neon's docs state that anyone can sign up by default and
that *"support for restricted signups is coming soon"* — and the roadmap does
not list the feature at all, while marking Organizations as ⚠️ Partial and
MFA/2FA as 🔜 Coming soon.

That collides with a locked decision. `V2_PLAN.md` §2 specifies Waitlist mode
and §4 leans on waitlist-gating as what *structurally* removes the urgency of
the C0 security hole. It is a control, not a nicety.

A workaround exists and is genuinely usable: **blocking webhooks** on
`user.before_create` pause the auth flow until your server responds and can
reject the signup. But you would maintain the allowlist table, write the
handler, and build your own approval interface — and that handler would live on
the HF Space, meaning Neon must reach our backend and our backend must be up for
anyone to sign up at all. Clerk gives the same outcome free, with a Dashboard
that already exists.

The pattern is unlucky rather than damning: Neon explicitly says to self-host
Better Auth if you need custom plugins or hooks, and signup gating is exactly
what managed cannot do natively yet.

Smaller considerations: the 15-minute token means the client must refresh via
`authClient.token()` (auth happens at SSE connect, so a long
`/analyze` or `/portfolio/overview` stream won't die mid-flight, but the refresh
logic is ours); and it makes the database and identity provider a single
decision, so leaving Neon later would mean migrating auth too.

**Reassuring, and worth remembering:** choosing Clerk does not close this door.
Neon's Data API accepts third-party JWTs from 13 providers **including Clerk**
via a configurable JWKS URL, so Neon RLS remains available to us later.

## Option 4 — roll our own on Google

Not chosen, but more viable than "write your own auth" usually implies, and
worth recording because the objection that killed *Sign in with IND Money* does
not apply here.

Google's discovery document, verified directly, has everything IND Money lacks:
issuer `https://accounts.google.com`, `jwks_uri`
`https://www.googleapis.com/oauth2/v3/certs`, `userinfo_endpoint`, **RS256**
`id_token`, and a stable `sub`.

Google-only SSO deletes the genuinely hard parts: no password storage, no
hashing, no reset flows, no email deliverability, and Google is the MFA.
Verification in Python is a handful of lines with `google-auth`.

What we would own: session issuance and lifetime, CSRF on the callback, token
refresh, revocation, waitlist gating (cheap — an allowlist table, and F3's
`oauth_pending` single-use + TTL pattern is already the right shape to copy),
and an admin path to approve people since there would be no dashboard. And every
security bug in all of it, permanently. Small attack surface, high blast radius
for an app holding people's net worth.

## Database — Neon (unchanged)

Verified 2026-08-15/16.

**Free tier:** 0.5 GB storage per project, **100 CU-hours per project per
month**, up to 100 projects, 10 branches per project, autoscale to 2 CU,
autosuspend after 5 min idle, 5 GB egress. Hitting a limit suspends compute
until the next billing month — a pause, not an overage charge.

**Launch:** $0.106/CU-hour + $0.35/GB-month, up to 16 CU, 7-day restore, **no
monthly minimum**. **Scale:** $0.222/CU-hour, 56 CU, 30-day restore, adds SLA/
HIPAA/SOC 2/Private Link/SSO at no extra fee.

**Databricks acquired Neon in May 2025 and the free tier got better, not
worse:** compute down 15–25%, storage down ~80% to $0.35/GB-month, monthly
minimums removed (Dec 2025), free CU-hours doubled 50 → 100.

**Regions are AWS-only** (Azure deprecated for new projects): us-east-1,
us-east-2, us-west-2, eu-central-1, eu-west-2, **ap-southeast-1 (Singapore)**,
ap-southeast-2, sa-east-1. **There is no Mumbai/India region.** Singapore is the
best latency option. Since the backend is on HF Spaces (also not in India), what
matters is co-locating the Space and the Neon region — not user-to-database
distance.

### Connection settings — a real gap, not yet applied

This is the most actionable engineering finding of this research. **Nothing
below has been changed; it is recorded for whoever wires the Space to Neon.**

Neon's pooler is **PgBouncer in transaction mode only**, at a `-pooler`-suffixed
hostname. Transaction mode does not support SQL-level `PREPARE`/`DEALLOCATE`,
`SET`/`RESET`, or `LISTEN`/`NOTIFY`.

1. **`statement_cache_size=0` is required on the pooled endpoint.** asyncpg
   creates server-side prepared statements by default, which breaks against
   transaction-mode pooling with `DuplicatePreparedStatementError` — connections
   are handed to different backend sessions between statements. Fix:
   `connect_args={"statement_cache_size": 0}`. This is inherent to any
   PgBouncer-transaction-mode + asyncpg pairing, not Neon-specific. *Community-
   verified — Neon's own Python page shows a bare `asyncpg.connect()` with no
   pooler guidance at all.*
2. **`pool_recycle` should be set at or below the scale-to-zero window**, per
   Neon's SQLAlchemy guidance, together with `pool_pre_ping=True` (and
   SQLAlchemy ≥ 2.0.33).
3. **Run Alembic against the direct, non-pooled endpoint.** Migrations are
   infrequent, don't need pooling, and this sidesteps pooler/DDL edge cases.

Current state: `backend/db/session.py:143` sets `pool_pre_ping=True` and
**nothing else** — no `pool_recycle`, no `statement_cache_size`, and no
distinction between the pooled and direct endpoints. F1 anticipated half of
this.

**Free-tier arithmetic worth knowing.** 100 CU-hours/month is designed for
serverless functions. We run a *long-lived* FastAPI process with a SQLAlchemy
pool; a pool that holds connections open keeps the compute awake, and always-on
at 0.25 CU is ~182 CU-hours/month. The `pool_recycle` setting is what lets the
compute actually suspend.

### Alternatives considered

**Supabase — avoid, on India-specific grounds.** On **24 February 2026 India's
MeitY ordered ISPs to block `*.supabase.co` under Section 69A of the IT Act.**
Jio, Airtel and others blocked DNS for roughly 7–8 days; Supabase reported
~365,000 Indian visits (~9% of global traffic) affected; access was restored
around 4–5 March 2026. **No reason was ever publicly given.** For a product
whose entire user base is in India, that is an unmitigable regulatory tail risk
with no warning, and it is specific to Supabase — Neon's domains were not
targeted. Separately its free tier pauses projects after 1 week of inactivity,
allows 2 active projects, and has **zero days of backup retention**. It does
have a Mumbai (ap-south-1) region, and Pro at $25/mo removes the pause.

| Option | Verdict |
| --- | --- |
| **Neon** | Chosen. Best free tier, no forced expiry, true pay-as-you-go, Singapore. |
| **Aiven** | The only budget option with a **real Mumbai region** — but only on the **Developer tier at $5/mo**; the free tier lets you pick a broad "Asia Pacific" geography, not a specific region. Keep in mind if Singapore latency ever disappoints. |
| **Supabase** | Avoid — see the Section 69A block above. |
| **Render** | Free Postgres now **expires 30 days after creation** (was 90), 14-day grace then deletion. A trial, not a free tier. |
| **Railway** | No durable free tier: one-time $5 trial credit, then $1/mo credit (insufficient for an always-on DB). |
| **Xata** | Free tier removed in the 2025 pivot; $100 credit expiring in 14 days, then usage billing. |
| **Prisma Postgres** | Billed per ORM operation — wrong model for a SQLAlchemy/asyncpg stack. |
| **Fly.io** | Has Mumbai (`bom1`) but no free tier; from $38/mo. |

**The serverless-HTTP-driver question is not relevant to us.** Drivers like
`@neondatabase/serverless` exist for edge functions with no persistent process.
HF Spaces runs a long-lived container — plain asyncpg over TCP to the pooled
endpoint is correct.

## The schema is already provider-neutral

`backend/db/models.py` defines `users.id` as a plain `varchar(255)` string
primary key, deliberately: *"a string, not a UUID, so F2 adopts Clerk without a
key migration."*

That neutrality is broader than the comment claims. Clerk's `user_…`, Better
Auth's UUID, and Google's numeric `sub` **all fit unchanged**. F1 did not lock
us to Clerk. The switching cost at the database layer is zero today, and stays
zero right up until real users exist.

## Revisit triggers

Reopen this decision if any of these become true — otherwise don't.

1. **Neon ships restricted signups.** This is the big one. It is the single
   feature standing between us and deleting a vendor while gaining a real
   foreign key. Watch `neon.com/docs/auth/roadmap`.
2. **Residency becomes a requirement** — a user, partner, or regulator asks that
   personal data not leave infrastructure we control. Clerk cannot satisfy that
   at any price; it offers no region selection.
3. **We want off Vercel**, or otherwise want the stack self-contained and
   portable.
4. **Cost stops being free** — we pass 50,000 MRU, or need MFA/custom session
   lifetime badly enough to pay $25/mo. (Not a strong trigger; $25/mo is cheap
   for what it removes.)

## Open follow-ups

- **Clerk's live subprocessor list is behind `trust.clerk.com`, which returns
  403 to automated fetching.** L1 requires naming subprocessors in the privacy
  policy, and Clerk would be the third alongside Groq and OpenAI. Someone has to
  open that page by hand or request the list from Clerk support before L1 ships.
- **The Neon connection settings above are unapplied.** They will bite the first
  time the Space runs against Neon's pooled endpoint, and are invisible until
  then.
- **The DPDP processor characterisation is inference, not verified** against any
  Clerk statement about India. Worth a legal read before inviting users, not
  after.

## Sources

Clerk: [pricing](https://clerk.com/pricing) ·
[restricting access / waitlist](https://clerk.com/docs/guides/secure/restricting-access) ·
[clerk-backend-api](https://pypi.org/project/clerk-backend-api/) ·
[official FastAPI example](https://github.com/clerk/fastapi-example) ·
[manual JWT verification](https://clerk.com/docs/backend-requests/manual-jwt) ·
[session options](https://clerk.com/docs/guides/secure/session-options) ·
[GDPR / transfers](https://clerk.com/legal/gdpr) ·
[DPA](https://clerk.com/legal/dpa)

Better Auth: [introduction](https://www.better-auth.com/docs/introduction) ·
[JWT plugin](https://www.better-auth.com/docs/plugins/jwt) ·
[JWT docs source](https://github.com/better-auth/better-auth/blob/main/docs/content/docs/plugins/jwt.mdx) ·
[database concepts](https://www.better-auth.com/docs/concepts/database) ·
[CLI](https://www.better-auth.com/docs/concepts/cli) ·
[hooks](https://www.better-auth.com/docs/concepts/hooks) ·
[pricing](https://www.better-auth.com/pricing)

Neon Auth: [Managed Better Auth overview](https://neon.com/docs/auth/overview) ·
[JWT guide (Python example)](https://neon.com/docs/auth/guides/plugins/jwt) ·
[roadmap](https://neon.com/docs/auth/roadmap) ·
[webhooks](https://neon.com/docs/auth/guides/webhooks) ·
[authentication flow](https://neon.com/docs/auth/authentication-flow) ·
[announcement](https://neon.com/blog/neon-auth-branchable-identity-in-your-database) ·
[custom auth providers](https://neon.com/docs/data-api/custom-authentication-providers)

Neon DB: [pricing](https://neon.com/pricing) · [regions](https://neon.com/docs/introduction/regions) ·
[connection pooling](https://neon.com/docs/connect/connection-pooling) ·
[SQLAlchemy guide](https://neon.com/docs/guides/sqlalchemy) ·
[asyncpg + PgBouncer discussion](https://github.com/sqlalchemy/sqlalchemy/discussions/10246)

Others: [Supabase pricing](https://supabase.com/pricing) ·
[TechCrunch — India blocks Supabase](https://www.techcrunch.com/2026/02/27/india-disrupts-access-to-popular-developer-platform-supabase-with-blocking-order/) ·
[Medianama](https://www.medianama.com/2026/02/223-supabase-isp-level-block-jiofiber-users-india/) ·
[Render free Postgres expiry](https://render.com/changelog/free-postgresql-instances-now-expire-after-30-days-previously-90) ·
[Aiven regions](https://aiven.io/docs/platform/reference/list_of_clouds) ·
[Google OIDC discovery](https://accounts.google.com/.well-known/openid-configuration) ·
[DPDP cross-border transfers](https://securiti.ai/cross-border-data-transfer-requirements-under-india-dpdpa/)
