import "@testing-library/dom";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

/**
 * The minimum jsdom needs to run this app's components.
 *
 * Everything here is a shim for a browser API jsdom does not implement, not a
 * convenience. If a test needs a mock, it mocks it in the test — a setup file
 * that quietly changes behaviour for every suite is how a green run stops
 * meaning anything.
 */

// React Testing Library does not auto-clean when `globals: true` is set without
// its own config hook, and a leaked DOM makes the *second* render in a file
// find two copies of every element.
afterEach(cleanup);

// Recharts' ResponsiveContainer measures its parent; jsdom reports 0×0 and the
// chart renders nothing. Only relevant if a test ever renders the trend with
// points — the current suites do not — but a silent empty chart would be a
// confusing thing to debug from scratch.
if (!("ResizeObserver" in globalThis)) {
  class ResizeObserverStub {
    observe(): void {}
    unobserve(): void {}
    disconnect(): void {}
  }
  (globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver =
    ResizeObserverStub;
}
