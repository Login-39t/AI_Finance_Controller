import Link from "next/link";

import { ApiError, latestRun, listRuns } from "@/lib/api";
import { EmptyState, Panel } from "@/components/primitives";
import { RunPanel } from "@/components/run-panel";

export default async function RunsPage() {
  let runs = null;
  let latest = null;
  let failure: string | null = null;

  try {
    [runs, latest] = await Promise.all([listRuns(), latestRun()]);
  } catch (error) {
    // Only ApiError is handled. `redirect()` signals by *throwing*, so
    // a bare catch swallows the bounce to sign-in and renders an
    // expired session as an unreachable API. Re-throwing anything
    // unrecognised also stops a real bug hiding behind this message.
    if (!(error instanceof ApiError)) throw error;
    failure = `${error.code}: ${error.message}`;
  }

  if (failure) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 py-5">
        <Panel title="Runs">
          <EmptyState
            title="The API is not reachable"
            body={`${failure}. Start it with "make api" and reload.`}
          />
        </Panel>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
        Runs
      </h1>
      <p className="mt-0.5 mb-5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        A run is a versioned, repeatable execution over everything imported. Re-running
        creates a new run; earlier results are never overwritten.
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <RunPanel initialRun={latest} />

        <Panel title="Run history" subtitle={`${(runs ?? []).length} run(s)`}>
          {(runs ?? []).length === 0 ? (
            <EmptyState
              title="No runs yet"
              body="Import the source files, then start a run to produce groups and exceptions."
            />
          ) : (
            <ul>
              {(runs ?? []).map((run, i) => (
                <li
                  key={run.id}
                  className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 px-4 py-2.5"
                  style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
                >
                  <div className="flex items-baseline gap-3">
                    <span className="num text-[12.5px]" style={{ color: "var(--ink)" }}>
                      {run.id}
                    </span>
                    <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                      {run.status}
                    </span>
                  </div>
                  {run.metrics && (
                    <span className="num text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                      {run.metrics.recordsProcessed} records · {run.metrics.autoResolved}{" "}
                      cleared · {run.metrics.exceptions} exceptions
                    </span>
                  )}
                  {run.status === "completed" && (
                    <Link
                      href="/exceptions"
                      className="text-[12px]"
                      style={{ color: "var(--flag)" }}
                    >
                      Review exceptions
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>
    </div>
  );
}
