import { cn } from "@/lib/utils";
import { Hint } from "@/components/Hint";
import type { AnalystAction, RiskDecision } from "@/lib/api";

const RISK_CLASS: Record<RiskDecision, string> = {
  PASS: "pill-pass",
  FLAG: "pill-flag",
  REJECT: "pill-reject",
};

const RISK_DESC: Record<RiskDecision, string> = {
  PASS: "Cleared all guardrails (confidence >= 0.75).",
  FLAG: "Cleared the guardrails but confidence is borderline (0.70-0.75). Review before approving.",
  REJECT: "Failed a guardrail - confidence < 0.70, sector full, or the analyst said avoid.",
};

export function RiskBadge({ decision }: { decision: RiskDecision }) {
  return (
    <Hint
      content={
        <>
          <span className="hint-head">Risk Manager · verdict</span>
          <span className="hint-body">
            <strong>{decision}</strong> — {RISK_DESC[decision]}
          </span>
        </>
      }
    >
      <span className={cn("pill", RISK_CLASS[decision])}>{decision}</span>
    </Hint>
  );
}

const ACTION_CLASS: Record<AnalystAction, string> = {
  buy: "pill-pass",
  hold: "pill-flag",
  avoid: "pill-reject",
};

const ACTION_DESC: Record<AnalystAction, string> = {
  buy: "Thesis favors upside.",
  hold: "Roughly balanced — no strong edge either way.",
  avoid: "Thesis is negative; better left alone.",
};

export function ActionBadge({ action }: { action: AnalystAction }) {
  return (
    <Hint
      content={
        <>
          <span className="hint-head">Analyst · call</span>
          <span className="hint-body">
            <strong>{action.toUpperCase()}</strong> — {ACTION_DESC[action]}
          </span>
        </>
      }
    >
      <span className={cn("pill", ACTION_CLASS[action])}>{action}</span>
    </Hint>
  );
}
