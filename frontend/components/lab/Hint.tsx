import type { ReactNode } from "react";

/**
 * Lightweight, accessible hover/focus tooltip (no extra deps). Wrap any element;
 * `content` is shown above it on hover and on keyboard focus.
 *
 * The styling lives in `app/portfolio/portfolio.css` as `.adp-hint` rather than
 * here: it is a positioned, themed surface, and keeping it in the token file is
 * what makes it invert with `data-adp-theme` for free (issue #18 — it used to be
 * `.hint` in `globals.css`, painted in the terminal's popover colours).
 */
export function Hint({ children, content }: { children: ReactNode; content: ReactNode }) {
  return (
    <span className="group relative inline-flex cursor-help" tabIndex={0}>
      {children}
      <span role="tooltip" className="adp-hint">
        {content}
      </span>
    </span>
  );
}

/** The tooltip's small uppercase caption — "Risk Manager · verdict". */
export function HintHead({ children }: { children: ReactNode }) {
  return <span className="adp-hint-head">{children}</span>;
}
