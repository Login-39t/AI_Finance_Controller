import Link from "next/link";
import {
  ArrowRightIcon,
  DownloadSimpleIcon,
  WarningCircleIcon,
} from "@phosphor-icons/react/dist/ssr";

import { ApiError, getOverview } from "@/lib/api";
import { formatInstant, formatMinor } from "@/lib/money";
import { EXCEPTION_LABEL, type ExceptionType, type Severity } from "@/lib/types";
import { EmptyState, Panel, SeverityMark } from "@/components/primitives";

/**
 * The overview.
 *
 * Written for one reader — the controller deciding whether the close can
 * be signed — and it answers their question in the first line rather
 * than at the bottom of a scroll: **how much money is unexplained, and
 * who has to look at it.**
 *
 * What is deliberately *not* here: a match-rate percentage in the hero.
 * Match rate is the number reconciliation tools lead with and it is the
 * wrong headline, because it goes up when the system guesses. The figure
 * that governs is exposure still open.
 */

export const dynamic = "force-dynamic";

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
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
    <div className="min-w-0">
      <dt className="label">{label}</dt>
      <dd className="num mt-1 truncate text-[22px] font-semibold leading-none" style={{ color }}>
        {value}
      </dd>
      {sub && (
        <p className="mt-1 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
          {sub}
        </p>
      )}
    </div>
  );
}

/**
 * A proportion bar. No chart library: one flex row of divs conveys a
 * share exactly, and a 40kB dependency to draw six rectangles is a
 * dependency to keep patched forever.
 */
function ShareBar({
  segments,
}: {
  segments: { key: string; value: number; color: string; title: string }[];
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0);
  if (total === 0) return null;

  return (
    <div
      className="flex h-2 w-full overflow-hidden"
      style={{ borderRadius: "var(--radius)", background: "var(--surface-2)" }}
      role="img"
      aria-label={segments.map((s) => s.title).join("; ")}
    >
      {segments
        .filter((s) => s.value > 0)
        .map((s) => (
          <div
            key={s.key}
            title={s.title}
            style={{ width: `${(s.value / total) * 100}%`, background: s.color }}
          />
        ))}
    </div>
  );
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: "var(--flag)",
  high: "var(--warn)",
  medium: "var(--ink-2)",
  low: "var(--ink-3)",
};

