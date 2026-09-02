"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { RobotIcon, SpinnerGapIcon } from "@phosphor-icons/react/dist/ssr";

import { runInvestigation, type InvestigateState } from "@/lib/case-actions";

const INITIAL: InvestigateState = { status: "idle", message: null };

/**
 * The button that asks for a grounded AI investigation.
 *
 * The call can take several seconds - it is a live model round-trip - so
 * the pending state is not cosmetic. There is no optimistic result: the
 * panel above re-renders from the server once the investigation is stored,
 * so what the analyst sees is what was actually recorded, including a
 * grounding rejection.
 */
export function InvestigateButton({
  caseId,
  hasInvestigation,
}: {
  caseId: string;
  hasInvestigation: boolean;
}) {
  const [state, action] = useActionState(runInvestigation, INITIAL);

  return (
    <form action={action} className="flex flex-col gap-2">
      <input type="hidden" name="caseId" value={caseId} />
      <SubmitButton hasInvestigation={hasInvestigation} />
      {state.message && (
        <p
          className="text-[12px]"
          style={{
            color:
              state.status === "error"
                ? "var(--flag)"
                : state.status === "rejected"
                  ? "var(--warn)"
                  : "var(--ink-2)",
          }}
        >
          {state.message}
        </p>
      )}
    </form>
  );
}

function SubmitButton({ hasInvestigation }: { hasInvestigation: boolean }) {
  const { pending } = useFormStatus();

  return (
    <button
      type="submit"
      disabled={pending}
      className="flex w-full items-center justify-center gap-2 whitespace-nowrap px-3 py-2 text-[12.5px] font-medium transition-colors duration-100 active:translate-y-px"
      style={{
        borderRadius: "var(--radius)",
        background: pending ? "var(--surface-2)" : "var(--warn)",
        color: pending ? "var(--ink-3)" : "#ffffff",
        cursor: pending ? "not-allowed" : "pointer",
      }}
    >
      {pending ? (
        <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />
      ) : (
        <RobotIcon size={14} weight="regular" />
      )}
      {pending
        ? "Investigating…"
        : hasInvestigation
          ? "Re-run investigation"
          : "Investigate this case"}
    </button>
  );
}
