/**
 * Where dialogs portal to (issue #22).
 *
 * On the dashboard the content has to land inside `#adp-root`, the wrapper that
 * scopes the `[data-adp]` tokens — portaling to `document.body` is what made
 * dialogs come out in the terminal palette. Everywhere else there is no such
 * wrapper and the body default must survive.
 */

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";

afterEach(() => {
  document.getElementById("adp-root")?.remove();
});

function renderDialog() {
  render(
    <Dialog open>
      <DialogContent>
        <DialogTitle>Holding detail</DialogTitle>
      </DialogContent>
    </Dialog>,
  );
  return screen.getByText("Holding detail");
}

describe("dialog portal container", () => {
  it("mounts inside the dashboard wrapper when it exists", () => {
    const root = document.createElement("div");
    root.id = "adp-root";
    root.setAttribute("data-adp", "");
    document.body.appendChild(root);

    expect(root.contains(renderDialog())).toBe(true);
  });

  it("falls back to document.body without a wrapper", () => {
    const title = renderDialog();
    expect(title.closest("[data-adp]")).toBeNull();
    expect(document.body.contains(title)).toBe(true);
  });
});
