"use client";

import type { PortfolioSummary } from "@/lib/api";
import { Badge, Button, Chip } from "./ui";

const LINK_LABEL: Record<PortfolioSummary["link_health"], { text: string; ok: boolean }> = {
  linked: { text: "IND Money · linked", ok: true },
  expiring: { text: "IND Money · renewing", ok: false },
  needs_relink: { text: "IND Money · relink needed", ok: false },
  revoked: { text: "IND Money · access revoked", ok: false },
};

/**
 * The surface's own top bar (`a-shadcn.html` / `a2-overview.html`).
 *
 * "Capture snapshot" is rendered because the locked design has it, and it is
 * **disabled with a `soon` badge** because the feature does not exist until card
 * S1 writes the first daily capture. A button that looked live and did nothing
 * would be a worse answer than one that says what it is waiting for.
 */
export function PortfolioTopBar({
  linkHealth,
  demo,
  onRefresh,
  refreshing,
}: {
  linkHealth: PortfolioSummary["link_health"] | null;
  demo: boolean;
  onRefresh: () => void;
  refreshing: boolean;
}) {
  const link = linkHealth ? LINK_LABEL[linkHealth] : null;
  // min-height, not height: the actions wrap to a second row at 375px, and a
  // fixed 56px header would let them spill over the page title.
  return (
    <header className="mb-6 flex min-h-14 flex-wrap items-center gap-x-3 gap-y-2 border-b border-border py-2">
      <span className="font-semibold tracking-[-0.01em]">
        alpha<b className="text-[var(--adp-accent)]">Desk</b>
      </span>
      <span className="text-[13px] text-muted-foreground">/ Portfolio</span>
      <span className="flex-1" />
      <Button variant="outline" size="sm" onClick={onRefresh} disabled={refreshing}>
        ↺ {refreshing ? "Refreshing…" : "Refresh"}
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled
        title="Daily snapshots arrive with card S1 — there is nothing to capture yet."
      >
        ◫ Capture snapshot
        <Badge variant="soon">S1</Badge>
      </Button>
      {link ? <Chip tone={link.ok ? "ok" : "warn"}>{link.text}</Chip> : null}
      {demo ? <Chip>Demo data</Chip> : null}
    </header>
  );
}
