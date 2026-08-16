"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  PortfolioError,
  capturePortfolioSnapshot,
  getPortfolioAllocation,
  getPortfolioHistory,
  getPortfolioHoldings,
  getPortfolioSummary,
  startAuthLogin,
  type AllocationSlice,
  type PortfolioHolding,
  type PortfolioSummary,
} from "@/lib/api";
import { AUTH_ENABLED } from "@/lib/auth";
import { useLinkConsent } from "@/components/consent/LinkConsent";
import { AiOverview } from "@/components/portfolio/AiOverview";
import { AllocationBars, AllocationBarsSkeleton } from "@/components/portfolio/AllocationBars";
import { CapStrip } from "@/components/portfolio/CapStrip";
import { HoldingsTable } from "@/components/portfolio/HoldingsTable";
import { NetWorthTrend, toTrendPoints, type TrendPoint } from "@/components/portfolio/NetWorthTrend";
import {
  PortfolioTopBar,
  type CaptureState,
} from "@/components/portfolio/PortfolioTopBar";
import { StalenessBanner } from "@/components/portfolio/StalenessBanner";
import { StatCards } from "@/components/portfolio/StatCards";
import { inr, num, typeLabel } from "@/components/portfolio/format";
import {
  Badge,
  Button,
  Card,
  CardHead,
  PortfolioFooter,
} from "@/components/portfolio/ui";
import {
  ConnectGate,
  LockedState,
  RateLimitedNotice,
  SourceEmptyNotice,
  SourceErrorState,
  UnauthorizedState,
  UnverifiedShapeNotice,
} from "@/components/portfolio/states";

/**
 * `/portfolio` — the D1 dashboard.
 *
 * Implements `docs/design/a-shadcn.html` (with the top-bar actions from
 * `a2-overview.html` and the gate from `a4-shell.html`). Three properties are
 * deliberate and worth stating up front:
 *
 * 1. **Holdings are fetched per asset type, only for the buckets the snapshot
 *    actually reported, one at a time.** The source rate-limits 15 calls/min per
 *    tool; walking the 16-member enum would trip that on an ordinary portfolio,
 *    and the answer for most of it would be `[]` anyway.
 * 2. **Every failure has a shape.** Unlinked is a Connect gate, throttled is a
 *    quiet inline wait, an unverified row shape is a labeled boundary — none of
 *    them is an empty table, because an empty table is a claim about what you
 *    own.
 * 3. **Nothing is synthesized.** The trend draws only the days that were
 *    actually captured — no interpolation, no forward-fill — and when captures
 *    stop, the amber banner says so instead of the line quietly flattening.
 *    A missed day cannot be backfilled from a point-in-time source, so the gap
 *    is the truth and hiding it would be the lie.
 */

/** Pacing between per-asset-type calls. Polite, not a rate-limit workaround. */
const CALL_SPACING_MS = 180;
/** Longest we will sit on a throttle before giving the bucket up for this load. */
const MAX_RETRY_WAIT_S = 20;
/**
 * How long Refresh stays disabled after a load starts.
 *
 * One load re-walks every bucket the snapshot reported — on a diversified
 * account that is most of the source's 15-calls-per-minute-per-tool budget, and
 * a reader who clicks Refresh five times in ten seconds would spend the rest of
 * it on 429s. The cooldown makes the button honest about the cost behind it.
 */
const REFRESH_COOLDOWN_S = 30;

type Phase = "loading" | "ready" | "locked" | "unauthorized" | "connect" | "error";

type BucketStatus = "ok" | "unsupported" | "unverified" | "rate_limited" | "error";

interface Bucket {
  assetType: string;
  label: string;
  status: BucketStatus;
  rows: PortfolioHolding[];
  /** The snapshot's value for this bucket, so an empty table can name the gap. */
  reportedValue: number | null;
  retryAfter: number | null;
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

/**
 * What `?reason=<code>` from the OAuth callback means, in the reader's terms.
 *
 * The backend sends a code from a closed set rather than the broker's own error
 * text: that text is attacker-influenced, and putting it in a query string
 * would hand this origin a string it then has to be careful with. Copy lives
 * here, where it can say something useful; an unrecognised code falls back to
 * `failed`.
 */
const LINK_FAILURES: Record<string, string> = {
  denied: "You declined the IND Money authorisation. Nothing was connected.",
  missing_params: "IND Money sent an incomplete response. Please try again.",
  state: "That connection attempt expired. Please start again.",
  failed: "Connecting to IND Money failed. Please try again.",
};

export default function PortfolioPage() {
  const [phase, setPhase] = useState<Phase>("loading");
  const [errorMessage, setErrorMessage] = useState("");
  const [summary, setSummary] = useState<PortfolioSummary | null>(null);
  const [history, setHistory] = useState<TrendPoint[]>([]);
  const [lastCapturedAt, setLastCapturedAt] = useState<string | null>(null);
  const [buckets, setBuckets] = useState<Bucket[]>([]);
  const [loadingHoldings, setLoadingHoldings] = useState(false);
  const [throttle, setThrottle] = useState<number | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);

