"use client";

import { useState } from "react";

import {
  createFd,
  deleteFd,
  updateFd,
  type FdCompounding,
  type ManualFd,
  type ManualFdInput,
  type PortfolioError,
} from "@/lib/api";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Badge, Button, Card, CardHead, EmptyCallout } from "@/components/portfolio/ui";
import { inr, inrSigned, num, pct } from "@/components/portfolio/format";
import { useAmountsHidden } from "@/components/portfolio/privacy";
import { usePortfolio } from "@/components/portfolio/PortfolioProvider";

/**
 * Manual fixed deposits (card B10).
 *
 * The one card on this surface whose numbers do **not** come from IND Money, and
 * the caption says so in the header rather than in a footnote — a reader who
 * cannot tell which figures the broker vouches for is worse off than one who
 * sees fewer figures. The vendor's own FD bucket is a separate, measured problem
 * (#65) and this card neither reads nor repairs it.
 *
 * Nothing is computed here. `current_value`, `accrued_interest` and `matured`
 * arrive already derived from the terms on every read, which is what "tracking"
 * means for an instrument whose value is computable rather than quoted. This
 * file's arithmetic is one sum — the card's own total of rows already in hand —
 * and its only other logic is the validation, which deliberately mirrors the
 * API's so a mistyped rate is answered instantly instead of by a 422.
 *
 * Writes never patch a row in place: they call the API and then await the
 * provider's `refreshFds`, because an edited rate changes an accrual only the
 * backend recomputes. An optimistic list would be a list of numbers this app
 * made up.
 */

/** The compounding vocabulary, in the API's own terms. */
const COMPOUNDING: Array<{ value: FdCompounding; label: string }> = [
  { value: "monthly", label: "Monthly" },
  { value: "quarterly", label: "Quarterly" },
  { value: "half_yearly", label: "Half-yearly" },
  { value: "yearly", label: "Yearly" },
  { value: "simple", label: "Simple interest" },
];

const compoundingLabel = (value: string): string =>
  COMPOUNDING.find((option) => option.value === value)?.label ?? value;

/** The provenance line. Stated in the header, so it is on screen in every state. */
export const PROVENANCE =
  "Tracked by AlphaDesk from the terms you enter — not read from IND Money.";

/** The terms, as the form holds them: strings, exactly as they will be sent. */
export interface FdDraft {
  label: string;
  principal: string;
  rate_pct: string;
  compounding: FdCompounding;
  start_date: string;
  maturity_date: string;
}

export type FdErrors = Partial<Record<keyof FdDraft, string>>;

const EMPTY_DRAFT: FdDraft = {
  label: "",
  principal: "",
  rate_pct: "",
  compounding: "quarterly",
  start_date: "",
  maturity_date: "",
};

/**
 * The API's own limits, checked here first.
 *
 * Every rule below exists on the server too and the server is the authority;
 * this is about the answer arriving while the field is still under the cursor.
 * If the two ever disagree the server wins — a write that passes here and fails
 * there surfaces its message in the dialog rather than being swallowed.
 */
export function validateFd(draft: FdDraft): FdErrors {
  const errors: FdErrors = {};

  const label = draft.label.trim();
  if (!label) errors.label = "Give this deposit a name.";
  else if (label.length > 120) errors.label = "Keep the name under 120 characters.";

  const principal = Number(draft.principal);
  if (!draft.principal.trim() || !Number.isFinite(principal)) {
    errors.principal = "Enter the deposited amount.";
  } else if (principal <= 0) {
    errors.principal = "The principal must be more than ₹0.";
  }

  const rate = Number(draft.rate_pct);
  if (!draft.rate_pct.trim() || !Number.isFinite(rate)) {
    errors.rate_pct = "Enter the annual interest rate.";
  } else if (rate <= 0) {
    errors.rate_pct = "The rate must be more than 0%.";
  } else if (rate > 50) {
    errors.rate_pct = "The rate must be 50% or less.";
  }

  if (!draft.start_date) errors.start_date = "Enter the deposit date.";
  if (!draft.maturity_date) errors.maturity_date = "Enter the maturity date.";
  if (draft.start_date && draft.maturity_date && draft.start_date >= draft.maturity_date) {
    errors.maturity_date = "Maturity must be after the deposit date.";
  }

  return errors;
}

