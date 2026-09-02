import type { Route } from "next";
import Link from "next/link";
import { ArrowRightIcon, RobotIcon } from "@phosphor-icons/react/dist/ssr";

import { ApiError, latestRun, listExceptions } from "@/lib/api";
import { ageInDays, formatMinor } from "@/lib/money";
import { EXCEPTION_LABEL, SOURCE_LABEL } from "@/lib/types";
import { ConfidenceBadge, Money, SeverityMark, StatusPill } from "@/components/primitives";

/**
 * The exceptions queue.
 *
 * Default sort is amount at risk, descending - applied by the engine and
 * preserved here. That is not a preference: an analyst has a finite
 * number of hours and the queue's whole job is to spend them on the
 * expensive problems first.
 *
 * Filters live in the URL so a view is shareable, survives a reload, and
 * behaves correctly with the back button.
 */

const FILTERS = [
  { key: "", label: "All" },
  { key: "missing_bank_credit", label: "Missing credit" },
  { key: "amount_mismatch", label: "Amount" },
  { key: "duplicate", label: "Duplicate" },
  { key: "unmatched_payment", label: "Unmatched" },
] as const;

const PAGE_SIZE = 60;

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<{ caseType?: string; severity?: string }>;
}) {
  const { caseType = "", severity = "" } = await searchParams;

  let page = null;
  let run = null;
  let failure: string | null = null;

  try {
    [page, run] = await Promise.all([
      listExceptions({ caseType, severity, limit: PAGE_SIZE }),
      latestRun(),
    ]);
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
      <Shell>
        <Notice
          title="The API is not reachable"
          body={`${failure}. Start it with \`make api\` and reload.`}
        />
      </Shell>
    );
  }

  // A 404 here means no run has happened. That is a different claim from
  // "nothing needs reconciling", and rendering an empty table would make
  // the more comfortable one.
  if (page === null) {
    return (
      <Shell>
        <Notice
          title="No reconciliation run yet"
          body="Import the source files, then start a run. The queue fills from the run's findings."
          action={{ href: "/imports" as Route, label: "Go to imports" }}
        />
      </Shell>
    );
  }

  const exposure = page.items.reduce(
    (total, c) => total + BigInt(c.amountAtRiskMinor),
    0n,
  );
  const criticalCount = page.items.filter((c) => c.severity === "critical").length;

  return (
    <Shell>
      <div
        className="mb-5 flex flex-wrap items-end gap-x-10 gap-y-4 border-b pb-4"
        style={{ borderColor: "var(--line)" }}
      >
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Exceptions
          </h1>
          <p className="mt-0.5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Highest financial risk first. {page.total} in this run.
          </p>
        </div>

        <dl className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <Stat label="Exposure shown" value={formatMinor(exposure.toString())} tone="flag" />
          <Stat label="Critical" value={String(criticalCount)} />
          <Stat
            label="Auto-resolved"
            value={run?.metrics ? String(run.metrics.autoResolved) : "——"}
            tone="ok"
          />
          <Stat
            label="Records"
            value={run?.metrics ? String(run.metrics.recordsProcessed) : "——"}
          />
        </dl>

        <nav className="ml-auto flex flex-wrap items-center gap-1" aria-label="Filter by type">
          {FILTERS.map((f) => {
            const active = f.key === caseType;
            return (
              <Link
                key={f.key || "all"}
                href={f.key ? `/exceptions?caseType=${f.key}` : "/exceptions"}
                aria-current={active ? "page" : undefined}
                className="border px-2.5 py-1 text-[12.5px] transition-colors duration-100"
                style={{
                  borderRadius: "var(--radius)",
                  borderColor: active ? "var(--ink)" : "var(--line)",
                  background: active ? "var(--ink)" : "transparent",
                  color: active ? "var(--surface)" : "var(--ink-2)",
                }}
              >
                {f.label}
              </Link>
            );
          })}
        </nav>
      </div>

      {page.items.length === 0 ? (
        <Notice
          title="Nothing matches this filter"
          body="Every case of this type has been decided, or none was raised in this run."
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[980px] border-collapse">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--line)" }}>
                <th className="label w-6 py-2 pr-2 text-left" scope="col">
                  <span className="sr-only">Severity</span>
                </th>
                <th className="label py-2 pr-4 text-left" scope="col">Type</th>
                <th className="label py-2 pr-4 text-right" scope="col">Amount at risk</th>
                <th className="label py-2 pr-4 text-left" scope="col">Subject</th>
                <th className="label py-2 pr-4 text-left" scope="col">Source</th>
                <th className="label py-2 pr-4 text-right" scope="col">Conf.</th>
                <th className="label py-2 pr-4 text-right" scope="col">Age</th>
                <th className="label py-2 pr-4 text-left" scope="col">Status</th>
                <th className="label py-2 text-right" scope="col">
                  <span className="sr-only">Open</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {page.items.map((c) => (
                <tr
                  key={c.id}
                  className="group border-b transition-colors duration-100"
                  style={{ borderColor: "var(--line-soft)" }}
                >
                  <td className="py-[7px] pr-2 align-middle">
                    <SeverityMark severity={c.severity} />
                  </td>
                  <td className="py-[7px] pr-4 align-middle" style={{ color: "var(--ink)" }}>
                    <Link
                      href={`/exceptions/${c.id}`}
                      className="font-medium hover:underline"
                      style={{ textUnderlineOffset: "2px" }}
                    >
                      {EXCEPTION_LABEL[c.caseType] ?? c.caseType}
                    </Link>
                  </td>
                  <td className="py-[7px] pr-4 text-right align-middle">
                    <Money
                      minor={c.amountAtRiskMinor}
                      currency={c.currency}
                      className="font-medium"
                    />
                  </td>
                  <td
                    className="num py-[7px] pr-4 align-middle text-[12px]"
                    style={{ color: "var(--ink-2)" }}
                  >
                    {c.primaryExternalId}
                  </td>
                  <td
                    className="py-[7px] pr-4 align-middle text-[12.5px]"
                    style={{ color: "var(--ink-2)" }}
                  >
                    {SOURCE_LABEL[c.primarySourceSystem] ?? c.primarySourceSystem}
                  </td>
                  <td className="py-[7px] pr-4 text-right align-middle">
                    <ConfidenceBadge value={c.confidence} />
                  </td>
                  <td
                    className="num py-[7px] pr-4 text-right align-middle text-[12px]"
                    style={{ color: "var(--ink-3)" }}
                  >
                    {ageInDays(c.openedAt)}d
                  </td>
                  <td className="py-[7px] pr-4 align-middle">
                    <StatusPill status={c.status} />
                  </td>
                  <td className="py-[7px] text-right align-middle">
                    <Link
                      href={`/exceptions/${c.id}`}
                      className="inline-flex items-center gap-1 text-[12.5px] opacity-0 transition-opacity duration-100 group-hover:opacity-100 focus-visible:opacity-100"
                      style={{ color: "var(--flag)" }}
                    >
                      Open <ArrowRightIcon size={12} weight="bold" />
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="mt-4 text-[12px]" style={{ color: "var(--ink-3)" }}>
        Sorted by amount at risk.{" "}
        {run ? `Ruleset ${run.rulesetVersion}, run ${run.id}.` : null}
        {page.nextCursor ? ` Showing the first ${PAGE_SIZE} of ${page.total}.` : null}
      </p>
    </Shell>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-[1400px] px-4 py-5">{children}</div>;
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "flag" | "ok";
}) {
  const color =
    tone === "flag" ? "var(--flag)" : tone === "ok" ? "var(--ok)" : "var(--ink)";
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="num mt-0.5 text-[17px] font-semibold" style={{ color }}>
        {value}
      </dd>
    </div>
  );
}

function Notice({
  title,
  body,
  action,
}: {
  title: string;
  body: string;
  // Typed as `Route` rather than `string` so Next's typedRoutes still
  // checks the destination; a plain string would silently opt out.
  action?: { href: Route; label: string };
}) {
  return (
    <div
      className="border px-4 py-8 text-center"
      style={{ borderColor: "var(--line)", borderRadius: "var(--radius)" }}
    >
      <p className="text-[13px] font-medium" style={{ color: "var(--ink)" }}>
        {title}
      </p>
      <p className="mx-auto mt-1 max-w-[52ch] text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        {body}
      </p>
      {action && (
        <Link
          href={action.href}
          className="mt-3 inline-block border px-3 py-1.5 text-[12.5px]"
          style={{
            borderRadius: "var(--radius)",
            borderColor: "var(--ink)",
            background: "var(--ink)",
            color: "var(--surface)",
          }}
        >
          {action.label}
        </Link>
      )}
    </div>
  );
}
