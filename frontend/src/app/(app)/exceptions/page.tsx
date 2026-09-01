import Link from "next/link";
import { ArrowRightIcon, RobotIcon } from "@phosphor-icons/react/dist/ssr";

import { QUEUE, PACKET } from "@/fixtures/cases";
import { ageInDays, compareMinor, formatMinor } from "@/lib/money";
import { EXCEPTION_LABEL, SOURCE_LABEL, type CaseStatus } from "@/lib/types";
import { ConfidenceBadge, Money, SeverityMark, StatusPill } from "@/components/primitives";

/**
 * The exceptions queue.
 *
 * Default sort is amount at risk, descending. That is not a preference:
 * an analyst has a finite number of hours and the queue's whole job is to
 * spend them on the expensive problems first.
 *
 * Filters live in the URL so a view is shareable, survives a reload, and
 * behaves correctly with the back button.
 */

const OPEN_STATUSES: CaseStatus[] = ["open", "investigating", "pending_approval", "unresolved"];

const FILTERS = [
  { key: "open", label: "Open" },
  { key: "all", label: "All" },
  { key: "unresolved", label: "Unresolved" },
  { key: "mine", label: "Assigned to me" },
] as const;

type FilterKey = (typeof FILTERS)[number]["key"];

const CURRENT_USER = "Meera Balakrishnan";

function sumMinor(values: string[]): string {
  return values.reduce((acc, v) => (BigInt(acc) + BigInt(v)).toString(), "0");
}

export default async function ExceptionsPage({
  searchParams,
}: {
  searchParams: Promise<{ view?: string }>;
}) {
  const { view } = await searchParams;
  const active = (FILTERS.find((f) => f.key === view)?.key ?? "open") as FilterKey;

  const rows = QUEUE.filter((c) => {
    if (active === "all") return true;
    if (active === "unresolved") return c.status === "unresolved";
    if (active === "mine") return c.assignedTo === CURRENT_USER;
    return OPEN_STATUSES.includes(c.status);
  }).sort((a, b) => compareMinor(b.amountAtRiskMinor, a.amountAtRiskMinor));

  const openCases = QUEUE.filter((c) => OPEN_STATUSES.includes(c.status));
  const exposure = sumMinor(openCases.map((c) => c.amountAtRiskMinor));
  const criticalCount = openCases.filter((c) => c.severity === "critical").length;

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      {/* Summary before detail. Three numbers that decide whether the
          analyst should be worried before they read a single row. */}
      <div
        className="mb-5 flex flex-wrap items-end gap-x-10 gap-y-4 border-b pb-4"
        style={{ borderColor: "var(--line)" }}
      >
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Exceptions
          </h1>
          <p className="mt-0.5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Highest financial risk first. {openCases.length} open of {QUEUE.length} in this run.
          </p>
        </div>

        <dl className="flex flex-wrap items-end gap-x-8 gap-y-3">
          <div>
            <dt className="label">Unresolved exposure</dt>
            <dd className="num mt-0.5 text-[17px] font-semibold" style={{ color: "var(--flag)" }}>
              {formatMinor(exposure)}
            </dd>
          </div>
          <div>
            <dt className="label">Critical</dt>
            <dd className="num mt-0.5 text-[17px] font-semibold" style={{ color: "var(--ink)" }}>
              {criticalCount}
            </dd>
          </div>
          <div>
            <dt className="label">Awaiting approval</dt>
            <dd className="num mt-0.5 text-[17px] font-semibold" style={{ color: "var(--ink)" }}>
              {QUEUE.filter((c) => c.status === "pending_approval").length}
            </dd>
          </div>
        </dl>

        <nav className="ml-auto flex items-center gap-1" aria-label="Queue filter">
          {FILTERS.map((f) => {
            const isActive = f.key === active;
            return (
              <Link
                key={f.key}
                href={`/exceptions?view=${f.key}`}
                aria-current={isActive ? "page" : undefined}
                className="border px-2.5 py-1 text-[12.5px] transition-colors duration-100"
                style={{
                  borderRadius: "var(--radius)",
                  borderColor: isActive ? "var(--ink)" : "var(--line)",
                  background: isActive ? "var(--ink)" : "transparent",
                  color: isActive ? "var(--surface)" : "var(--ink-2)",
                }}
              >
                {f.label}
              </Link>
            );
          })}
        </nav>
      </div>

      {/* Hairlines, not cards. A card per row would triple the vertical
          cost of a queue an analyst reads for hours. */}
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
              <th className="label py-2 pr-4 text-left" scope="col">Assignee</th>
              <th className="label py-2 text-right" scope="col">
                <span className="sr-only">Open</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => {
              const hasAi = c.id === PACKET.id;
              return (
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
                      {EXCEPTION_LABEL[c.caseType]}
                    </Link>
                  </td>
                  <td className="py-[7px] pr-4 text-right align-middle">
                    <Money
                      minor={c.amountAtRiskMinor}
                      currency={c.currency}
                      className="font-medium"
                    />
                  </td>
                  <td className="num py-[7px] pr-4 align-middle text-[12px]" style={{ color: "var(--ink-2)" }}>
                    {c.primaryExternalId}
                  </td>
                  <td className="py-[7px] pr-4 align-middle text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                    {SOURCE_LABEL[c.primarySourceSystem]}
                  </td>
                  <td className="py-[7px] pr-4 text-right align-middle">
                    <ConfidenceBadge value={c.confidence} />
                  </td>
                  <td className="num py-[7px] pr-4 text-right align-middle text-[12px]" style={{ color: "var(--ink-3)" }}>
                    {ageInDays(c.openedAt)}d
                  </td>
                  <td className="py-[7px] pr-4 align-middle">
                    <StatusPill status={c.status} />
                  </td>
                  <td className="py-[7px] pr-4 align-middle text-[12.5px]" style={{ color: c.assignedTo ? "var(--ink-2)" : "var(--ink-3)" }}>
                    <span className="inline-flex items-center gap-1.5">
                      {c.assignedTo ?? "Unassigned"}
                      {hasAi && (
                        <RobotIcon
                          size={13}
                          weight="regular"
                          style={{ color: "var(--warn)" }}
                          aria-label="Has an AI investigation"
                        />
                      )}
                    </span>
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
              );
            })}
          </tbody>
        </table>
      </div>

      {rows.length === 0 && (
        <div className="border-b py-10 text-center" style={{ borderColor: "var(--line-soft)" }}>
          <p className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
            Nothing in this view
          </p>
          <p className="mt-1 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
            Every case matching this filter has been decided. Switch to All to see the run history.
          </p>
        </div>
      )}

      <p className="mt-4 text-[12px]" style={{ color: "var(--ink-3)" }}>
        Sorted by amount at risk. Ruleset {QUEUE[0].rulesetVersion}.
      </p>
    </div>
  );
}
