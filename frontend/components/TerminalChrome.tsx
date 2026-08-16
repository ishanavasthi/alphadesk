"use client";

import { usePathname } from "next/navigation";
import { TopBar } from "@/components/TopBar";

/**
 * Renders the terminal `<TopBar/>` everywhere except the D1 portfolio surface.
 *
 * The portfolio route (card D1) ships the locked shadcn design, which has its
 * own top bar; stacking the dark terminal chrome above it would be two headers
 * from two design languages on one page. This is deliberately the dumbest
 * possible conditional — **card U1 owns unifying the app shell and should
 * delete this file**, restoring `<TopBar/>` (or its successor) directly in
 * `app/layout.tsx`.
 *
 * Nothing about the Lab (`/lab`, `/lab/a/[id]`) changes: it renders exactly the
 * header it always did.
 */
export function TerminalChrome() {
  const pathname = usePathname();
  // Exact match or a true child segment — a bare `startsWith` would also strip
  // the chrome from an unrelated future route like `/portfolios` or
  // `/portfolio-settings`.
  if (pathname === "/portfolio" || pathname?.startsWith("/portfolio/")) return null;
  return <TopBar />;
}
