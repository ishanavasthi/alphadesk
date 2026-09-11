import { cn } from "@/lib/utils";
import { Hint } from "@/components/Hint";
import type { AnalystAction, RiskDecision } from "@/lib/api";

const RISK_CLASS: Record<RiskDecision, string> = {
  PASS: "pill-pass",
  FLAG: "pill-flag",
  REJECT: "pill-reject",
};

const RISK_DESC: Record<RiskDecision, string> = {
  PASS: "Cleared every guardrail with nothing flagged.",
  FLAG: "Cleared the guardrails, but with a caution - borderline conviction or thin evidence. Approvable; look before you do.",
  REJECT: "Failed a guardrail - conviction below the floor, sector already full, or the analyst said avoid.",
};

/** Human wording for the non-fatal `flags` behind a FLAG verdict. */
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
          <span className="hint-head">Risk Manager · verdict</span>
          <span className="hint-body">
            <strong>{decision}</strong> - {RISK_DESC[decision]}
            {why}
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
  hold: "Roughly balanced - no strong edge either way.",
  avoid: "Thesis is negative; better left alone.",
};

export function ActionBadge({ action }: { action: AnalystAction }) {
  return (
    <Hint
      content={
        <>
          <span className="hint-head">Analyst · call</span>
          <span className="hint-body">
            <strong>{action.toUpperCase()}</strong> - {ACTION_DESC[action]}
          </span>
        </>
      }
    >
      <span className={cn("pill", ACTION_CLASS[action])}>{action}</span>
    </Hint>
  );
}
