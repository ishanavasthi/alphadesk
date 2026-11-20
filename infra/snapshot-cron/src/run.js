// The nightly snapshot trigger, as a pure function of (cron, env, deps).
//
// **Why this exists (#94).** GitHub's `schedule` event is best-effort, and by
// November 2026 it was starting the 23:45 IST run a median 5 h 24 m late. Past
// 06:00 IST the backend (correctly) files a capture under the *next* day, so a
// late night lost its snapshot and mislabelled the following one. Cloudflare
// cron triggers fire on the minute; this Worker is now the primary trigger and
// `.github/workflows/snapshot.yml` is the backup.
//
// It calls the same endpoints, with the same retry discipline, as that
// workflow: retry only what a retry can fix, and fail loudly otherwise, because
// a missed snapshot cannot be backfilled.
//
// Everything with a side effect (fetch, sleep, the clock, logging) is injected,
// so test/run.test.js can drive it on a virtual clock.

/** 23:45 IST primary and 01:00 IST retry — both attributed to the same IST day. */
export const CAPTURE_CRONS = ["15 18 * * *", "30 19 * * *"];
/**
 * Sunday 01:15 IST: drop snapshot_raw payloads older than 90 days.
 * `SUN`, not `0`: Cloudflare numbers weekdays 1-7 with 1 = Sunday and rejects
 * `0` (GitHub's workflow uses `0`, which is Sunday there).
 */
export const PRUNE_CRON = "45 19 * * SUN";

// Budgets. Cloudflare kills a scheduled invocation at 15 minutes of wall time,
// so the worst case is computed, not guessed (and pinned by a test):
//   wake 240 s + one 20 s overrun + 3 x 170 s + 15 + 30 s backoff = 815 s.
export const WAKE_BUDGET_SECONDS = 240;
export const WAKE_FETCH_TIMEOUT_SECONDS = 20;
export const WAKE_SLEEP_SECONDS = 10;
export const TRIGGER_ATTEMPTS = 3;
export const TRIGGER_TIMEOUT_SECONDS = 170;
export const TRIGGER_BACKOFF_SECONDS = [15, 30];
export const PRUNE_TIMEOUT_SECONDS = 120;

const defaultDeps = {
  fetch: (...args) => fetch(...args),
  sleep: (s) => new Promise((resolve) => setTimeout(resolve, s * 1000)),
  now: () => Date.now(),
  log: (...args) => console.log(...args),
};

/** Run the job for the cron expression that fired. Resolves with a summary, throws on failure. */
export async function runScheduled(cron, env, deps = {}) {
  const d = { ...defaultDeps, ...deps };
  const root = (env.BACKEND_URL || "").replace(/\/+$/, "");
  const secret = env.CRON_SECRET || "";

  const isCapture = CAPTURE_CRONS.includes(cron);
  if (!isCapture && cron !== PRUNE_CRON) {
    throw new Error(`Unknown cron "${cron}" — nothing was run.`);
  }
  const missing = [!root && "BACKEND_URL", !secret && "CRON_SECRET"].filter(Boolean);
  if (missing.length) {
    throw new Error(`Not configured: ${missing.join(", ")}. Nothing was run.`);
  }

  if (isCapture) {
    const awake = await wake(root, d);
    if (!awake) {
      throw new Error(
        `Backend never answered 200 within ${WAKE_BUDGET_SECONDS}s (${root}/). ` +
          "Nothing was captured; tonight's data depends on the retry.",
      );
    }
    return capture(root, secret, d);
  }

  // Retention is housekeeping: try to wake, but prune either way.
  await wake(root, d);
  return prune(root, secret, d);
}

async function wake(root, d) {
  // Deadline-based, like the workflow: the budget is a wall clock, so the error
  // message's number is the real one.
  const deadline = d.now() + WAKE_BUDGET_SECONDS * 1000;
  let attempt = 0;
  while (d.now() < deadline) {
    attempt += 1;
    const status = await statusOf(d, `${root}/`, { method: "GET" }, WAKE_FETCH_TIMEOUT_SECONDS);
    d.log(`wake attempt ${attempt}: HTTP ${status}`);
    if (status === 200) return true;
    await d.sleep(WAKE_SLEEP_SECONDS);
  }
  return false;
}

async function capture(root, secret, d) {
  const url = `${root}/internal/snapshot`;
  for (let attempt = 1; attempt <= TRIGGER_ATTEMPTS; attempt += 1) {
    let status = 0;
    let body = null;
    try {
      const res = await d.fetch(url, {
        method: "POST",
        headers: { "x-cron-secret": secret },
        signal: AbortSignal.timeout(TRIGGER_TIMEOUT_SECONDS * 1000),
      });
      status = res.status;
      body = await jsonOrNull(res);
    } catch (err) {
      d.log(`trigger attempt ${attempt}: ${err?.message || err}`);
    }
    if (status) d.log(`trigger attempt ${attempt}: HTTP ${status}`);

    if (status === 200) {
      const errors = Number(body?.errors ?? 0);
      const captured = Number(body?.users_captured ?? 0);
      const day = body?.captured_on ?? "";
      d.log(`snapshot ${day}: captured=${captured} errors=${errors}`, JSON.stringify(body));
      if (errors !== 0) {
        throw new Error(`${errors} user(s) failed to capture for ${day}. Those days cannot be backfilled.`);
      }
      return { kind: "capture", day, captured, errors };
    }
    if (status === 401 || status === 403) {
      throw new Error(`Rejected (${status}): CRON_SECRET does not match the backend's.`);
    }
    if (status === 404 || status === 422) {
      throw new Error(`The backend rejected the request (${status}); check BACKEND_URL is the Space root.`);
    }
    if (status === 503) {
      const code = typeof body?.detail === "object" ? body.detail?.code : undefined;
      if (code === "cron_not_configured" || code === "no_database") {
        throw new Error(`The backend is misconfigured (503 ${code}); retrying would not help.`);
      }
      // An unlabelled 503 is the platform's (a waking Space, an edge hiccup).
    }
    if (attempt < TRIGGER_ATTEMPTS) await d.sleep(TRIGGER_BACKOFF_SECONDS[attempt - 1]);
  }
  throw new Error(`Snapshot trigger failed after ${TRIGGER_ATTEMPTS} attempts (${url}).`);
}

async function prune(root, secret, d) {
  const url = `${root}/internal/prune?days=90`;
  let status = 0;
  let body = null;
  try {
    const res = await d.fetch(url, {
      method: "POST",
      headers: { "x-cron-secret": secret },
      signal: AbortSignal.timeout(PRUNE_TIMEOUT_SECONDS * 1000),
    });
    status = res.status;
    body = await jsonOrNull(res);
  } catch (err) {
    d.log(`prune: ${err?.message || err}`);
  }
  d.log(`prune: HTTP ${status}`, JSON.stringify(body));
  if (status !== 200) throw new Error(`Prune failed (${status}).`);
  return { kind: "prune", result: body };
}

async function statusOf(d, url, init, timeoutSeconds) {
  try {
    const res = await d.fetch(url, { ...init, signal: AbortSignal.timeout(timeoutSeconds * 1000) });
    return res.status;
  } catch {
    return 0;
  }
}

async function jsonOrNull(res) {
  try {
    return JSON.parse(await res.text());
  } catch {
    return null;
  }
}
