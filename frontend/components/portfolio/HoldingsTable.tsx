"use client";

import { useMemo, useState } from "react";
import type { PortfolioHolding } from "@/lib/api";
import { inr, inrSigned, num, pctSigned, toneClass, typeLabel, units } from "./format";
import { Badge } from "./ui";

type SortKey =
  | "name"
  | "asset_type"
  | "units"
  | "invested_amount"
  | "current_value"
  | "pnl"
  | "pnl_pct";

const COLUMNS: Array<{ key: SortKey; label: string; num?: boolean; hideSm?: boolean }> = [
  { key: "name", label: "Holding" },
  { key: "asset_type", label: "Type", hideSm: true },
  { key: "units", label: "Units", num: true, hideSm: true },
  { key: "invested_amount", label: "Invested", num: true },
  { key: "current_value", label: "Current", num: true },
  { key: "pnl", label: "P&L", num: true },
  { key: "pnl_pct", label: "Return", num: true },
];

/** The one sentence that explains every `—` on this page. */
const NO_BASIS = "Cost basis not reported by the source";

function value(row: PortfolioHolding, key: SortKey): number | string | null {
  if (key === "name") return row.name || row.symbol || row.external_id;
  if (key === "asset_type") return typeLabel(row.asset_type, row.asset_type_raw);
  return num(row[key]);
}

/** `—`, with the tooltip that says why. Never a computed zero or −100%. */
function Unknown() {
  return (
    <span className="cursor-help text-[var(--adp-faint)]" title={NO_BASIS}>
      —
    </span>
  );
}

/**
 * Sortable holdings table.
 *
 * The column that matters most is **Return**, and what it does *not* show is the
 * point: it is `pnl_pct`, a simple cumulative return, and it is blank whenever
 * the source did not report a cost basis. There is no XIRR anywhere — card C2
 * established that the vendor's own field is dead (0 in every observed row) and
 * that no dated cashflow exists to compute one from, so labelling this
 * money-weighted would be a lie about the arithmetic.
 *
 * A row whose basis is unknown shows `—`; a row whose basis is known and whose
 * value really is zero shows an honest −100%. Those two are different facts and
 * the table refuses to render them the same way.
 */
export function HoldingsTable({ rows }: { rows: PortfolioHolding[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("current_value");
  const [dir, setDir] = useState<-1 | 1>(-1);

  const sorted = useMemo(() => {
    return [...rows].sort((a, b) => {
      const av = value(a, sortKey);
      const bv = value(b, sortKey);
      // Nulls sink to the bottom in both directions: "not reported" is not a
      // small number, and letting it sort as one would rank rows by ignorance.
      if (av === null && bv === null) return 0;
      if (av === null) return 1;
      if (bv === null) return -1;
      if (typeof av === "string" || typeof bv === "string") {
        return String(av).localeCompare(String(bv)) * dir;
      }
      return (av > bv ? 1 : av < bv ? -1 : 0) * dir;
    });
  }, [rows, sortKey, dir]);

  const toggle = (key: SortKey) => {
    if (key === sortKey) setDir((current) => (current === -1 ? 1 : -1));
    else {
      setSortKey(key);
      setDir(-1);
    }
  };

  return (
    <div className="overflow-x-auto">
      <table className="adp-num w-full border-collapse">
        <thead>
          <tr>
            {COLUMNS.map((column) => (
              <th
                key={column.key}
                scope="col"
                aria-sort={
                  sortKey === column.key ? (dir === -1 ? "descending" : "ascending") : "none"
                }
                className={`whitespace-nowrap border-b border-border p-0 text-xs font-medium text-muted-foreground ${
                  column.num ? "text-right" : "text-left"
                } ${column.hideSm ? "hidden sm:table-cell" : ""}`}
              >
                <button
                  type="button"
                  onClick={() => toggle(column.key)}
                  className={`w-full px-2.5 py-2 hover:text-foreground ${
                    column.num ? "text-right" : "text-left"
                  }`}
                >
                  {column.label}
                  <span className="ml-1 text-[9px] text-[var(--adp-faint)]">
                    {sortKey === column.key ? (dir === -1 ? "▼" : "▲") : ""}
                  </span>
                </button>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((row) => {
            const invested = num(row.invested_amount);
            const pnl = num(row.pnl);
            const pnlPct = num(row.pnl_pct);
            return (
              <tr key={`${row.source}:${row.external_id}`} className="hover:bg-background">
                <td className="border-b border-[var(--adp-hairline)] p-2.5 text-[13px]">
                  <span className="font-medium">{row.name || row.symbol || row.external_id}</span>
                  {row.us_exposure ? (
                    <Badge variant="us" className="ml-1.5">
                      US
                    </Badge>
                  ) : null}
                  {row.symbol ? (
                    <div className="text-[11.5px] text-muted-foreground">{row.symbol}</div>
                  ) : null}
                </td>
                <td className="hidden border-b border-[var(--adp-hairline)] p-2.5 text-[13px] sm:table-cell">
                  <Badge variant="type">{typeLabel(row.asset_type, row.asset_type_raw)}</Badge>
                </td>
                <td className="hidden border-b border-[var(--adp-hairline)] p-2.5 text-right text-[13px] sm:table-cell">
                  {units(num(row.units))}
                </td>
                <td className="border-b border-[var(--adp-hairline)] p-2.5 text-right text-[13px]">
                  {invested === null ? <Unknown /> : inr(invested)}
                </td>
                <td className="border-b border-[var(--adp-hairline)] p-2.5 text-right text-[13px]">
                  {inr(num(row.current_value))}
                </td>
                <td className="border-b border-[var(--adp-hairline)] p-2.5 text-right text-[13px]">
                  {pnl === null ? (
                    <Unknown />
                  ) : (
                    <span className={toneClass(pnl)}>{inrSigned(pnl)}</span>
                  )}
                </td>
                <td className="border-b border-[var(--adp-hairline)] p-2.5 text-right text-[13px]">
                  {pnlPct === null ? (
                    <Unknown />
                  ) : (
                    <span className={toneClass(pnlPct)}>{pctSigned(pnlPct)}</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
