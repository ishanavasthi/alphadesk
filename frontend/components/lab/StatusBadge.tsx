import { Hint, HintHead } from "@/components/lab/Hint";
import { Badge } from "@/components/ui/adp";
import type { AnalystAction, RiskDecision } from "@/lib/api";

/**
 * The two verdicts every candidate carries: what the Analyst called, and what
 * the Risk Manager did with it.
 *
 * Both are DECISION badges (issue #18) rather than the terminal's mono
 * `.pill-*`. The mapping is the point: a verdict is *status*, so it takes the
 * status tints — `good` for cleared, `warn` for a caution, `bad` for a
 * rejection — and never the accent, which belongs to charts and emphasis.
 */

const RISK_VARIANT: Record<RiskDecision, "good" | "warn" | "bad"> = {
  PASS: "good",
  FLAG: "warn",
  REJECT: "bad",
};

const RISK_DESC: Record<RiskDecision, string> = {
  PASS: "Cleared every guardrail with nothing flagged.",
  FLAG: "Cleared the guardrails, but with a caution — borderline conviction or thin evidence. Approvable; look before you do.",
  REJECT:
    "Failed a guardrail — conviction below the floor, the sector already full, or the Analyst said avoid.",
};

/** Human wording for the non-fatal `flags` behind a FLAG verdict (B11). */
const FLAG_DESC: Record<string, string> = {
  borderline_confidence: "conviction sits just above the floor",
  thin_evidence: "the call rests on very little data",
};

export function flagLabel(flag: string): string {
  return FLAG_DESC[flag] ?? flag.replace(/_/g, " ");
}

export function RiskBadge({
  decision,
  flags,
}: {
  decision: RiskDecision;
  flags?: string[];
}) {
  const why = flags?.length ? ` (${flags.map(flagLabel).join("; ")})` : "";
  return (
    <Hint
      content={
        <>
          <HintHead>Risk Manager · verdict</HintHead>
          <span>
            <b>{decision}</b> — {RISK_DESC[decision]}
            {why}
          </span>
        </>
      }
    >
      <Badge variant={RISK_VARIANT[decision]}>{decision}</Badge>
    </Hint>
  );
}

const ACTION_VARIANT: Record<AnalystAction, "good" | "warn" | "bad"> = {
  buy: "good",
  hold: "warn",
  avoid: "bad",
};

const ACTION_DESC: Record<AnalystAction, string> = {
  buy: "The thesis favours upside.",
  hold: "Roughly balanced — no strong edge either way.",
  avoid: "The thesis is negative; better left alone.",
};

const ACTION_LABEL: Record<AnalystAction, string> = {
  buy: "Buy",
  hold: "Hold",
  avoid: "Avoid",
};

export function ActionBadge({ action }: { action: AnalystAction }) {
  return (
    <Hint
      content={
        <>
          <HintHead>Analyst · call</HintHead>
          <span>
            <b>{ACTION_LABEL[action]}</b> — {ACTION_DESC[action]}
          </span>
        </>
      }
    >
      <Badge variant={ACTION_VARIANT[action]}>{ACTION_LABEL[action]}</Badge>
    </Hint>
  );
}
