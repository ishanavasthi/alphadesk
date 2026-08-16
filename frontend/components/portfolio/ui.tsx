/**
 * The shadcn primitives for the portfolio surface, tuned to the DECISION tokens.
 *
 * `components/ui/*` already holds this app's shadcn set, but it was tuned for
 * the Bloomberg terminal — uppercase mono buttons, 4px radii. Editing those in
 * place would restyle `/` and `/a/[id]`, so the D1 surface carries its own copy
 * with the same cva/`cn` construction shadcn generates. That is how shadcn is
 * meant to be used: the components live in the repo and get edited.
 *
 * Every measurement here traces to `docs/design/DECISION.md` and the reference
 * pages `a-shadcn.html` / `shadcn.css`.
 */
import type { ReactNode } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/** Card: 8px radius, hairline border, the one small shadow in the system. */
export function Card({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-card p-5 shadow-[0_1px_2px_var(--adp-shadow)]",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
}

/** Card header: 14/600 title over a 12px muted description. */
export function CardHead({ title, desc }: { title: string; desc?: ReactNode }) {
  return (
    <div className="mb-3.5">
      <h2 className="text-sm font-semibold leading-tight">{title}</h2>
      {desc ? <div className="mt-0.5 text-xs text-muted-foreground">{desc}</div> : null}
    </div>
  );
}

const badgeVariants = cva(
  "inline-block rounded-[4px] px-1.5 py-px align-[1px] text-[10.5px] font-semibold tracking-[.02em]",
  {
    variants: {
      variant: {
        type: "border border-border bg-secondary text-muted-foreground",
        us: "border border-[var(--adp-accent-ring)] bg-[var(--adp-accent-soft)] text-[var(--adp-chip-ink)]",
        good: "border border-[var(--adp-good-bd)] bg-[var(--adp-good-bg)] text-[var(--adp-good-ink)]",
        warn: "border border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] text-[var(--adp-warn-ink)]",
        lab: "border border-[var(--adp-lab-bd)] bg-[var(--adp-lab-bg)] text-[var(--adp-lab-ink)]",
        soon: "border border-dashed border-border bg-secondary text-[var(--adp-faint)]",
      },
    },
    defaultVariants: { variant: "type" },
  },
);

export function Badge({
  className,
  variant,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

const buttonVariants = cva(
  "inline-flex items-center gap-2 whitespace-nowrap rounded-md border border-transparent text-[13px] font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50",
  {
    variants: {
      variant: {
        primary: "bg-primary text-primary-foreground hover:bg-primary/90",
        accent:
          "bg-[var(--adp-accent)] text-[var(--adp-accent-ink)] hover:bg-[var(--adp-accent-strong)]",
        outline: "border-border bg-card text-foreground hover:bg-secondary",
        ghost: "text-muted-foreground hover:bg-secondary",
        destructive: "text-[var(--adp-bad)] hover:bg-secondary",
      },
      size: {
        default: "px-3.5 py-[7px]",
        sm: "rounded-[5px] px-2.5 py-1 text-xs",
      },
    },
    defaultVariants: { variant: "outline", size: "default" },
  },
);

export function Button({
  className,
  variant,
  size,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof buttonVariants>) {
  return <button className={cn(buttonVariants({ variant, size }), className)} {...props} />;
}

/** Pill chip used in the top bar. `tone="ok"` prefixes the green link dot. */
export function Chip({
  tone,
  className,
  children,
}: {
  tone?: "ok" | "warn";
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-[3px] text-xs text-muted-foreground",
        tone === "warn" &&
          "border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] text-[var(--adp-warn-ink)]",
        className,
      )}
    >
      {tone === "ok" ? (
        <span className="h-[7px] w-[7px] rounded-full bg-[var(--adp-good)]" aria-hidden />
      ) : null}
      {children}
    </span>
  );
}

/**
 * The dashed callout for a gap in the data (the EPF pattern).
 *
 * It exists because the alternative — rendering nothing — reads as "you hold
 * none of this", which is a different and false statement.
 */
export function EmptyCallout({
  icon = "∅",
  children,
  className,
}: {
  icon?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2.5 rounded-lg border border-dashed border-border p-4 text-[13px] text-muted-foreground",
        className,
      )}
    >
      <span
        className="grid h-[26px] w-[26px] shrink-0 place-items-center rounded-md bg-secondary text-[13px] text-[var(--adp-faint)]"
        aria-hidden
      >
        {icon}
      </span>
      <span>{children}</span>
    </div>
  );
}

/** Amber staleness/notice banner. */
export function WarnBanner({ children }: { children: ReactNode }) {
  return (
    <div className="mb-4 flex items-center gap-2.5 rounded-lg border border-[var(--adp-warn-bd)] bg-[var(--adp-warn-bg)] px-3.5 py-2.5 text-[13px] text-[var(--adp-warn-ink)]">
      {children}
    </div>
  );
}

/**
 * The footer every page in the locked design carries.
 *
 * The Privacy and Terms links are part of that design and part of what a page
 * asking for account access owes the reader, so they ship now even though the
 * pages themselves are a later card's work — a missing link is easier to notice
 * (and to route) than a promise nobody made.
 */
export function PortfolioFooter({ demo }: { demo: boolean }) {
  return (
    <footer className="mt-7 flex flex-wrap items-center gap-3.5 text-xs text-[var(--adp-faint)]">
      <span className="h-2.5 w-2.5 rounded-[3px] bg-[var(--adp-accent)]" aria-hidden />
      <span>
        {demo ? "Synthetic demo data · " : ""}descriptive analytics only · not investment advice
      </span>
      <span className="flex items-center gap-3.5">
        <a className="hover:text-foreground hover:underline" href="/privacy">
          Privacy
        </a>
        <a className="hover:text-foreground hover:underline" href="/terms">
          Terms
        </a>
      </span>
    </footer>
  );
}
