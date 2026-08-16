import type { ReactNode } from "react";

import { AuthFooterShell } from "@/components/shell/AuthFooterShell";

/**
 * `/waitlist` collects an email but sat outside the marketing group, so its
 * footer — and the Privacy/Terms links a data-collecting page owes the reader —
 * was unreachable. This layout gives it the shared footer.
 */
export default function WaitlistLayout({ children }: { children: ReactNode }) {
  return <AuthFooterShell>{children}</AuthFooterShell>;
}
