import type { Metadata } from "next";

import { LegalPage } from "@/components/shell/LegalPage";

export const metadata: Metadata = {
  title: "Privacy — AlphaDesk",
  description:
    "What AlphaDesk reads from your broker, where it is stored, how long it is kept, and how to delete it.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="16 August 2026"
      summary="AlphaDesk reads your IND Money portfolio read-only, over OAuth, to compute and show you your own dashboard. It places no orders and shows descriptive analytics only — never investment advice. This policy explains exactly what is read, where it is stored, how long it is kept, who processes it, and how to delete it."
    >
      <section>
        <h2>What we read, and why</h2>
        <p>
          When you connect IND Money, you authorize AlphaDesk — through IND Money&rsquo;s own
          OAuth screen — to read, and only read:
        </p>
        <ul>
          <li>your holdings across stocks, mutual funds and other assets;</li>
          <li>their current values and, where the source provides it, your invested amount;</li>
          <li>your SIPs (systematic investment plans);</li>
          <li>your net-worth totals and allocation breakdowns.</li>
        </ul>
        <p>
          We read these so we can compute and display your dashboard and daily net-worth
          history. We never receive your IND Money password — authentication happens on IND
          Money&rsquo;s site, and we hold only an OAuth token, encrypted at rest.
        </p>
      </section>

      <section>
        <h2>What we never do</h2>
        <ul>
          <li>
            <b className="font-semibold text-foreground">No trading.</b> AlphaDesk cannot place,
            change or cancel an order. Access is strictly read-only.
          </li>
          <li>
            <b className="font-semibold text-foreground">No credentials.</b> We never see or
            store your broker password.
          </li>
          <li>
            <b className="font-semibold text-foreground">No advice.</b> Everything shown is
            descriptive analytics, not a recommendation.
          </li>
          <li>We never sell your data, and we never share it except with the processors below.</li>
        </ul>
      </section>

      <section>
        <h2>Where it is stored, and for how long</h2>
        <p>
          Your data is stored in a PostgreSQL database (Neon). We keep the{" "}
          <b className="font-semibold text-foreground">normalized daily snapshots</b> — the
          per-day totals and holding rows that draw your net-worth history — for as long as your
          account exists, because a point-in-time snapshot cannot be recreated later. The{" "}
          <b className="font-semibold text-foreground">raw broker payloads</b> those snapshots
          are derived from are kept only for forensics and are{" "}
          <b className="font-semibold text-foreground">pruned after 90 days</b>. Your broker
          tokens are encrypted at rest and are never returned to your browser.
        </p>
      </section>

      <section>
        <h2>Who processes your data (subprocessors)</h2>
        <p>We use these services to run AlphaDesk. Each processes only what its function needs:</p>
        <ul>
          <li>
            <b className="font-semibold text-foreground">Groq</b> — runs the Lab&rsquo;s research
            agents (market-data prompts; not your holdings).
          </li>
          <li>
            <b className="font-semibold text-foreground">OpenAI</b> — narrates your portfolio
            overview from aggregate figures. By default your inputs are{" "}
            <b className="font-semibold text-foreground">not used to train models</b>, and are
            retained for up to 30 days for abuse monitoring. We send OpenAI aggregates and
            instrument names only — never account numbers, broker ids, your email, or your user
            id.
          </li>
          <li>
            <b className="font-semibold text-foreground">LangSmith</b> — traces the Lab&rsquo;s
            research runs (the prompts and responses of the market-data agents) for debugging,
            and <b className="font-semibold text-foreground">only when a LangSmith API key is
            configured</b>. It never receives your portfolio: your holdings, net worth and
            overview are explicitly kept out of tracing.
          </li>
          <li>
            <b className="font-semibold text-foreground">Clerk</b> — identity and sign-in.
          </li>
          <li>
            <b className="font-semibold text-foreground">Neon</b> — the PostgreSQL database.
          </li>
          <li>
            <b className="font-semibold text-foreground">Hugging Face</b> — hosts the backend.
          </li>
          <li>
            <b className="font-semibold text-foreground">Vercel</b> — hosts the frontend.
          </li>
        </ul>
      </section>

      <section>
        <h2>Your rights, and deleting your data</h2>
        <p>
          Under India&rsquo;s Digital Personal Data Protection Act, you can erase your data at
          any time. Use <b className="font-semibold text-foreground">&ldquo;Delete my
          data&rdquo;</b> in the account menu: it first{" "}
          <b className="font-semibold text-foreground">revokes your broker token upstream</b> at
          IND Money, then permanently deletes your account and every row we hold — your link,
          your snapshots and history, and your paper watchlist. This cannot be undone. You can
          also disconnect IND Money on its own at any time without deleting your account.
        </p>
      </section>
    </LegalPage>
  );
}