  const [cooldown, setCooldown] = useState(0);

  // Sector drill-down: portfolio-wide by default (it rides the snapshot call),
  // one lazy request per asset type the reader actually asks for.
  const [sectorType, setSectorType] = useState<string | null>(null);
  const [sectorSlices, setSectorSlices] = useState<AllocationSlice[] | null>(null);
  const [sectorError, setSectorError] = useState<string | null>(null);
  const [sectorLoading, setSectorLoading] = useState(false);

  const [connectBusy, setConnectBusy] = useState(false);
  const [connectError, setConnectError] = useState<string | null>(null);
  const { begin: beginConsent, dialog: consentDialog } = useLinkConsent();

  const [captureState, setCaptureState] = useState<CaptureState>("idle");

  const aborter = useRef<AbortController | null>(null);
  const sectorAborter = useRef<AbortController | null>(null);
  /**
   * Monotonic id of the newest drill-down request.
   *
   * Aborting the previous fetch is not enough on its own: a response already in
   * flight can resolve after the abort, and the two requests are indistinguishable
   * once the promises are pending. Only the request whose token still matches is
   * allowed to write state, so a stale bucket can never land under a newer chip's
   * label.
   */
  const sectorToken = useRef(0);

  /**
   * Read the outcome the OAuth callback redirected back with, then erase it.
   *
   * The backend used to end the link flow on its own origin with a "you can
   * close this window" page — correct for the popup it was written for, a dead
   * end once every call site navigates the current tab. It now sends the
   * browser here with `?ind=connected` or `?ind=error&reason=<code>`.
   *
   * The parameters are stripped with `replaceState` so a refresh (or a shared
   * URL) cannot replay an outcome that is no longer true. On success there is
   * nothing else to do: the status fetch below finds the link and renders the
   * dashboard.
   */
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const outcome = params.get("ind");
    if (!outcome) return;
    if (outcome === "error") {
      const reason = params.get("reason") ?? "";
      setConnectError(LINK_FAILURES[reason] ?? LINK_FAILURES.failed);
    }
    params.delete("ind");
    params.delete("reason");
    const rest = params.toString();
    window.history.replaceState(
      null,
      "",
      window.location.pathname + (rest ? `?${rest}` : ""),
    );
  }, []);

  useEffect(() => {
    // Flag off there is no credential this build can send, so it is locked.
    // Flag on, a signed-out visitor is a normal state the backend answers 401
    // for, and `unauthorized` is what renders.
    if (!AUTH_ENABLED) {
      setPhase("locked");
      return;
    }

    setCooldown(REFRESH_COOLDOWN_S);
    const controller = new AbortController();
    aborter.current?.abort();
    aborter.current = controller;
    const { signal } = controller;

    const run = async () => {
      setPhase("loading");
      setThrottle(null);
      setBuckets([]);
      // A reload invalidates any drill-down in flight along with everything else.
      sectorToken.current += 1;
      sectorAborter.current?.abort();
      sectorAborter.current = null;
      setSectorType(null);
      setSectorSlices(null);
      setSectorError(null);
      setSectorLoading(false);

      let snapshot: PortfolioSummary;
      try {
        snapshot = await getPortfolioSummary(signal);
      } catch (err) {
        if (signal.aborted) return;
        const failure = err as PortfolioError;
        if (failure.code === "locked") setPhase("locked");
        else if (failure.code === "unauthorized") setPhase("unauthorized");
        else if (failure.code === "not_linked") setPhase("connect");
        else {
          setErrorMessage(failure.message || "The portfolio source could not be read.");
          setPhase("error");
        }
        return;
      }
      if (signal.aborted) return;
      setSummary(snapshot);
      setPhase("ready");

      try {
        const captured = await getPortfolioHistory(90, signal);
        if (signal.aborted) return;
        setHistory(toTrendPoints(captured.points));
        setLastCapturedAt(captured.last_captured_at);
      } catch {
        // History is additive; its absence must never take the page down.
        if (!signal.aborted) setHistory([]);
      }

      await loadHoldings(snapshot, signal, setBuckets, setLoadingHoldings, setThrottle);
    };

    void run();
    return () => {
      controller.abort();
      sectorAborter.current?.abort();
    };
  }, [refreshKey]);

  // Counts the Refresh cooldown down one second at a time, purely for the label.
  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((seconds) => seconds - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const refresh = useCallback(() => setRefreshKey((key) => key + 1), []);

  /**
   * Take today's snapshot now, and reload the history line when one lands.
   *
   * The button is awaited rather than fire-and-forget: someone who pressed it is
   * owed an answer. It walks every bucket the snapshot reports, paced, so this
   * takes seconds — which is why the label says "Capturing…" instead of a bare
   * spinner. A day that already has a row comes back `already_captured`, and the
   * label says exactly that rather than pretending to have done work.
   */
  const capture = useCallback(async () => {
    setCaptureState("busy");
    try {
      const result = await capturePortfolioSnapshot();
      if (result.status === "captured") {
        setCaptureState("done");
        const captured = await getPortfolioHistory(90);
        setHistory(toTrendPoints(captured.points));
        setLastCapturedAt(captured.last_captured_at);
      } else if (result.status === "already_captured") {
        setCaptureState("existing");
      } else if (result.status === "in_flight") {
        // Opening this page starts a capture when today's row is missing, so
        // pressing the button a second later legitimately finds one running.
        // Nothing failed, and saying "failed" would send the reader looking for
        // a problem that does not exist.
        setCaptureState("in_flight");
      } else {
        // `skipped` (no usable link) and `failed` (the source could not be
        // read) are both "no snapshot exists for today", and the button should
        // not claim otherwise.
        setCaptureState("failed");
      }
    } catch {
      setCaptureState("failed");
    }
  }, []);

  /**
   * Return the button to "Capture snapshot" a few seconds after it settles.
   *
   * Every terminal state is a *result*, not a mode: "Captured" is worth reading
   * once and then in the way. Without this the only route back to a usable
   * button is a page reload — which is a silly thing to ask of someone whose
   * capture just failed and who wants to try again.
   */
  useEffect(() => {
    if (captureState === "idle" || captureState === "busy") return;
    const timer = setTimeout(() => setCaptureState("idle"), 5000);
    return () => clearTimeout(timer);
  }, [captureState]);

  const runConnect = useCallback(async () => {
    setConnectBusy(true);
    setConnectError(null);
    try {
      const url = await startAuthLogin();
      window.location.href = url;
    } catch (err) {
      setConnectError((err as Error).message);
      setConnectBusy(false);
    }
  }, []);

  // The Connect button routes through the link-time consent screen (card L1) —
  // there is no path to `/auth/login` here that skips it.
  const connect = useCallback(() => beginConsent(runConnect), [beginConsent, runConnect]);

  /**
   * Switch the sector card to one asset type (or back to the whole portfolio).
   *
   * Three clicks in a second used to be three unguarded fetches racing to write
   * the same state, and the slowest one won — the card could end up showing
   * mutual-fund sectors under an "Within US stocks" heading, which is worse than
   * showing nothing. Now the previous request is aborted, only the newest token
   * may write, and the card renders a skeleton rather than the outgoing data
   * while a fetch is open. The label and the bars can never disagree.
   */
  const chooseSector = useCallback(async (assetType: string | null) => {
    const token = (sectorToken.current += 1);
    sectorAborter.current?.abort();
    sectorAborter.current = null;

    setSectorType(assetType);
    setSectorError(null);
    if (assetType === null) {
      setSectorSlices(null);
      setSectorLoading(false);
      return;
    }

    const controller = new AbortController();
    sectorAborter.current = controller;
    setSectorSlices(null);
    setSectorLoading(true);
    try {
      const result = await getPortfolioAllocation(assetType, "sector", controller.signal);
      if (token !== sectorToken.current) return;
      setSectorSlices(result.slices);
    } catch (err) {
      if (token !== sectorToken.current || controller.signal.aborted) return;
      setSectorSlices([]);
      setSectorError((err as PortfolioError).message);
    } finally {
      if (token === sectorToken.current) setSectorLoading(false);
    }
  }, []);

  const holdings = useMemo(() => buckets.flatMap((bucket) => bucket.rows), [buckets]);
  const drillTypes = useMemo(
    () =>
      (summary?.by_asset_type ?? [])
        .filter((slice) => slice.asset_type && slice.asset_type !== "UNKNOWN")
        .map((slice) => slice.asset_type as string),
    [summary],
  );

  if (phase === "locked") return <LockedState />;
  if (phase === "unauthorized") return <UnauthorizedState />;
  if (phase === "connect") {
    return (
      <>
        <ConnectGate onConnect={connect} busy={connectBusy} error={connectError} />
        {consentDialog}
      </>
    );
  }
  if (phase === "error") return <SourceErrorState message={errorMessage} onRetry={refresh} />;
  if (phase === "loading" || !summary) {
    return (
      <div className="pt-24 text-center text-[13px] text-muted-foreground">
        Reading your portfolio…
      </div>
    );
  }

  const demo = summary.source === "stub";
  // Never the whole-portfolio fallback while a drill-down is selected: that
  // would print portfolio-wide sectors under a "Within <asset type>" heading.
  const sectorSource = sectorType === null ? summary.by_sector : sectorSlices ?? [];

  return (
    <>
      <PortfolioTopBar
        linkHealth={summary.link_health}
        demo={demo}
        onRefresh={refresh}
        refreshing={loadingHoldings}
        cooldown={cooldown}
        onCapture={() => void capture()}
        captureState={captureState}
      />

      <h1 className="text-xl font-semibold tracking-[-0.02em]">Portfolio</h1>
      <div className="mb-5 text-[13px] text-muted-foreground">
        {demo ? "Invented demo portfolio" : "Linked account snapshot"} · read{" "}
        {new Date(summary.as_of).toLocaleString("en-IN")}
      </div>

      {/* Above the numbers on purpose: if the history has stopped accruing, the
          reader needs to know that before they read a trend line drawn from it. */}
      <StalenessBanner lastCapturedAt={lastCapturedAt} />

      {throttle !== null ? (
        <div className="mb-4">
          <RateLimitedNotice retryAfter={throttle} />
        </div>
      ) : null}

      <StatCards
        summary={summary}
        holdingsCount={holdings.length}
        countIsPartial={loadingHoldings}
      />

      {/* AI overview (card A1). Streams its own metrics + narrative and degrades
          to "AI overview unavailable" on its own — it never blocks the rest of
          the dashboard, and every number here renders with or without the model. */}
      <AiOverview />

      <div className="mt-4 grid gap-4 lg:grid-cols-[2fr_1fr]">
        <NetWorthTrend points={history} lastCapturedAt={lastCapturedAt} />
        <Card>
          <CardHead title="Market cap mix" desc="Equity holdings by cap band" />
          <CapStrip slices={summary.by_market_cap} />
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHead title="Allocation by asset type" desc="Share of current value" />
          <AllocationBars slices={summary.by_asset_type} labelMode="type" />
        </Card>
        <Card>
          <CardHead
            title="Allocation by sector"
            desc={
              sectorType
                ? `Within ${typeLabel(sectorType)} · fetched on demand`
                : "Whole portfolio, as the snapshot reports it"
            }
          />
          <div className="mb-3 flex flex-wrap gap-1.5">
            <Button
              variant={sectorType === null ? "primary" : "outline"}
              size="sm"
              onClick={() => void chooseSector(null)}
            >
              Whole portfolio
            </Button>
            {drillTypes.map((type) => (
              <Button
                key={type}
                variant={sectorType === type ? "primary" : "outline"}
                size="sm"
                onClick={() => void chooseSector(type)}
              >
                {typeLabel(type)}
              </Button>
            ))}
          </div>
          {sectorError ? (
            <div className="mb-2 text-xs text-muted-foreground">{sectorError}</div>
          ) : null}
          {sectorLoading ? (
            <AllocationBarsSkeleton />
          ) : (
            <AllocationBars slices={sectorSource} />
          )}
        </Card>
      </div>

      <Card className="mt-4">
        <CardHead
          title="Holdings"
          desc={
            <>
              Click a column to sort · &ldquo;—&rdquo; means the source did not report a cost
              basis
              {loadingHoldings ? " · still loading buckets" : ""}
            </>
          }
        />
        <HoldingsTable rows={holdings} />
        {buckets.map((bucket) => {
          if (bucket.status === "unverified") {
            return <UnverifiedShapeNotice key={bucket.assetType} label={bucket.label} />;
          }
          if (bucket.status === "rate_limited") {
            return (
              <div key={bucket.assetType} className="mt-3.5">
                <RateLimitedNotice retryAfter={bucket.retryAfter} />
              </div>
            );
          }
          if (bucket.status === "unsupported") {
            return (
              <SourceEmptyNotice
                key={bucket.assetType}
                label={bucket.label}
                value={inr(bucket.reportedValue)}
              />
            );
          }
          if (bucket.status === "error") {
            return (
              <div key={bucket.assetType} className="mt-3.5 text-xs text-muted-foreground">
                {bucket.label} rows could not be read from the source.
              </div>
            );
          }
          if (!bucket.rows.length && (bucket.reportedValue ?? 0) > 0) {
            return (
              <SourceEmptyNotice
                key={bucket.assetType}
                label={bucket.label}
                value={inr(bucket.reportedValue)}
              />
            );
          }
          return null;
        })}
        {!holdings.length && !loadingHoldings ? (
          <div className="mt-3.5 text-[13px] text-muted-foreground">
            No holding-level rows were returned for any bucket in this snapshot.
          </div>
        ) : null}
      </Card>

      {demo ? (
        <div className="mt-4">
          <Badge variant="warn">
            Synthetic data — every name, value and identifier below is invented.
          </Badge>
        </div>
      ) : null}

      <PortfolioFooter demo={demo} />
    </>
  );
}

