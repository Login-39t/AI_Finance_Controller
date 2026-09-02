"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { PlayIcon, SpinnerGapIcon } from "@phosphor-icons/react/dist/ssr";

// `import type` only - a value import from api.ts would drag
// next/headers into this client bundle and fail the build.
import type { Run } from "@/lib/api";
import { formatMinor } from "@/lib/money";
import { pollRun, startRun } from "@/lib/work-actions";

const POLL_MS = 800;
const MAX_POLLS = 300;

/**
 * Start a run and follow it to completion.
 *
 * The POST returns 202 with the work still queued, so this polls until a
 * terminal status. That is the contract, not an implementation detail:
 * the request must not hold a connection open for the length of a
 * reconciliation, and run state lives in the API so a page refresh
 * mid-run picks the run back up rather than losing it.
 */
export function RunPanel({ initialRun }: { initialRun: Run | null }) {
  const router = useRouter();
  const [run, setRun] = useState<Run | null>(initialRun);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Stop the timer on unmount, or a navigated-away page keeps polling.
  useEffect(() => {
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, []);

  async function poll(runId: string, attempt = 0) {
    if (attempt > MAX_POLLS) {
      setError("the run did not finish in time; check the API logs");
      setBusy(false);
      return;
    }
    const result = await pollRun(runId);
    if (!result.ok || !result.data) {
      setError(result.error ?? "lost track of the run");
      setBusy(false);
      return;
    }

    setRun(result.data);
    if (result.data.status === "completed" || result.data.status === "failed") {
      setBusy(false);
      router.refresh();
      return;
    }
    timer.current = setTimeout(() => poll(runId, attempt + 1), POLL_MS);
  }

  async function start() {
    setBusy(true);
    setError(null);

    const result = await startRun();
    if (!result.ok || !result.data) {
      setError(result.error ?? "could not start a run");
      setBusy(false);
      return;
    }
    setRun(result.data);
    poll(result.data.id);
  }

  const metrics = run?.metrics;

  return (
    <section
      className="border"
      style={{
        background: "var(--surface)",
        borderColor: "var(--line)",
        borderRadius: "var(--radius)",
      }}
    >
      <header
        className="flex items-baseline justify-between gap-2 border-b px-4 py-2.5"
        style={{ borderColor: "var(--line)" }}
      >
        <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
          Reconciliation run
        </h2>
        {run && (
          <span className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
            {run.id} · {run.rulesetVersion}
          </span>
        )}
      </header>

      <div className="flex flex-col gap-3 px-4 py-3">
        <button
          type="button"
          onClick={start}
          disabled={busy}
          className="flex items-center justify-center gap-2 whitespace-nowrap px-3 py-2 text-[12.5px] font-medium transition-colors duration-100 active:translate-y-px"
          style={{
            borderRadius: "var(--radius)",
            background: busy ? "var(--surface-2)" : "var(--flag)",
            color: busy ? "var(--ink-3)" : "#ffffff",
            cursor: busy ? "not-allowed" : "pointer",
          }}
        >
          {busy ? (
            <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />
          ) : (
            <PlayIcon size={13} weight="bold" />
          )}
          {busy ? `Running${run?.currentStage ? ` · ${run.currentStage}` : ""}` : "Start a run"}
        </button>

        {error && (
          <p
            className="border-l-2 py-1 pl-2.5 text-[12px]"
            style={{ borderColor: "var(--flag)", color: "var(--ink-2)" }}
          >
            {error}
          </p>
        )}

        {run && (
          <p className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            Status <span className="num">{run.status}</span>
            {run.error ? ` — ${run.error}` : null}
          </p>
        )}

        {metrics && (
          <>
            <dl className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
              <Metric label="Records" value={String(metrics.recordsProcessed)} />
              <Metric label="Auto-resolved" value={String(metrics.autoResolved)} tone="ok" />
              <Metric label="To review" value={String(metrics.pendingReview)} tone="warn" />
              <Metric label="Exceptions" value={String(metrics.exceptions)} tone="flag" />
              <Metric label="Groups" value={String(metrics.groups)} />
              <Metric
                label="Unresolved value"
                value={formatMinor(metrics.unresolvedValueMinor)}
                tone="flag"
              />
            </dl>
            <p className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
              {Object.entries(metrics.stageTimingsMs)
                .map(([stage, ms]) => `${stage} ${ms}ms`)
                .join(" · ")}
            </p>
          </>
        )}
      </div>
    </section>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "flag";
}) {
  const color =
    tone === "ok"
      ? "var(--ok)"
      : tone === "warn"
        ? "var(--warn)"
        : tone === "flag"
          ? "var(--flag)"
          : "var(--ink)";
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="num mt-0.5 text-[15px] font-semibold" style={{ color }}>
        {value}
      </dd>
    </div>
  );
}
