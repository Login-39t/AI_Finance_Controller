"use client";

import { useActionState, useState } from "react";
import { useFormStatus } from "react-dom";
import {
  CheckCircleIcon,
  LockSimpleIcon,
  SpinnerGapIcon,
} from "@phosphor-icons/react/dist/ssr";

import { submitDecision, type DecisionState } from "@/lib/case-actions";
import { formatMinor } from "@/lib/money";
import { REASON_CODES, type CaseResolution, type Role } from "@/lib/types";

type Action = "approve" | "reject" | "override" | "dismiss";

/**
 * The decision panel.
 *
 * Three things here are deliberate and worth not "improving" later:
 *
 * 1. No optimistic update. A financial approval must reflect what the
 *    server actually did, including a 403 from the material-amount rule.
 *    Half a second of honesty beats a UI that shows an approval that did
 *    not happen.
 *
 * 2. The disabled state explains *which* rule blocked the action and who
 *    can perform it. Hiding the button would be easier and would leave
 *    the analyst guessing. The server refuses the call either way - this
 *    is only about not wasting their time.
 *
 * 3. The checks below are duplicated on the server, and the server's copy
 *    is the real one. This is a courtesy, not a control.
 */
export function DecisionPanel({
  caseId,
  amountAtRiskMinor,
  currency,
  requiresControllerApproval,
  viewerRole,
  reviewThresholdMinor,
  decided,
}: {
  caseId: string;
  amountAtRiskMinor: string;
  currency: string;
  requiresControllerApproval: boolean;
  viewerRole: Role;
  reviewThresholdMinor: string;
  decided?: {
    resolution: CaseResolution;
    reasonCode?: string | null;
    note?: string | null;
    by?: string | null;
    byRole?: Role | null;
    at?: string | null;
  } | null;
}) {
  const [action, setAction] = useState<Action>("approve");
  const [reasonCode, setReasonCode] = useState<string>("");
  const [state, formAction] = useActionState<DecisionState, FormData>(
    submitDecision,
    { status: "idle", message: null },
  );

  const canDecideAtAll = viewerRole !== "analyst";
  const blockedByAmount =
    requiresControllerApproval && viewerRole !== "controller" && viewerRole !== "admin";
  const blocked = !canDecideAtAll || blockedByAmount;

  const overrideNeedsReason = action === "override" && !reasonCode;

  const blockReason = !canDecideAtAll
    ? "An analyst cannot decide a case. A reviewer or controller must action this one."
    : `This case is above the ${formatMinor(reviewThresholdMinor, currency)} review threshold, so only a controller can approve it.`;

  if (decided) {
    return (
      <section
        className="border backdrop-blur-md"
        style={{
          background: "var(--surface)",
          borderColor: "var(--line)",
          borderRadius: "var(--radius)",
          boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37), inset 0 1px 0 0 rgba(255, 255, 255, 0.08)",
          overflow: "hidden",
        }}
      >
        <header className="border-b px-4 py-2.5" style={{ borderColor: "var(--line)", background: "rgba(255, 255, 255, 0.015)" }}>
          <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
            Decision
          </h2>
        </header>
        <div className="flex flex-col gap-2 px-4 py-3">
          <p className="flex items-center gap-1.5 text-[13px]" style={{ color: "var(--ink)" }}>
            <CheckCircleIcon size={14} weight="fill" style={{ color: "var(--ok)" }} />
            <span className="capitalize">{decided.resolution}</span>
          </p>
          {decided.by && (
            <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
              {decided.by}
              {decided.byRole ? ` · ${decided.byRole}` : ""}
              {decided.at ? ` · ${new Date(decided.at).toLocaleString()}` : ""}
            </p>
          )}
          {decided.reasonCode && (
            <p className="text-[12px]" style={{ color: "var(--ink-2)" }}>
              Reason:{" "}
              {REASON_CODES.find((r) => r.code === decided.reasonCode)?.label ??
                decided.reasonCode}
            </p>
          )}
          {decided.note && (
            <p className="text-[12.5px]" style={{ color: "var(--ink)" }}>
              {decided.note}
            </p>
          )}
          <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            A decided case is not re-decided in place. Reopening it is a separate,
            audited action, so the first verdict is never silently replaced.
          </p>
        </div>
      </section>
    );
  }

  return (
    <section
      className="border backdrop-blur-md"
      style={{
        background: "var(--surface)",
        borderColor: "var(--line)",
        borderRadius: "var(--radius)",
        boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37), inset 0 1px 0 0 rgba(255, 255, 255, 0.08)",
        overflow: "hidden",
      }}
    >
      <header className="border-b px-4 py-2.5" style={{ borderColor: "var(--line)", background: "rgba(255, 255, 255, 0.015)" }}>
        <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
          Decision
        </h2>
      </header>

      <form action={formAction} className="flex flex-col gap-3 px-4 py-3">
        <input type="hidden" name="caseId" value={caseId} />
        <input type="hidden" name="action" value={action} />

        <div className="flex flex-col gap-1.5">
          <span className="label">Action</span>
          <div
            className="flex gap-1 p-1"
            style={{
              background: "var(--surface-2)",
              borderRadius: "var(--radius)",
              border: "1px solid var(--line)",
              backdropFilter: "blur(12px)",
            }}
          >
            {(["approve", "reject", "override", "dismiss"] as const).map((a) => {
              const isActive = action === a;
              return (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAction(a)}
                  className="flex-1 px-2.5 py-1.5 text-[12.5px] capitalize font-medium transition-all duration-150 active:translate-y-px"
                  style={{
                    borderRadius: "calc(var(--radius) - 3px)",
                    borderColor: isActive ? "var(--line)" : "transparent",
                    background: isActive ? "var(--surface-3)" : "transparent",
                    color: isActive ? "var(--ink)" : "var(--ink-2)",
                    boxShadow: isActive ? "0 2px 8px rgba(0, 0, 0, 0.35), inset 0 1px 0 rgba(255, 255, 255, 0.1)" : undefined,
                  }}
                >
                  {a}
                </button>
              );
            })}
          </div>
        </div>

        {action === "override" && (
          <div className="flex flex-col gap-1">
            <label htmlFor="reason" className="label">
              Reason code, required
            </label>
            <select
              id="reason"
              name="reasonCode"
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
              className="w-full border px-3 py-2 text-[12.5px] cursor-pointer"
              style={{
                borderRadius: "var(--radius)",
                borderColor: "var(--line)",
                background: "var(--surface-2)",
                color: "var(--ink)",
                backdropFilter: "blur(12px)",
              }}
            >
              <option value="" style={{ background: "#0f121a", color: "var(--ink)" }}>Select a reason</option>
              {REASON_CODES.map((r) => (
                <option key={r.code} value={r.code} style={{ background: "#0f121a", color: "var(--ink)" }}>
                  {r.label}
                </option>
              ))}
            </select>
          </div>
        )}

        <div className="flex flex-col gap-1">
          <label htmlFor="note" className="label">
            Note
          </label>
          <textarea
            id="note"
            name="note"
            rows={3}
            placeholder="What you checked, and what you concluded."
            className="w-full resize-y border px-3 py-2 text-[12.5px]"
            style={{
              borderRadius: "var(--radius)",
              borderColor: "var(--line)",
              background: "var(--surface-2)",
              color: "var(--ink)",
              backdropFilter: "blur(12px)",
            }}
          />
          <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            Recorded in the audit trail against your name and role.
          </p>
        </div>

        <SubmitButton
          action={action}
          blocked={blocked}
          overrideNeedsReason={overrideNeedsReason}
        />

        {blocked && (
          <p
            className="border-l-2 py-1 pl-2.5 text-[12px]"
            style={{ borderColor: "var(--warn)", color: "var(--ink-2)" }}
          >
            {blockReason} Amount at risk is {formatMinor(amountAtRiskMinor, currency)}.
          </p>
        )}

        {overrideNeedsReason && !blocked && (
          <p className="text-[12px]" style={{ color: "var(--warn)" }}>
            Choose a reason code before submitting an override.
          </p>
        )}

        {state.status !== "idle" && state.message && (
          <p
            className="border-l-2 py-1.5 pl-3 text-[12px] rounded-r-[var(--radius)]"
            style={{
              borderColor: state.status === "ok" ? "var(--ok)" : "var(--danger)",
              background: state.status === "ok" ? "var(--ok-wash)" : "var(--danger-wash)",
              color: state.status === "ok" ? "var(--ok)" : "var(--danger)",
            }}
            role="status"
          >
            {state.message}
          </p>
        )}
      </form>
    </section>
  );
}

function SubmitButton({
  action,
  blocked,
  overrideNeedsReason,
}: {
  action: Action;
  blocked: boolean;
  overrideNeedsReason: boolean;
}) {
  const { pending } = useFormStatus();
  const disabled = blocked || pending || overrideNeedsReason;

  return (
    <button
      type="submit"
      disabled={disabled}
      className="flex w-full items-center justify-center gap-2 whitespace-nowrap px-3 py-2.5 text-[12.5px] font-medium transition-all duration-150 active:translate-y-px"
      style={{
        borderRadius: "var(--radius)",
        background: disabled ? "var(--surface-2)" : "var(--flag)",
        color: disabled ? "var(--ink-3)" : "#ffffff",
        cursor: disabled ? "not-allowed" : "pointer",
        backdropFilter: "blur(12px)",
        boxShadow: disabled ? "none" : "0 4px 14px rgba(0, 112, 243, 0.35)",
      }}
    >
      {pending && <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />}
      {blocked && <LockSimpleIcon size={13} weight="bold" />}
      {pending ? "Submitting" : `Submit ${action}`}
    </button>
  );
}
