import type { Metadata } from "next";

import { LegalPage } from "@/components/shell/LegalPage";

export const metadata: Metadata = {
  title: "Privacy · AlphaDesk",
  description:
    "What AlphaDesk reads from your broker, where it is stored, how long it is kept, who processes it, and how to delete it.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy Policy"
      updated="16 August 2026"
      summary="AlphaDesk reads your IND Money portfolio read-only, over OAuth, to compute and show you your own dashboard. It places no orders and shows descriptive analytics only, never investment advice. This policy explains exactly what is read, why, where it is stored, how long it is kept, who processes it, and how to delete it."
    >
      <section>
        <h2>Who is responsible for your data</h2>
        <p>
          AlphaDesk is operated as a personal project by its author. Under India&rsquo;s Digital
          Personal Data Protection Act, 2023, the operator is the{" "}
          <b className="font-semibold text-foreground">data fiduciary</b> for the personal data
          described here, and you are the data principal. Your data is processed for one stated
          purpose only: computing and showing you your own portfolio analytics. It is not
          processed for advertising, profiling, resale, or any purpose you have not asked for.
        </p>
      </section>

      <section>
        <h2>What we read, and why</h2>
        <p>
          When you connect IND Money, you authorize AlphaDesk, through IND Money&rsquo;s own OAuth
          screen, to read, and only read:
        </p>
        <ul>
          <li>your holdings across stocks, mutual funds and other assets;</li>
          <li>their current values and, where the source provides it, your invested amount;</li>
          <li>your SIPs (systematic investment plans);</li>
          <li>your net-worth totals and allocation breakdowns.</li>
        </ul>
        <p>
          We read these so we can compute and display your dashboard, your allocation and
          concentration metrics, and your daily net-worth history. We never receive your IND
          Money password: authentication happens on IND Money&rsquo;s site, and we hold only an
          OAuth token.
        </p>
        <p>
          Alongside the portfolio data we store the minimum needed to run an account: the user id
          and email address your sign-in provider gives us, and the paper watchlist entries you
          approve in the Lab.
        </p>
      </section>

      <section>
        <h2>Consent, given at link time</h2>
        <p>
          Before you are sent to IND Money&rsquo;s OAuth screen, AlphaDesk shows you a consent
          screen that names exactly what will be read and what will never happen. You cannot skip
          it, and linking does not begin until you accept it. Your consent covers the read
          access described above and nothing else. You can withdraw it at any time by
          disconnecting IND Money, which stops all further reads, or by deleting your data, which
          also erases what was already read.
        </p>
      </section>

      <section>
        <h2>What we never do</h2>
        <ul>
          <li>
            <b className="font-semibold text-foreground">No trading.</b> AlphaDesk cannot place,
            change or cancel an order. Access is strictly read-only and no real order is ever
            placed, in the dashboard or in the Lab.
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
        <h2>The daily snapshot</h2>
        <p>
          Once a day, after the Indian market closes and mutual fund NAVs publish, AlphaDesk
          captures one snapshot of your portfolio: the normalized holding rows and the day&rsquo;s
          totals, stamped with an IST calendar date. That snapshot is what draws your net-worth
          history, and it is the only reason we keep portfolio data at all beyond the moment you
          are looking at the screen. The broker feed is point-in-time, so a day that was not
          captured cannot be reconstructed later. Capture stops when you disconnect IND Money.
        </p>
      </section>

      <section>
        <h2>Where it is stored, and for how long</h2>
        <p>
          Your data is stored in a PostgreSQL database hosted by Neon, in a managed cloud region.
          We keep the <b className="font-semibold text-foreground">normalized daily snapshots</b>,
          the per-day totals and holding rows that draw your net-worth history, for as long as
          your account exists, because a point-in-time snapshot cannot be recreated later. The{" "}
          <b className="font-semibold text-foreground">raw broker payloads</b> those snapshots are
          derived from are kept only for forensics and are{" "}
          <b className="font-semibold text-foreground">pruned after 90 days</b>.
        </p>
        <p>
          Your broker tokens are{" "}
          <b className="font-semibold text-foreground">encrypted at rest</b> in that database with
          Fernet symmetric encryption, under a key held only in the backend&rsquo;s server
          environment and never stored beside the data. A token is decrypted only in memory, only
          to call IND Money on your behalf, and is{" "}
          <b className="font-semibold text-foreground">never returned to your browser</b> and
          never written to logs. Lab runs are held in memory only and do not survive a backend
          restart.
        </p>
      </section>

      <section>
        <h2>What the AI models receive</h2>
        <p>
          The portfolio overview is written by a language model from figures AlphaDesk has already
          computed in code. The prompts carry{" "}
          <b className="font-semibold text-foreground">aggregates and instrument symbols only</b>:
          totals, weights, concentration measures, sector splits and ticker symbols. They never
          carry your account numbers, broker ids, email address, or your user id. A redaction step
          in the backend enforces this, and it is covered by tests. Your holdings are also kept
          out of request tracing: the portfolio pipeline runs with tracing disabled at the graph
          level, not by an environment switch someone can flip back on.
        </p>
      </section>

      <section>
        <h2>Who processes your data (subprocessors)</h2>
        <p>We use these services to run AlphaDesk. Each processes only what its function needs:</p>
        <ul>
          <li>
            <b className="font-semibold text-foreground">OpenRouter</b> (LLM routing) is the
            inference provider AlphaDesk currently routes to, for both the Lab&rsquo;s research
            agents and your portfolio overview. OpenRouter forwards each prompt to the underlying
            model it serves; where that model is an unattributed preview model, the identity of
            the operator running it is not disclosed to OpenRouter&rsquo;s customers, and so is
            not known to us. It receives only what the two entries below describe &mdash; for the
            overview, aggregates and instrument symbols, never account numbers, broker ids, your
            email, or your user id.
          </li>
          <li>
            <b className="font-semibold text-foreground">Groq</b> (LLM inference) runs the
            Lab&rsquo;s research agents when the Lab is configured to route to Groq. Those prompts
            are public market-data prompts and do not contain your holdings.
          </li>
          <li>
            <b className="font-semibold text-foreground">OpenAI</b> (LLM inference) narrates your
            portfolio overview from the aggregate figures described above, when the overview is
            configured to route to OpenAI. By default your inputs are{" "}
            <b className="font-semibold text-foreground">not used to train models</b>, and are
            retained for up to 30 days for abuse monitoring before deletion. We send OpenAI
            aggregates and instrument symbols only, never account numbers, broker ids, your email,
            or your user id.
          </li>
          <li>
            <b className="font-semibold text-foreground">LangSmith</b> (tracing) records the
            Lab&rsquo;s research runs for debugging, and{" "}
            <b className="font-semibold text-foreground">only when a LangSmith API key is
            configured</b>. It never receives your portfolio: your holdings, net worth and
            overview are explicitly kept out of tracing.
          </li>
          <li>
            <b className="font-semibold text-foreground">Clerk</b> (identity) handles sign-in and
            holds your email address and user id.
          </li>
          <li>
            <b className="font-semibold text-foreground">Neon</b> (database) hosts the PostgreSQL
            database that holds everything described above.
          </li>
          <li>
            <b className="font-semibold text-foreground">Hugging Face</b> (hosting) runs the
            backend container that talks to your broker and the models.
          </li>
          <li>
            <b className="font-semibold text-foreground">Vercel</b> (hosting) serves the frontend.
          </li>
        </ul>
        <p>
          Some of these process data outside India. IND Money itself is your broker platform, not
          our subprocessor: it is the source you authorize us to read. We use no advertising,
          analytics or error-tracking third parties.
        </p>
      </section>

      <section>
        <h2>Your rights, and deleting your data</h2>
        <p>
          Under the Digital Personal Data Protection Act you can access, correct and erase your
          data, withdraw consent, and raise a grievance. Your dashboard already shows you
          everything we hold about your portfolio.
        </p>
        <p>
          To erase it, use <b className="font-semibold text-foreground">&ldquo;Delete my
          data&rdquo;</b> in the account menu. It first{" "}
          <b className="font-semibold text-foreground">revokes your broker token upstream</b> at
          IND Money, so access ends at the source, and then permanently{" "}
          <b className="font-semibold text-foreground">cascade-deletes every row we hold for
          you</b>: your account, your broker link, any pending link attempt, your snapshot days,
          holdings and raw payloads, and your paper watchlist. It is a single atomic deletion, so
          a half-deleted account is not possible, and it cannot be undone. You can also disconnect
          IND Money on its own at any time, without deleting your account.
        </p>
        <p>
          For a rights request or a grievance, open an issue on the project&rsquo;s public GitHub
          repository. We will respond within the timelines the Act requires.
        </p>
      </section>

      <section>
        <h2>Changes to this policy</h2>
        <p>
          If this policy changes in a way that affects what is read, who processes it, or how long
          it is kept, we will update the date at the top of this page and, for material changes,
          ask for your consent again before the change applies to you.
        </p>
      </section>
    </LegalPage>
  );
}