export default async function OverviewPage() {
  let overview = null;
  let failure: string | null = null;
  try {
    overview = await getOverview();
  } catch (error) {
    // Only ApiError is handled here. `redirect()` signals by *throwing*,
    // so a bare catch swallows the bounce to /login and renders an
    // expired session as "the API is unavailable" - which is both wrong
    // and unrecoverable, because the user never gets to sign in again.
    // Re-throwing anything unrecognised also stops a real bug hiding
    // behind a friendly message.
    if (!(error instanceof ApiError)) throw error;
    failure = error.message;
  }

  if (failure) {
    return (
      <div className="mx-auto max-w-[1200px] px-4 py-8">
        <EmptyState title="Cannot reach the API" body={failure} />
      </div>
    );
  }

  // 404 becomes null: no run has happened, which is a different claim
  // from "nothing needs reconciling" and must not render as zeroes.
  if (overview === null) {
    return (
      <div className="mx-auto max-w-[1200px] px-4 py-8">
        <EmptyState
          title="No reconciliation has run yet"
          body="Upload the source files, then start a run. Until then this page would only be able to show zeroes, which would read as a clean close."
        />
        <div className="mt-4 flex gap-3">
          <Link href="/imports" className="text-[13px] underline" style={{ color: "var(--flag)" }}>
            Upload source files
          </Link>
          <Link href="/runs" className="text-[13px] underline" style={{ color: "var(--flag)" }}>
            Start a run
          </Link>
        </div>
      </div>
    );
  }

  const { decisions } = overview;
  const openShare =
    overview.exceptions > 0 ? decisions.open / overview.exceptions : 0;

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-5 px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Close overview
          </h1>
          <p className="mt-0.5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            Run <span className="num">{overview.runId}</span> ·{" "}
            <span className="num">{overview.rulesetVersion}</span>
            {overview.completedAt ? ` · ${formatInstant(overview.completedAt)}` : null}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          {[
            { kind: "exceptions", label: "Exceptions" },
            { kind: "matches", label: "Matches" },
            { kind: "audit", label: "Audit trail" },
          ].map((e) => (
            <a
              key={e.kind}
              href={`/api/export/${e.kind}`}
              className="flex items-center gap-1.5 border px-2.5 py-1.5 text-[12px] transition-colors duration-100"
              style={{
                borderRadius: "var(--radius)",
                borderColor: "var(--line)",
                color: "var(--ink-2)",
              }}
            >
              <DownloadSimpleIcon size={12} weight="bold" />
              {e.label}
            </a>
          ))}
        </div>
      </header>

      {/* The headline. Exposure first, because it is the number that
          decides whether the close can be signed. */}
      <section
        className="border px-5 py-4"
        style={{
          background: "var(--surface)",
          borderColor: "var(--line)",
          borderRadius: "var(--radius)",
        }}
      >
        <dl className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-3 lg:grid-cols-5">
          <Stat
            label="Exposure still open"
            value={formatMinor(decisions.openValueMinor)}
            sub={`${decisions.open} of ${overview.exceptions} cases undecided`}
            tone="flag"
          />
          <Stat
            label="Needs a controller"
            value={String(decisions.awaitingController)}
            sub="above the material threshold"
            tone={decisions.awaitingController > 0 ? "warn" : "ok"}
          />
          <Stat
            label="Decided"
            value={formatMinor(decisions.decidedValueMinor)}
            sub={`${decisions.decided} case${decisions.decided === 1 ? "" : "s"}`}
            tone="ok"
          />
          <Stat
            label="Cleared without a human"
            value={`${(overview.autoResolutionRate * 100).toFixed(1)}%`}
            sub={`${overview.autoResolved} of ${overview.groups} groups, by value`}
          />
          <Stat
            label="Records"
            value={overview.recordsProcessed.toLocaleString("en-IN")}
            sub={`${overview.pendingReview} groups to review`}
          />
        </dl>

        <div className="mt-4">
          <ShareBar
            segments={[
              {
                key: "open",
                value: decisions.open,
                color: "var(--flag)",
                title: `${decisions.open} undecided`,
              },
              {
                key: "decided",
                value: decisions.decided,
                color: "var(--ok)",
                title: `${decisions.decided} decided`,
              },
            ]}
          />
          <p className="mt-1.5 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
            {(openShare * 100).toFixed(0)}% of exceptions are still open.
            {decisions.awaitingController > 0
              ? " Some of them cannot be closed by a reviewer."
              : null}
          </p>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        <Panel title="Where the money is" subtitle="By exception type, largest first">
          {overview.byType.length === 0 ? (
            <EmptyState
              title="Nothing outstanding"
              body="Every group in this run cleared the gate."
            />
          ) : (
            <ul>
              {overview.byType.map((bucket) => (
                <li
                  key={bucket.caseType}
                  className="flex items-center gap-3 border-b px-4 py-2 last:border-b-0"
                  style={{ borderColor: "var(--line)" }}
                >
                  <Link
                    href={`/exceptions?caseType=${bucket.caseType}`}
                    className="min-w-0 flex-1 truncate text-[12.5px]"
                    style={{ color: "var(--ink)" }}
                  >
                    {EXCEPTION_LABEL[bucket.caseType as ExceptionType] ?? bucket.caseType}
                  </Link>
                  <span className="num shrink-0 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                    {bucket.count}
                  </span>
                  <span
                    className="num w-[110px] shrink-0 text-right text-[12.5px]"
                    style={{ color: "var(--ink)" }}
                  >
                    {formatMinor(bucket.amountAtRiskMinor)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <div className="flex flex-col gap-5">
          <Panel title="By severity" subtitle="Count and exposure">
            <ul>
              {overview.bySeverity.map((bucket) => (
                <li
                  key={bucket.severity}
                  className="flex items-center gap-3 border-b px-4 py-2 last:border-b-0"
                  style={{ borderColor: "var(--line)" }}
                >
                  <SeverityMark severity={bucket.severity as Severity} withLabel />
                  <span className="flex-1" />
                  <span className="num shrink-0 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                    {bucket.count}
                  </span>
                  <span
                    className="num w-[110px] shrink-0 text-right text-[12.5px]"
                    style={{ color: SEVERITY_COLOR[bucket.severity] ?? "var(--ink)" }}
                  >
                    {formatMinor(bucket.amountAtRiskMinor)}
                  </span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Engine" subtitle="Stage timings for this run">
            <div className="flex flex-wrap gap-x-5 gap-y-2 px-4 py-3">
              {Object.entries(overview.stageTimingsMs).map(([stage, ms]) => (
                <div key={stage}>
                  <span className="label">{stage.replace(/_/g, " ")}</span>
                  <p className="num text-[13px]" style={{ color: "var(--ink)" }}>
                    {ms}ms
                  </p>
                </div>
              ))}
            </div>
          </Panel>
        </div>
      </div>

      {decisions.awaitingController > 0 && (
        <p
          className="flex items-center gap-2 border-l-2 py-1.5 pl-3 text-[12.5px]"
          style={{ borderColor: "var(--warn)", color: "var(--ink-2)" }}
        >
          <WarningCircleIcon size={14} weight="bold" style={{ color: "var(--warn)" }} />
          {decisions.awaitingController} case
          {decisions.awaitingController === 1 ? " is" : "s are"} above the material
          threshold and can only be closed by a controller.
          <Link
            href="/exceptions"
            className="ml-1 inline-flex items-center gap-1 underline"
            style={{ color: "var(--flag)" }}
          >
            Open the queue <ArrowRightIcon size={11} weight="bold" />
          </Link>
        </p>
      )}
    </div>
  );
}
