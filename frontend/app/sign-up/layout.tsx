import type { ReactNode } from "react";

import { AuthFooterShell } from "@/components/shell/AuthFooterShell";

/**
 * `/sign-up` collects an email and creates an account, but sits outside the
 * marketing group, so its footer — and the Privacy/Terms links a
 * data-collecting page owes the reader — would otherwise be unreachable. This
 * layout gives it the shared footer, as `/sign-in` and the retired `/waitlist`
 * both have.
 */
export default function SignUpLayout({ children }: { children: ReactNode }) {
  return <AuthFooterShell>{children}</AuthFooterShell>;
}
