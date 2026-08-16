import type { ReactNode } from "react";

import { AuthFooterShell } from "@/components/shell/AuthFooterShell";

/**
 * `/sign-in` sits outside the marketing group, so it inherited no footer — and
 * with it, no route to Privacy or Terms. This layout gives it the shared footer.
 */
export default function SignInLayout({ children }: { children: ReactNode }) {
  return <AuthFooterShell>{children}</AuthFooterShell>;
}
