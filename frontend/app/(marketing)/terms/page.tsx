import type { Metadata } from "next";

import { LegalPage } from "@/components/shell/LegalPage";

export const metadata: Metadata = {
  title: "Terms — AlphaDesk",
  description: "The terms of use for AlphaDesk: descriptive analytics only, not investment advice.",
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Use"
      updated="16 August 2026"
      summary="AlphaDesk is a portfolio-analytics and research tool. It is descriptive only and is not investment advice; the research desk is a paper simulation and no real orders are ever placed. By using AlphaDesk you agree to these terms."
    >
      <section>
        <h2>What AlphaDesk is</h2>
        <p>
          AlphaDesk links your IND Money account read-only and shows you your net worth,
          allocation, holdings and history, plus an AI overview that narrates figures computed
          from your own data. It is a personal analytics tool.
        </p>
      </section>

      <section>
        <h2>Not investment advice</h2>
        <p>
          Everything AlphaDesk shows is <b className="font-semibold text-foreground">descriptive
          analytics</b> — a picture of what your portfolio <i>is</i>. It is{" "}
          <b className="font-semibold text-foreground">not investment advice</b>, not a
          recommendation to buy, hold or sell any security, and not a forecast. AlphaDesk is not
          a registered investment adviser or research analyst. Decisions you make are your own;
          consult a qualified, registered adviser before acting.
        </p>
      </section>

      <section>
        <h2>The Lab is a simulation</h2>
        <p>
          The research desk (&ldquo;Lab&rdquo;) is a labelled{" "}
          <b className="font-semibold text-foreground">paper simulation</b>. Its runs produce a
          paper watchlist for illustration only.{" "}
          <b className="font-semibold text-foreground">No real orders are ever placed</b> — the
          broker layer is a stub — and its buy/avoid outputs are not advice about your real
          holdings.
        </p>
      </section>

      <section>
        <h2>Data, accuracy and availability</h2>
        <p>
          Figures come from your broker via the IND Money MCP and from AI narration; they may be
          delayed, incomplete, or wrong, and AlphaDesk is provided &ldquo;as is&rdquo; without
          warranty. Snapshots are captured at a point in time and cannot be recreated for a day
          the job did not run. We may change or discontinue the service. See the{" "}
          <a href="/privacy">Privacy Policy</a> for what we store and how to delete it.
        </p>
      </section>

      <section>
        <h2>Acceptable use</h2>
        <p>
          Use AlphaDesk only for your own account and data. Do not attempt to access another
          user&rsquo;s data, disrupt the service, or use it to provide personalized advice to
          others.
        </p>
      </section>

      <section>
        <h2>Limitation of liability</h2>
        <p>
          To the extent permitted by law, AlphaDesk and its authors are not liable for any loss
          arising from your use of the service or reliance on anything it shows.
        </p>
      </section>
    </LegalPage>
  );
}
