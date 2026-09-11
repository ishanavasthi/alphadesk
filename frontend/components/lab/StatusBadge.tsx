import { Hint, HintHead } from "@/components/lab/Hint";
import { Badge } from "@/components/ui/adp";
import type { AnalystAction, RiskDecision } from "@/lib/api";

/**
 * The two verdicts every candidate carries: what the Analyst called, and what
 * the Risk Manager did with it.
 *
 * Both are DECISION badges now (issue #18) rather than the terminal's mono
 * `.pill-*`. The mapping is the point: a verdict is *status*, so it takes the
 * status tints — `good` for cleared, `warn` for the caution band, `bad` for a
 * rejection — and never the accent, which belongs to charts and emphasis.
 */

const RISK_VARIANT: Record<RiskDecision, "good" | "warn" | "bad"> = {
  PASS: "good",
  FLAG: "warn",
  REJECT: "bad",
};

const RISK_DESC: Record<RiskDecision, string> = {
  PASS: "Cleared every guardrail — confidence at or above 0.75.",
  FLAG: "Cleared the guardrails, but confidence sits in the caution band (0.70–0.75). Read the bear case before approving.",
  REJECT:
    "Failed a guardrail — confidence below 0.70, the sector cap already full, or the Analyst said avoid.",
};

export function RiskBadge({ decision }: { decision: RiskDecision }) {
  return (
    <Hint
      content={
        <>
          <HintHead>Risk Manager · verdict</HintHead>
          <span>
            <b>{decision}</b> — {RISK_DESC[decision]}
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
