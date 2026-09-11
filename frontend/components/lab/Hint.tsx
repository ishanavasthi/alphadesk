import type { ReactNode } from "react";

/**
 * Lightweight, accessible hover/focus tooltip (no extra deps). Wrap any element;
 * `content` is shown above it on hover and on keyboard focus.
 */
export function Hint({ children, content }: { children: ReactNode; content: ReactNode }) {
  return (
    <span className="group relative inline-flex cursor-help" tabIndex={0}>
      {children}
      <span role="tooltip" className="hint">
        {content}
      </span>
    </span>
  );
}
