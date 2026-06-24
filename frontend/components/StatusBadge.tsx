import { cn } from "@/lib/utils";
import type { AnalystAction, RiskDecision } from "@/lib/api";

const RISK_CLASS: Record<RiskDecision, string> = {
  PASS: "pill-pass",
  FLAG: "pill-flag",
  REJECT: "pill-reject",
};

export function RiskBadge({ decision }: { decision: RiskDecision }) {
  return <span className={cn("pill", RISK_CLASS[decision])}>{decision}</span>;
}

const ACTION_CLASS: Record<AnalystAction, string> = {
  buy: "pill-pass",
  hold: "pill-flag",
  avoid: "pill-reject",
};

export function ActionBadge({ action }: { action: AnalystAction }) {
  return <span className={cn("pill", ACTION_CLASS[action])}>{action}</span>;
}
