import { Info, Lock, ShieldCheck, UserRound } from "lucide-react";

import { IconTile } from "./primitives";

const ITEMS = [
  {
    icon: Lock,
    title: "Read-only broker access",
    body: "The IND Money link can only read. No order can be placed through AlphaDesk, because the capability does not exist.",
  },
  {
    icon: Info,
    title: "Descriptive, never advisory",
    body: "It narrates what is. No forecasts, and no buy or sell calls on your real holdings.",
  },
  {
    icon: ShieldCheck,
    title: "Tokens encrypted at rest",
    body: "Broker tokens are Fernet-encrypted and never returned to the frontend. Prompts carry aggregates and symbols only.",
  },
  {
    icon: UserRound,
    title: "Delete-my-data built in",
    body: "One action revokes broker access upstream first, then cascade-deletes every row of yours.",
  },
];

export function TrustBand() {
  return (
    <div id="trust" className="border-y border-border bg-card">
      <div className="mx-auto max-w-[1120px] px-4 py-11 sm:px-6">
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {ITEMS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="flex items-start gap-3">
              <IconTile className="h-[30px] w-[30px]">
                <Icon className="h-4 w-4" aria-hidden />
              </IconTile>
              <div>
                <h3 className="mb-0.5 text-[13.5px] font-semibold">{title}</h3>
                <p className="text-[12.5px] text-muted-foreground">{body}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
