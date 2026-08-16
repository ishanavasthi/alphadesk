import { DemoDashboard } from "@/components/shell/DemoDashboard";

/**
 * `/demo` — the public, no-sign-in, no-LLM dashboard (card U1).
 *
 * The critical property of this route is enforced structurally, not by
 * convention: it renders `DemoDashboard`, which reads only committed fixtures
 * (`lib/demo`) and never calls `fetch`. There is no code path from this route to
 * `/portfolio/*`, to `/portfolio/overview`, or to any LLM — proven by loading it
 * with the backend down (`docs/TESTING/U1.md`).
 */
export default function DemoPage() {
  return <DemoDashboard />;
}