/** `2027-03-14` → `14 Mar 2027`, without going through a timezone. */
export function formatDay(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return iso;
  const months = [
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
  ];
  return `${Number(match[3])} ${months[Number(match[2]) - 1]} ${match[1]}`;
}

/** The terms of an existing row, back in form shape. */
function draftOf(fd: ManualFd): FdDraft {
  return {
    label: fd.label,
    principal: fd.principal,
    rate_pct: fd.rate_pct,
    compounding: fd.compounding,
    start_date: fd.start_date,
    maturity_date: fd.maturity_date,
  };
}

/** The trimmed draft, as the API takes it. */
function payloadOf(draft: FdDraft): ManualFdInput {
  return {
    label: draft.label.trim(),
    principal: draft.principal.trim(),
    rate_pct: draft.rate_pct.trim(),
    compounding: draft.compounding,
    start_date: draft.start_date,
    maturity_date: draft.maturity_date,
  };
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string;
  label: string;
  hint?: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1.5">
      <label htmlFor={id} className="text-[13px] font-medium">
        {label}
      </label>
      {children}
      {error ? (
        <p className="text-xs text-[var(--adp-bad)]">{error}</p>
      ) : hint ? (
        <p className="text-xs text-muted-foreground">{hint}</p>
      ) : null}
    </div>
  );
}

/**
 * Add / Edit, one form.
 *
 * The two differ only in what they start from and which call they end with, and
 * a second copy of the validation is exactly the thing that drifts. `existing`
 * being null is "Add".
 */