/**
 * Fetch holdings for the buckets the snapshot reported, one call at a time.
 *
 * Ordered by value so the biggest positions appear first, deduplicated (several
 * out-of-enum buckets share the single `UNKNOWN` query), and paced. A throttled
 * bucket waits out the source's own suggested delay once, then gives up for this
 * load rather than hammering a server that just said no.
 */
async function loadHoldings(
  snapshot: PortfolioSummary,
  signal: AbortSignal,
  setBuckets: (update: (current: Bucket[]) => Bucket[]) => void,
  setLoadingHoldings: (value: boolean) => void,
  setThrottle: (value: number | null) => void,
): Promise<void> {
  const wanted = new Map<string, { label: string; value: number | null }>();
  for (const slice of snapshot.by_asset_type) {
    const key = slice.asset_type;
    if (!key) continue;
    const label =
      key === "UNKNOWN"
        ? typeLabel(null, slice.asset_type_raw)
        : typeLabel(key, slice.asset_type_raw);
    const existing = wanted.get(key);
    const value = num(slice.current_value);
    if (existing) {
      existing.value = (existing.value ?? 0) + (value ?? 0);
    } else {
      wanted.set(key, { label, value });
    }
  }

  const ordered = [...wanted.entries()].sort(
    (a, b) => (b[1].value ?? 0) - (a[1].value ?? 0),
  );

  setLoadingHoldings(true);
  for (const [assetType, meta] of ordered) {
    if (signal.aborted) break;

    let bucket: Bucket = {
      assetType,
      label: meta.label,
      status: "ok",
      rows: [],
      reportedValue: meta.value,
      retryAfter: null,
    };

    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        const response = await getPortfolioHoldings(assetType, signal);
        bucket = { ...bucket, status: "ok", rows: response.holdings };
        break;
      } catch (err) {
        if (signal.aborted) return;
        const failure = err as PortfolioError;
        if (
          failure.code === "rate_limited" &&
          attempt === 0 &&
          (failure.retryAfter ?? 0) <= MAX_RETRY_WAIT_S
        ) {
          bucket = { ...bucket, status: "rate_limited", retryAfter: failure.retryAfter };
          setThrottle(failure.retryAfter);
          await sleep((failure.retryAfter ?? 5) * 1000);
          continue;
        }
        if (failure.code === "rate_limited") {
          bucket = { ...bucket, status: "rate_limited", retryAfter: failure.retryAfter };
        } else if (failure.code === "unverified_shape") {
          bucket = { ...bucket, status: "unverified" };
        } else if (
          failure.code === "unsupported_asset_type" ||
          failure.code === "unknown_asset_type"
        ) {
          // The source cannot enumerate this bucket at all (its own snapshot
          // reports it, its holdings endpoint refuses it). That is the EPF-style
          // gap, not an error.
          bucket = { ...bucket, status: "unsupported" };
        } else {
          bucket = { ...bucket, status: "error" };
        }
        break;
      }
    }

    if (signal.aborted) return;
    setThrottle(null);
    setBuckets((current) => [...current, bucket]);
    await sleep(CALL_SPACING_MS);
  }
  if (!signal.aborted) setLoadingHoldings(false);
}
