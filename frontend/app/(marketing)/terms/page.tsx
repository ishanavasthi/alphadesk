import type { Metadata } from "next";

import { LegalPage } from "@/components/shell/LegalPage";

export const metadata: Metadata = {
  title: "Terms · AlphaDesk",
  description:
    "The terms of use for AlphaDesk: descriptive analytics only, not investment advice, a paper simulation, and open source.",
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms of Use"
      updated="16 August 2026"
      summary="AlphaDesk is a portfolio-analytics and research tool. It is descriptive only and is not investment advice; the research desk is a paper simulation and no real orders are ever placed. Access is waitlist-gated and the code is open source. By using AlphaDesk you agree to these terms."
    >
      <section>
        <h2>What AlphaDesk is</h2>
        <p>
          AlphaDesk links your IND Money account read-only and shows you your net worth,
          allocation, holdings and history, plus an AI overview that narrates figures computed
          from your own data. It is a personal analytics tool, offered as is, by an individual
          author rather than a financial institution.
        </p>
      </section>

      <section>
        <h2>Who can use it</h2>
        <p>
          Access is <b className="font-semibold text-foreground">waitlist-gated</b>. Joining the
          waitlist does not create an account or entitle you to access; the operator approves
          invitations individually and may decline or withdraw access at any time, for any reason,
          without notice. You must be at least 18 and use AlphaDesk only for your own accounts.
        </p>
      </section>

      <section>
        <h2>Not investment advice</h2>
        <p>
          Everything AlphaDesk shows is{" "}
          <b className="font-semibold text-foreground">descriptive analytics</b>, a picture of
          what your portfolio <i>is</i>. It is{" "}
          <b className="font-semibold text-foreground">not investment advice</b>, not a
          recommendation to buy, hold or sell any security, and not a forecast or a projection of
          returns. Nothing here is personalized to your objectives, risk tolerance or
          circumstances, and nothing here should be treated as a solicitation to transact.
        </p>
        <p>
          AlphaDesk is <b className="font-semibold text-foreground">not registered with SEBI</b> as
          an Investment Adviser or a Research Analyst, and provides no investment advisory or
          research analyst services within the meaning of those regulations. It does not manage
          money, hold client funds or securities, or execute transactions. Decisions you make are
          your own; consult a qualified, registered adviser before acting.
        </p>
      </section>

      <section>
        <h2>The Lab is a simulation</h2>
        <p>
          The research desk (&ldquo;Lab&rdquo;) is a labelled{" "}
          <b className="font-semibold text-foreground">paper simulation</b>. Its runs produce a
          paper watchlist for illustration only.{" "}
          <b className="font-semibold text-foreground">No real orders are ever placed</b>, the
          broker layer is a stub, and its buy or avoid outputs are simulated research artifacts,
          not advice about your real holdings. The Lab is deliberately kept in its own section and
          is never shown alongside your real portfolio. Approving an item in the Lab adds a row to
          a paper watchlist and does nothing else.
        </p>
      </section>

      <section>
        <h2>Scope: Indian rupees only</h2>
        <p>
          In this version AlphaDesk reports in{" "}
          <b className="font-semibold text-foreground">Indian rupees only</b>. Holdings reported in
          any other currency are rejected rather than converted, so that a total is never quietly
          wrong. If your broker account holds non-INR assets, those positions may be missing from
          the figures you see, and the totals should be read as INR-only totals.
        </p>
      </section>

      <section>
        <h2>Data, accuracy and availability</h2>
        <p>
          Figures come from your broker via the IND Money MCP and from AI narration; they may be
          delayed, incomplete, or wrong, and must not be relied on for tax, accounting or any
          other record-keeping purpose. Your broker and your own statements remain the record of
          truth. Snapshots are captured at a point in time and cannot be recreated for a day the
          job did not run. Language models can produce inaccurate text even when the underlying
          numbers are correct. This is a personal project with no uptime commitment: we may
          change, suspend or discontinue any part of the service at any time. See the{" "}
          <a href="/privacy">Privacy Policy</a> for what we store and how to delete it.
        </p>
      </section>

      <section>
        <h2>Acceptable use</h2>
        <p>
          Use AlphaDesk only for your own account and data. Do not attempt to access another
          user&rsquo;s data, disrupt or overload the service, bypass the rate limits, scrape it, or
          use it to provide personalized advice to others. Automated access outside the product
          itself is not permitted.
        </p>
      </section>

      <section>
        <h2>Open source</h2>
        <p>
          AlphaDesk is an <b className="font-semibold text-foreground">open-source project</b>. The
          source code, including everything described in this document and in the{" "}
          <a href="/privacy">Privacy Policy</a>, is public at{" "}
          <a href="https://github.com/ishanavasthi/alphadesk">
            github.com/ishanavasthi/alphadesk
          </a>
          . You can read exactly what is requested from your broker, what is stored, and what is
          sent to the language models, and you can run your own instance.
        </p>
        <p>
          These terms govern your use of the hosted service at this site. Your rights to the code
          itself are governed by the repository&rsquo;s licence, not by this page, and running your
          own copy is your own responsibility. The public repository contains no user data.
        </p>
      </section>

      <section>
        <h2>No warranty</h2>
        <p>
          As with open-source software generally, AlphaDesk is provided{" "}
          <b className="font-semibold text-foreground">&ldquo;as is&rdquo;, without warranty of any
          kind</b>, express or implied, including without limitation the warranties of
          merchantability, fitness for a particular purpose, accuracy, and non-infringement. The
          entire risk as to the quality and performance of the service is with you.
        </p>
      </section>

      <section>
        <h2>Limitation of liability</h2>
        <p>
          To the extent permitted by law, AlphaDesk and its authors and contributors are not
          liable for any loss, including trading or investment losses, lost profits, or loss of
          data, arising from your use of the service, from its unavailability or inaccuracy, or
          from reliance on anything it shows.
        </p>
      </section>

      <section>
        <h2>Changes to these terms</h2>
        <p>
          We may update these terms; the date at the top of this page changes when we do, and
          continuing to use AlphaDesk after that means you accept the updated terms. These terms
          are governed by the laws of India.
        </p>
      </section>
    </LegalPage>
  );
}