export function FdFormDialog({
  open,
  existing,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  existing: ManualFd | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => Promise<void> | void;
}) {
  const [draft, setDraft] = useState<FdDraft>(existing ? draftOf(existing) : EMPTY_DRAFT);
  const [errors, setErrors] = useState<FdErrors>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = (key: keyof FdDraft) => (value: string) =>
    setDraft((current) => ({ ...current, [key]: value } as FdDraft));

  const close = () => {
    setErrors({});
    setFailure(null);
    onOpenChange(false);
  };

  const save = async () => {
    const found = validateFd(draft);
    setErrors(found);
    if (Object.keys(found).length) return;

    setBusy(true);
    setFailure(null);
    try {
      const payload = payloadOf(draft);
      if (existing) await updateFd(existing.id, payload);
      else await createFd(payload);
      await onSaved();
      setBusy(false);
      close();
    } catch (err) {
      // The server is the authority on its own rules — including "there is no
      // database to write to" (503 `no_database`), which is the one failure a
      // reader must never see swallowed as a save.
      setFailure((err as PortfolioError).message || "That deposit could not be saved.");
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{existing ? "Edit fixed deposit" : "Add a fixed deposit"}</DialogTitle>
          <DialogDescription>{PROVENANCE}</DialogDescription>
        </DialogHeader>

        <div className="grid gap-3">
          <Field id="fd-label" label="Name" error={errors.label}>
            <Input
              id="fd-label"
              value={draft.label}
              maxLength={120}
              onChange={(event) => set("label")(event.target.value)}
            />
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="fd-principal" label="Principal (₹)" error={errors.principal}>
              <Input
                id="fd-principal"
                type="number"
                inputMode="decimal"
                className="adp-num"
                value={draft.principal}
                onChange={(event) => set("principal")(event.target.value)}
              />
            </Field>
            <Field id="fd-rate" label="Rate (% a year)" error={errors.rate_pct}>
              <Input
                id="fd-rate"
                type="number"
                inputMode="decimal"
                step="0.01"
                className="adp-num"
                value={draft.rate_pct}
                onChange={(event) => set("rate_pct")(event.target.value)}
              />
            </Field>
          </div>

          <Field
            id="fd-compounding"
            label="Compounding"
            hint="Indian bank FDs compound quarterly unless the certificate says otherwise."
          >
            <select
              id="fd-compounding"
              value={draft.compounding}
              onChange={(event) => set("compounding")(event.target.value)}
              className="flex h-10 w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
            >
              {COMPOUNDING.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </Field>

          <div className="grid gap-3 sm:grid-cols-2">
            <Field id="fd-start" label="Deposited on" error={errors.start_date}>
              <Input
                id="fd-start"
                type="date"
                className="adp-num"
                value={draft.start_date}
                onChange={(event) => set("start_date")(event.target.value)}
              />
            </Field>
            <Field id="fd-maturity" label="Matures on" error={errors.maturity_date}>
              <Input
                id="fd-maturity"
                type="date"
                className="adp-num"
                value={draft.maturity_date}
                onChange={(event) => set("maturity_date")(event.target.value)}
              />
            </Field>
          </div>
        </div>

        {failure ? <p className="text-[13px] text-[var(--adp-bad)]">{failure}</p> : null}

        <DialogFooter>
          <Button type="button" variant="ghost" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="accent"
            onClick={() => void save()}
            disabled={busy}
          >
            {busy ? "Saving…" : existing ? "Save changes" : "Add deposit"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** Delete confirm. Names the deposit, because "Delete?" names nothing. */
export function DeleteFdDialog({
  fd,
  onOpenChange,
  onDeleted,
}: {
  fd: ManualFd | null;
  onOpenChange: (open: boolean) => void;
  onDeleted: () => Promise<void> | void;
}) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  if (!fd) return null;

  const close = () => {
    setFailure(null);
    onOpenChange(false);
  };

  const remove = async () => {
    setBusy(true);
    setFailure(null);
    try {
      await deleteFd(fd.id);
      await onDeleted();
      setBusy(false);
      close();
    } catch (err) {
      setFailure((err as PortfolioError).message || "That deposit could not be removed.");
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(next) => (next ? onOpenChange(true) : close())}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Remove “{fd.label}”?</DialogTitle>
          <DialogDescription>
            AlphaDesk stops tracking this deposit and it leaves your net worth. The deposit
            itself is untouched — this record only ever existed here.
          </DialogDescription>
        </DialogHeader>
        {failure ? <p className="text-[13px] text-[var(--adp-bad)]">{failure}</p> : null}
        <DialogFooter>
          <Button type="button" variant="ghost" onClick={close} disabled={busy}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => void remove()}
            disabled={busy}
          >
            {busy ? "Removing…" : "Remove"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/** One deposit: its terms on the left, what it is worth today on the right. */
function FdRow({
  fd,
  onEdit,
  onDelete,
}: {
  fd: ManualFd;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const accrued = num(fd.accrued_interest);
  return (
    <li className="flex flex-wrap items-start justify-between gap-3 border-b border-[var(--adp-hairline)] py-2.5 last:border-b-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[13px] font-medium">{fd.label}</span>
          {fd.matured ? <Badge variant="warn">Matured</Badge> : null}
        </div>
        <div className="adp-num mt-0.5 text-[11.5px] text-muted-foreground">
          {inr(num(fd.principal))} · {pct(num(fd.rate_pct), 2)} ·{" "}
          {compoundingLabel(fd.compounding)} ·{" "}
          {fd.matured
            ? `matured ${formatDay(fd.maturity_date)} — value frozen`
            : `matures ${formatDay(fd.maturity_date)}${
                fd.days_to_maturity > 0 ? ` · in ${fd.days_to_maturity} days` : ""
              }`}
        </div>
      </div>

      <div className="shrink-0 text-right">
        <div className="adp-num text-[13px] font-semibold">{inr(num(fd.current_value))}</div>
        <div className="adp-num text-[11.5px] text-[var(--adp-good)]">
          {inrSigned(accrued)} interest
        </div>
      </div>

      <div className="flex shrink-0 gap-1.5">
        <Button size="sm" variant="outline" onClick={onEdit}>
          Edit
        </Button>
        <Button
          size="sm"
          variant="destructive"
          onClick={onDelete}
          aria-label={`Remove ${fd.label}`}
        >
          Remove
        </Button>
      </div>
    </li>
  );
}

/**
 * The card itself, given its data.
 *
 * Split from the connected component below so it can be rendered against a
 * fixed list — the provider walks the whole source to exist, and this card's
 * behaviour has nothing to do with that.
 */
export function ManualFdsCard({
  fds,
  loading,
  note,
  error,
  onChanged,
}: {
  fds: ManualFd[];
  loading: boolean;
  /** The backend's own reason the list is empty (no database). Disables writes. */
  note: string | null;
  error: string | null;
  onChanged: () => Promise<void> | void;
}) {
  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<ManualFd | null>(null);
  const [removing, setRemoving] = useState<ManualFd | null>(null);

  // The formatters read the privacy flag at module scope; this is what tells
  // React to paint again when it flips.
  useAmountsHidden();

  // A backend with no database answers the read with a note and refuses the
  // write with a 503. Offering an enabled Add button would be an invitation to
  // type a deposit into a dialog that cannot accept it.
  const writable = note === null;
  const total = fds.reduce((sum, fd) => sum + (num(fd.current_value) ?? 0), 0);

  return (
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <CardHead title="Fixed deposits — manual" desc={PROVENANCE} />
        <Button
          size="sm"
          variant="accent"
          onClick={() => setAdding(true)}
          disabled={!writable}
          title={writable ? undefined : note ?? undefined}
        >
          Add FD
        </Button>
      </div>

      {note ? (
        <div className="mb-3 text-xs text-muted-foreground">
          {note} Adding a deposit is switched off until then — a record of your money must be
          saved somewhere durable or not accepted at all.
        </div>
      ) : null}

      {error ? (
        <EmptyCallout icon="!">{error}</EmptyCallout>
      ) : loading && fds.length === 0 ? (
        <div className="py-1.5 text-[13px] text-muted-foreground">Reading your deposits…</div>
      ) : fds.length === 0 ? (
        <EmptyCallout icon="₹">
          <b className="font-semibold text-foreground">No manual deposits yet.</b> A fixed
          deposit&apos;s value is computed from its terms, not quoted by a market — add one and
          AlphaDesk accrues it for you, every time this page is read.
        </EmptyCallout>
      ) : (
        <>
          <ul className="m-0 list-none p-0">
            {fds.map((fd) => (
              <FdRow
                key={fd.id}
                fd={fd}
                onEdit={() => setEditing(fd)}
                onDelete={() => setRemoving(fd)}
              />
            ))}
          </ul>
          <div className="mt-2.5 flex items-baseline justify-between gap-3 text-xs text-muted-foreground">
            <span>
              {fds.length} deposit{fds.length === 1 ? "" : "s"} tracked here, added to your net
              worth
            </span>
            <span className="adp-num font-semibold text-foreground">{inr(total)}</span>
          </div>
        </>
      )}

      {adding ? (
        <FdFormDialog
          open
          existing={null}
          onOpenChange={(next) => setAdding(next)}
          onSaved={onChanged}
        />
      ) : null}
      {editing ? (
        <FdFormDialog
          open
          existing={editing}
          onOpenChange={(next) => (next ? undefined : setEditing(null))}
          onSaved={onChanged}
        />
      ) : null}
      <DeleteFdDialog
        fd={removing}
        onOpenChange={(next) => (next ? undefined : setRemoving(null))}
        onDeleted={onChanged}
      />
    </Card>
  );
}

/** The card as the page uses it: everything from the provider, nothing fetched here. */
export function ManualFds() {
  const { fds, fdsLoading, fdsNote, fdsError, refreshFds } = usePortfolio();
  return (
    <ManualFdsCard
      fds={fds}
      loading={fdsLoading}
      note={fdsNote}
      error={fdsError}
      onChanged={refreshFds}
    />
  );
}
