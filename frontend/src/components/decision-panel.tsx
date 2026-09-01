"use client";

import { useState } from "react";
import { LockSimpleIcon, SpinnerGapIcon } from "@phosphor-icons/react/dist/ssr";

import { formatMinor } from "@/lib/money";
import { REASON_CODES, type Role } from "@/lib/types";

type Action = "approve" | "reject" | "override";
type Phase = "idle" | "submitting" | "done" | "error";

/**
 * The decision panel.
 *
 * Two things here are deliberate and worth not "improving" later:
 *
 * 1. No optimistic update. A financial approval must reflect what the
 *    server actually did, including a 403 from the material-amount rule.
 *    Half a second of honesty beats a UI that shows an approval that did
 *    not happen.
 *
 * 2. The disabled state explains *which* rule blocked the action and who
 *    can perform it. Hiding the button would be easier and would leave
 *    the analyst guessing. The server rejects the call either way; this
 *    is only about not wasting their time.
 */
export function DecisionPanel({
  amountAtRiskMinor,
  currency,
  requiresControllerApproval,
  viewerRole,
  reviewThresholdMinor,
}: {
  amountAtRiskMinor: string;
  currency: string;
  requiresControllerApproval: boolean;
  viewerRole: Role;
  reviewThresholdMinor: string;
}) {
  const [action, setAction] = useState<Action>("approve");
  const [reasonCode, setReasonCode] = useState<string>("");
  const [note, setNote] = useState("");
  const [phase, setPhase] = useState<Phase>("idle");
  const [message, setMessage] = useState<string | null>(null);

  const canDecideAtAll = viewerRole !== "analyst";
  const blockedByAmount =
    requiresControllerApproval && viewerRole !== "controller" && viewerRole !== "admin";
  const blocked = !canDecideAtAll || blockedByAmount;

  const overrideNeedsReason = action === "override" && !reasonCode;
  const disabled = blocked || phase === "submitting" || overrideNeedsReason;

  const blockReason = !canDecideAtAll
    ? `An analyst cannot decide a case. A reviewer or controller must action this one.`
    : `This case is above the ${formatMinor(reviewThresholdMinor, currency)} review threshold, so only a controller can approve it.`;

  async function submit() {
    setPhase("submitting");
    setMessage(null);
    // Placeholder for POST /v1/exceptions/{id}/decision with an
    // Idempotency-Key. The server, not this component, is the authority.
    await new Promise((r) => setTimeout(r, 600));
    setPhase("error");
    setMessage("Not wired up yet: the decision endpoint lands with apps/api.");
  }

  return (
    <section
      className="border"
      style={{ background: "var(--surface)", borderColor: "var(--line)", borderRadius: "var(--radius)" }}
    >
      <header className="border-b px-4 py-2.5" style={{ borderColor: "var(--line)" }}>
        <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
          Decision
        </h2>
      </header>

      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex flex-col gap-1.5">
          <span className="label">Action</span>
          <div className="flex gap-1">
            {(["approve", "reject", "override"] as const).map((a) => {
              const isActive = action === a;
              return (
                <button
                  key={a}
                  type="button"
                  onClick={() => setAction(a)}
                  className="flex-1 border px-2 py-1.5 text-[12.5px] capitalize transition-colors duration-100 active:translate-y-px"
                  style={{
                    borderRadius: "var(--radius)",
                    borderColor: isActive ? "var(--ink)" : "var(--line)",
                    background: isActive ? "var(--ink)" : "transparent",
                    color: isActive ? "var(--surface)" : "var(--ink-2)",
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
              value={reasonCode}
              onChange={(e) => setReasonCode(e.target.value)}
              className="w-full border px-2 py-1.5 text-[12.5px]"
              style={{
                borderRadius: "var(--radius)",
                borderColor: "var(--line)",
                background: "var(--surface)",
                color: "var(--ink)",
              }}
            >
              <option value="">Select a reason</option>
              {REASON_CODES.map((r) => (
                <option key={r.code} value={r.code}>
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
            rows={3}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="What you checked, and what you concluded."
            className="w-full resize-y border px-2 py-1.5 text-[12.5px]"
            style={{
              borderRadius: "var(--radius)",
              borderColor: "var(--line)",
              background: "var(--surface)",
              color: "var(--ink)",
            }}
          />
          <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            Recorded in the audit trail against your name and role.
          </p>
        </div>

        <button
          type="button"
          onClick={submit}
          disabled={disabled}
          className="flex w-full items-center justify-center gap-2 whitespace-nowrap px-3 py-2 text-[12.5px] font-medium transition-colors duration-100 active:translate-y-px"
          style={{
            borderRadius: "var(--radius)",
            background: disabled ? "var(--surface-2)" : "var(--flag)",
            color: disabled ? "var(--ink-3)" : "#ffffff",
            cursor: disabled ? "not-allowed" : "pointer",
          }}
        >
          {phase === "submitting" && <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />}
          {blocked && <LockSimpleIcon size={13} weight="bold" />}
          {phase === "submitting" ? "Submitting" : `Submit ${action}`}
        </button>

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

        {phase === "error" && message && (
          <p
            className="border-l-2 py-1 pl-2.5 text-[12px]"
            style={{ borderColor: "var(--flag)", color: "var(--ink-2)" }}
          >
            {message}
          </p>
        )}
      </div>
    </section>
  );
}
