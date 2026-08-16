import type { Metadata } from "next";

import { LegalPage } from "@/components/shell/LegalPage";

export const metadata: Metadata = {
  title: "Privacy — AlphaDesk",
  description: "How AlphaDesk handles your data. Placeholder; full policy at launch.",
};

export default function PrivacyPage() {
  return (
    <LegalPage
      title="Privacy"
      summary="AlphaDesk reads your IND Money portfolio read-only, over OAuth, to compute and display your own dashboard. It places no orders and shows descriptive analytics only — never investment advice."
    >
      <p>
        The full privacy policy — what is stored, for how long, and how to delete
        it (the DPDP “delete my data” obligation, which revokes the broker token
        upstream and removes every row) — is published with the L1 release.
      </p>
    </LegalPage>
  );
}
