import type { ReactNode } from "react";

/**
 * The shared frame for the `/privacy` and `/terms` policy pages.
 *
 * Card U1 shipped these as reachable placeholders; **card L1 fills them with the
 * real content** — the DPDP data-fiduciary obligations, the named subprocessors,
 * the retention and deletion policy. A product that reads someone's net worth
 * owes them a real, reachable policy, linked from the footer of every page.
 */
export function LegalPage({
  title,
  updated,
  summary,
  children,
}: {
  title: string;
  updated: string;
  summary: string;
  children: ReactNode;
}) {
  return (
    <main className="mx-auto max-w-2xl px-4 py-16 sm:px-6">
      <h1 className="text-xl font-semibold tracking-[-0.02em]">{title}</h1>
      <p className="mt-1 text-xs text-[var(--adp-faint)]">Last updated {updated}</p>
      <p className="mt-4 text-[14px] leading-relaxed text-muted-foreground">{summary}</p>
      <div className="mt-8 space-y-6 text-[13.5px] leading-relaxed text-muted-foreground [&_h2]:mt-1 [&_h2]:text-[15px] [&_h2]:font-semibold [&_h2]:text-foreground [&_ul]:list-disc [&_ul]:space-y-1 [&_ul]:pl-5 [&_a]:underline [&_a:hover]:text-foreground">
        {children}
      </div>
      <p className="mt-10 text-xs text-[var(--adp-faint)]">
        Questions, or a request under your data-protection rights? Open an issue on the
        project&rsquo;s GitHub, or use &ldquo;Delete my data&rdquo; in the account menu.
      </p>
    </main>
  );
}
