import type { Metadata } from "next";

import { LegalPage } from "@/components/shell/LegalPage";

export const metadata: Metadata = {
  title: "Terms — AlphaDesk",
  description: "Terms of use for AlphaDesk. Placeholder; full terms at launch.",
};

export default function TermsPage() {
  return (
    <LegalPage
      title="Terms"
      summary="AlphaDesk is a portfolio-analytics and research tool. It is descriptive only and is not investment advice; the research desk is a paper simulation and no real orders are ever placed."
    >
      <p>
        The full terms of use are published with the L1 release. Until then, use
        the live demo freely and treat everything the product shows as
        informational, not a recommendation.
      </p>
    </LegalPage>
  );
}
