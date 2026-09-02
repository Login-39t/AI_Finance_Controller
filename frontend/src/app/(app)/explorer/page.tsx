import Link from "next/link";
import { CheckCircleIcon, CircleDashedIcon, XCircleIcon } from "@phosphor-icons/react/dist/ssr";

import { ApiError, listMatchGroups } from "@/lib/api";
import { formatMinor } from "@/lib/money";
import { EmptyState } from "@/components/primitives";

/**
 * The reconciliation explorer.
 *
 * The exceptions queue shows what went wrong. This shows what the engine
 * *decided* — including the groups it cleared on its own, which is the
 * half a reconciliation tool usually hides.
 *
 * That asymmetry matters. Auto-resolution precision is the number this
 * whole system rests on, and a number nobody can spot-check is a number
 * taken on trust. Here a controller can open any cleared group and see
 * the six gate conditions that let it through.
 */

export const dynamic = "force-dynamic";

const STATUS_TABS = [
  { key: "", label: "All" },
  { key: "auto_resolved", label: "Auto-resolved" },
  { key: "pending_review", label: "To review" },
  { key: "proposed", label: "Proposed" },
] as const;

function GateMark({ passed, total }: { passed: number; total: number }) {
  if (total === 0) {
    return (
      <span className="inline-flex items-center gap-1" title="the gate was not evaluated">
        <CircleDashedIcon size={12} weight="bold" style={{ color: "var(--ink-3)" }} />
        <span className="num text-[11.5px]" style={{ color: "var(--ink-3)" }}>
          —
        </span>
      </span>
    );
  }
  const all = passed === total;
  return (
    <span
      className="inline-flex items-center gap-1"
      title={`${passed} of ${total} gate conditions held`}
    >
      {all ? (
        <CheckCircleIcon size={12} weight="fill" style={{ color: "var(--ok)" }} />
      ) : (
        <XCircleIcon size={12} weight="fill" style={{ color: "var(--warn)" }} />
      )}
      <span
        className="num text-[11.5px]"
        style={{ color: all ? "var(--ok)" : "var(--ink-2)" }}
      >
        {passed}/{total}
      </span>
    </span>
  );
}

export default async function ExplorerPage({
  searchParams,
}: {
  searchParams: Promise<{ status?: string; rule?: string }>;
}) {
  const { status = "", rule } = await searchParams;

  let page = null;
  let failure: string | null = null;
  try {
    page = await listMatchGroups({ status, rule, limit: 200 });
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

  if (page === null) {
    return (
      <div className="mx-auto max-w-[1200px] px-4 py-8">
        <EmptyState
          title="No reconciliation has run yet"
          body="There are no match groups to explore until a run completes."
        />
      </div>
    );
  }

  const total = Object.values(page.statusCounts).reduce((a, b) => a + b, 0);

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Reconciliation explorer
          </h1>
          <p className="mt-0.5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            Every group the engine formed, cleared and uncleared. {total} in this run.
          </p>
        </div>

        <nav className="flex flex-wrap gap-1">
          {STATUS_TABS.map((tab) => {
            const isActive = status === tab.key;
            const count =
              tab.key === "" ? total : (page.statusCounts[tab.key] ?? 0);
            return (
              <Link
                key={tab.key || "all"}
                href={tab.key ? `/explorer?status=${tab.key}` : "/explorer"}
                className="flex items-center gap-1.5 border px-2.5 py-1 text-[12px] transition-colors duration-100"
                style={{
                  borderRadius: "var(--radius)",
                  borderColor: isActive ? "var(--ink)" : "var(--line)",
                  background: isActive ? "var(--ink)" : "transparent",
                  color: isActive ? "var(--surface)" : "var(--ink-2)",
                }}
              >
                {tab.label}
                <span className="num opacity-70">{count}</span>
              </Link>
            );
          })}
        </nav>
      </header>

      {page.items.length === 0 ? (
        <EmptyState
          title="Nothing in this view"
          body="No group in this run has that status."
        />
      ) : (
        // The table is wider than a narrow viewport, so it scrolls inside
        // its own container. The document itself must never scroll
        // sideways.
        <div
          className="overflow-x-auto border"
          style={{
            background: "var(--surface)",
            borderColor: "var(--line)",
            borderRadius: "var(--radius)",
          }}
        >
          <table className="w-full min-w-[900px] border-collapse">
            <thead>
              <tr className="border-b" style={{ borderColor: "var(--line)" }}>
                {[
                  "Rule",
                  "Shape",
                  "Members",
                  "Matched amount",
                  "Bridge",
                  "Gate",
                  "Conf.",
                  "Status",
                ].map((h, i) => (
                  <th
                    key={h}
                    className={`label px-3 py-2 ${i === 3 ? "text-right" : "text-left"}`}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {page.items.map((group) => (
                <tr
                  key={group.id}
                  className="border-b last:border-b-0"
                  style={{ borderColor: "var(--line)" }}
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`/explorer/${group.id}`}
                      className="num text-[12.5px]"
                      style={{ color: "var(--ink)" }}
                    >
                      {group.matchedByRule}
                    </Link>
                    <span
                      className="ml-2 text-[11px]"
                      style={{
                        color:
                          group.tier === "deterministic" ? "var(--ok)" : "var(--warn)",
                      }}
                    >
                      {group.tier}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-[12px]" style={{ color: "var(--ink-2)" }}>
                    {group.groupType.replace(/_/g, "-")}
                  </td>
                  <td className="num px-3 py-2 text-[12px]" style={{ color: "var(--ink-2)" }}>
                    {group.memberCount}
                  </td>
                  <td className="num px-3 py-2 text-right text-[12.5px]" style={{ color: "var(--ink)" }}>
                    {formatMinor(group.matchedAmountMinor, group.currency)}
                  </td>
                  <td className="px-3 py-2 text-[11.5px]">
                    {group.bridgeBalances === null ? (
                      <span style={{ color: "var(--ink-3)" }}>n/a</span>
                    ) : group.bridgeBalances ? (
                      <span style={{ color: "var(--ok)" }}>balances</span>
                    ) : (
                      <span style={{ color: "var(--flag)" }}>off</span>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <GateMark passed={group.gatePassed} total={group.gateTotal} />
                  </td>
                  <td className="num px-3 py-2 text-[12px]" style={{ color: "var(--ink-2)" }}>
                    {group.confidence.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-[11.5px]">
                    <span
                      style={{
                        color:
                          group.status === "auto_resolved"
                            ? "var(--ok)"
                            : group.status === "pending_review"
                              ? "var(--warn)"
                              : "var(--ink-2)",
                      }}
                    >
                      {group.status.replace(/_/g, " ")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
        Auto-resolved groups are shown on purpose. A precision figure nobody can
        spot-check is a figure taken on trust.
      </p>
    </div>
  );
}
