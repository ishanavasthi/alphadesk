/**
 * The footer — and the Privacy/Terms links it carries — must be reachable from
 * the two bare auth routes, `/sign-in` and `/waitlist` (card L1).
 *
 * Both sit outside the marketing group that renders the footer everywhere else,
 * and `/waitlist` collects an email, so a missing policy link there is a real
 * gap. Each route now has a layout that wraps its page in the shared footer;
 * these render that layout and assert the links resolve.
 */

import { render, within } from "@testing-library/react";
import type { ComponentType, ReactNode } from "react";
import { describe, expect, it } from "vitest";

import SignInLayout from "@/app/sign-in/layout";
import WaitlistLayout from "@/app/waitlist/layout";

describe("global footer on the bare auth routes", () => {
  it.each<[string, ComponentType<{ children: ReactNode }>]>([
    ["/sign-in", SignInLayout],
    ["/waitlist", WaitlistLayout],
  ])("renders the footer with Privacy + Terms on %s", (_route, Layout) => {
    const { container } = render(<Layout>
      <div>the form</div>
    </Layout>);

    // The route's own content still renders inside the shell.
    expect(within(container).getByText("the form")).toBeTruthy();

    // And the footer is present, with policy links that actually resolve.
    const footer = container.querySelector("footer");
    expect(footer).not.toBeNull();
    const f = within(footer as HTMLElement);
    expect(f.getByText("Privacy").getAttribute("href")).toBe("/privacy");
    expect(f.getByText("Terms").getAttribute("href")).toBe("/terms");
  });
});
