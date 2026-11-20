// Run with `node --test` from infra/snapshot-cron/.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  CAPTURE_CRONS,
  PRUNE_CRON,
  TRIGGER_ATTEMPTS,
  TRIGGER_BACKOFF_SECONDS,
  TRIGGER_TIMEOUT_SECONDS,
  WAKE_BUDGET_SECONDS,
  WAKE_FETCH_TIMEOUT_SECONDS,
  runScheduled,
} from "../src/run.js";

const ENV = { BACKEND_URL: "https://backend.example/", CRON_SECRET: "s3cret" };
const [PRIMARY, RETRY] = CAPTURE_CRONS;

/** A fake world: virtual clock, recorded sleeps and requests, scripted replies. */
function world(script) {
  let now = 0;
  const calls = [];
  const sleeps = [];
  return {
    calls,
    sleeps,
    deps: {
      now: () => now,
      sleep: async (s) => {
        sleeps.push(s);
        now += s * 1000;
      },
      log: () => {},
      fetch: async (url, init = {}) => {
        const call = { url, method: init.method ?? "GET", headers: init.headers ?? {}, signal: init.signal };
        calls.push(call);
        const step = script(call, calls);
        if (step.advance) now += step.advance * 1000;
        if (step.throws) throw new Error(step.throws);
        return new Response(step.body === undefined ? "" : JSON.stringify(step.body), { status: step.status });
      },
    },
  };
}

const isWake = (c) => c.method === "GET";
const ok = { captured_on: "2026-11-21", users_captured: 1, skipped: 4, errors: 0 };

test("primary capture: wakes the backend, then POSTs with the secret", async () => {
  const w = world((c) => (isWake(c) ? { status: 200 } : { status: 200, body: ok }));
  const result = await runScheduled(PRIMARY, ENV, w.deps);

  assert.deepEqual(result, { kind: "capture", day: "2026-11-21", captured: 1, errors: 0 });
  assert.equal(w.calls[0].url, "https://backend.example/");
  assert.equal(w.calls[1].url, "https://backend.example/internal/snapshot");
  assert.equal(w.calls[1].method, "POST");
  assert.equal(w.calls[1].headers["x-cron-secret"], "s3cret");
  assert.ok(w.calls[1].signal, "every request carries a timeout signal");
});

test("the retry cron does the same capture", async () => {
  const w = world((c) => (isWake(c) ? { status: 200 } : { status: 200, body: ok }));
  assert.equal((await runScheduled(RETRY, ENV, w.deps)).kind, "capture");
});

test("a sleeping Space is polled until it answers 200", async () => {
  let wakes = 0;
  const w = world((c) => {
    if (isWake(c)) return { status: ++wakes < 3 ? 503 : 200 };
    return { status: 200, body: ok };
  });
  await runScheduled(PRIMARY, ENV, w.deps);
  assert.equal(wakes, 3);
});

test("a Space that never wakes fails loudly within the wake budget", async () => {
  const w = world((c) => ({ status: 503, advance: 1 }));
  await assert.rejects(runScheduled(PRIMARY, ENV, w.deps), /never answered 200/);
  assert.ok(w.calls.every(isWake), "no capture is attempted against a dead backend");
  const elapsed = w.sleeps.reduce((a, b) => a + b, 0) + w.calls.length;
  assert.ok(elapsed <= WAKE_BUDGET_SECONDS + 10 + 1, `stayed inside the budget (${elapsed}s)`);
});

test("an unlabelled 503 is transient: retried with backoff, then succeeds", async () => {
  let triggers = 0;
  const w = world((c) => {
    if (isWake(c)) return { status: 200 };
    return ++triggers === 1 ? { status: 503, body: { detail: "edge" } } : { status: 200, body: ok };
  });
  await runScheduled(PRIMARY, ENV, w.deps);
  assert.equal(triggers, 2);
  assert.deepEqual(w.sleeps, [TRIGGER_BACKOFF_SECONDS[0]]);
});

for (const status of [401, 403, 404, 422]) {
  test(`HTTP ${status} is not retried — a retry would be just as wrong`, async () => {
    let triggers = 0;
    const w = world((c) => (isWake(c) ? { status: 200 } : (triggers++, { status })));
    await assert.rejects(runScheduled(PRIMARY, ENV, w.deps), new RegExp(String(status)));
    assert.equal(triggers, 1);
  });
}

for (const code of ["cron_not_configured", "no_database"]) {
  test(`our own 503 (${code}) is a misconfiguration, not retried`, async () => {
    let triggers = 0;
    const w = world((c) =>
      isWake(c) ? { status: 200 } : (triggers++, { status: 503, body: { detail: { code } } }),
    );
    await assert.rejects(runScheduled(PRIMARY, ENV, w.deps), new RegExp(code));
    assert.equal(triggers, 1);
  });
}

test("a 200 that reports per-user errors still fails the run", async () => {
  const w = world((c) => (isWake(c) ? { status: 200 } : { status: 200, body: { ...ok, errors: 2 } }));
  await assert.rejects(runScheduled(PRIMARY, ENV, w.deps), /2 user\(s\) failed/);
});

test("network errors are retried, then the run fails after the last attempt", async () => {
  let triggers = 0;
  const w = world((c) => (isWake(c) ? { status: 200 } : (triggers++, { throws: "connection reset" })));
  await assert.rejects(runScheduled(PRIMARY, ENV, w.deps), /failed after 3 attempts/);
  assert.equal(triggers, TRIGGER_ATTEMPTS);
  assert.deepEqual(w.sleeps, TRIGGER_BACKOFF_SECONDS);
});

test("the Sunday prune cron prunes and does not capture", async () => {
  const w = world((c) => (isWake(c) ? { status: 200 } : { status: 200, body: { deleted: 12 } }));
  const result = await runScheduled(PRUNE_CRON, ENV, w.deps);
  assert.equal(result.kind, "prune");
  assert.equal(w.calls[1].url, "https://backend.example/internal/prune?days=90");
  assert.equal(w.calls[1].method, "POST");
  assert.ok(!w.calls.some((c) => c.url.endsWith("/internal/snapshot")));
});

test("a failed prune fails the run", async () => {
  const w = world((c) => (isWake(c) ? { status: 200 } : { status: 500 }));
  await assert.rejects(runScheduled(PRUNE_CRON, ENV, w.deps), /Prune failed \(500\)/);
});

test("an unknown cron does nothing and says so", async () => {
  const w = world(() => ({ status: 200 }));
  await assert.rejects(runScheduled("0 0 * * *", ENV, w.deps), /Unknown cron/);
  assert.equal(w.calls.length, 0);
});

test("missing configuration fails before any request", async () => {
  for (const env of [{ CRON_SECRET: "x" }, { BACKEND_URL: "https://b/" }]) {
    const w = world(() => ({ status: 200 }));
    await assert.rejects(runScheduled(PRIMARY, env, w.deps), /Not configured/);
    assert.equal(w.calls.length, 0);
  }
});

test("worst case fits Cloudflare's 15-minute cron wall-time limit", () => {
  const worst =
    WAKE_BUDGET_SECONDS +
    WAKE_FETCH_TIMEOUT_SECONDS + // one wake request may overrun the deadline
    TRIGGER_ATTEMPTS * TRIGGER_TIMEOUT_SECONDS +
    TRIGGER_BACKOFF_SECONDS.reduce((a, b) => a + b, 0);
  assert.ok(worst < 15 * 60 - 30, `worst case ${worst}s leaves under 30 s of headroom`);
});
