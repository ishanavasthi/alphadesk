import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { RecaptureDialog } from "@/components/portfolio/RecaptureDialog";

/**
 * Replacing today's snapshot. IND Money serves a stale bank balance until it is
 * refreshed in their app, so the first reading of a day is not necessarily the
 * true one — the dialog shows what it would replace and never claims success it
 * did not get.
 */
const OFFER = { total_value: "439656.50", captured_at: "2026-11-10T01:29:00+00:00" };

describe("<RecaptureDialog/>", () => {
  it("is closed without an offer", () => {
    render(<RecaptureDialog offer={null} onDismiss={() => {}} onRecapture={async () => null} />);
    expect(screen.queryByText(/Replace today/)).toBeNull();
  });

  it("names the stored reading and its IST time", () => {
    render(<RecaptureDialog offer={OFFER} onDismiss={() => {}} onRecapture={async () => null} />);
    expect(screen.getByText("₹4,39,657")).toBeTruthy();
    expect(screen.getByText(/taken at 06:59 IST/)).toBeTruthy();
    expect(screen.getByText(/refresh it in the IND Money app first/)).toBeTruthy();
  });

  it("replaces on confirm", async () => {
    const onRecapture = vi.fn(async () => null);
    render(<RecaptureDialog offer={OFFER} onDismiss={() => {}} onRecapture={onRecapture} />);
    fireEvent.click(screen.getByRole("button", { name: "Replace with a fresh reading" }));
    await waitFor(() => expect(onRecapture).toHaveBeenCalledTimes(1));
  });

  it("stays open with the reason when the earlier reading was kept", async () => {
    render(
      <RecaptureDialog
        offer={OFFER}
        onDismiss={() => {}}
        onRecapture={async () => "IND Money could not be read just now, so today's earlier reading was kept."}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Replace with a fresh reading" }));
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByText(/Replace today/)).toBeTruthy();
  });

  it("keeps the current reading on dismiss", () => {
    const onDismiss = vi.fn();
    render(<RecaptureDialog offer={OFFER} onDismiss={onDismiss} onRecapture={async () => null} />);
    fireEvent.click(screen.getByRole("button", { name: "Keep current" }));
    expect(onDismiss).toHaveBeenCalledTimes(1);
  });
});
