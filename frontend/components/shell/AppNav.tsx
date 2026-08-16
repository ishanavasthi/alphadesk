"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * The one set of surface links, shared by chromes that look nothing alike.
 *
 * The Lab's dark terminal bar and the dashboard's light header keep their own
 * styling — `className` is where each one says how its links should read — but
 * "which surface am I on" is answered here, once, from the pathname. A link is
 * active for its own route and everything under it, so `/lab/a/<id>` still
 * highlights Lab.
 *
 * Deliberately Clerk-free and flag-free: it is a list of destinations its caller
 * has already decided to show.
 */
export function AppNav({
  links,
  className = "",
}: {
  // `exact` opts a link out of prefix-matching: a tab set where "/portfolio" is
  // Overview must not read active under "/portfolio/holdings".
  links: { href: string; label: string; exact?: boolean }[];
  className?: string;
}) {
  // `usePathname()` has no value outside the app router (tests render these bars
  // on their own); nothing is active then, which is the honest answer.
  const pathname = usePathname();
  return (
    <nav className={`flex items-center gap-4 ${className}`.trim()}>
      {links.map(({ href, label, exact }) => {
        const active =
          pathname === href || (!exact && pathname?.startsWith(`${href}/`));
        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? "page" : undefined}
            className={
              active
                ? "text-foreground font-medium"
                : "text-muted-foreground transition-colors hover:text-foreground"
            }
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
