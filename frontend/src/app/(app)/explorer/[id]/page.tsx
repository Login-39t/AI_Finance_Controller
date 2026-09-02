import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/ssr";

import { getMatchGroup } from "@/lib/api";
import { formatMinor } from "@/lib/money";
import { EmptyState, Panel } from "@/components/primitives";
import {
  AmountBridgeView,
  EvidenceList,
  GatePanel,
  RecordList,
} from "@/components/case-sections";

/**
 * One match group, in full.
 *
 * The same four sections as a case packet — records, bridge, evidence,
 * gate — reusing the same components rather than a second set that
 * renders the same data slightly differently. A cleared group and a
 * failed one must be legible side by side, and two renderers would
 * eventually disagree about what "balances" means.
 */

export const dynamic = "force-dynamic";

export default async function GroupDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const group = await getMatchGroup(id);
  if (group === null) notFound();

  const cleared = group.status === "auto_resolved";

  return (
    <div className="mx-auto flex max-w-[1200px] flex-col gap-4 px-4 py-6">
      <Link
        href="/explorer"
        className="flex w-fit items-center gap-1.5 text-[12.5px]"
        style={{ color: "var(--ink-2)" }}
      >
        <ArrowLeftIcon size={12} weight="bold" />
        Explorer
      </Link>

      <header className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
        <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
          {group.matchedByRule}
        </h1>
        <span
          className="px-1.5 py-0.5 text-[11px]"
          style={{
            borderRadius: "var(--radius)",
            background: cleared ? "var(--ok-bg, transparent)" : "transparent",
            color: cleared ? "var(--ok)" : "var(--warn)",
            border: `1px solid ${cleared ? "var(--ok)" : "var(--warn)"}`,
          }}
        >
          {group.status.replace(/_/g, " ")}
        </span>
        <span className="num text-[12px]" style={{ color: "var(--ink-3)" }}>
          {group.id}
        </span>
      </header>

      <dl
        className="grid grid-cols-2 gap-x-6 gap-y-3 border px-4 py-3 sm:grid-cols-4"
        style={{
          background: "var(--surface)",
          borderColor: "var(--line)",
          borderRadius: "var(--radius)",
        }}
      >
        <div>
          <dt className="label">Matched amount</dt>
          <dd className="num mt-0.5 text-[15px] font-semibold" style={{ color: "var(--ink)" }}>
            {formatMinor(group.matchedAmountMinor, group.currency)}
          </dd>
        </div>
        <div>
          <dt className="label">Shape</dt>
          <dd className="mt-0.5 text-[13px]" style={{ color: "var(--ink)" }}>
            {group.groupType.replace(/_/g, "-")}, {group.memberCount} records
          </dd>
        </div>
        <div>
          <dt className="label">Tier</dt>
          <dd
            className="mt-0.5 text-[13px]"
            style={{ color: group.tier === "deterministic" ? "var(--ok)" : "var(--warn)" }}
          >
            {group.tier}
          </dd>
        </div>
        <div>
          <dt className="label">Confidence</dt>
          <dd className="num mt-0.5 text-[13px]" style={{ color: "var(--ink)" }}>
            {group.confidence.toFixed(4)}
          </dd>
        </div>
      </dl>

      {group.explanation && (
        <p className="max-w-[70ch] text-[13px] leading-relaxed" style={{ color: "var(--ink)" }}>
          {group.explanation}
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.7fr)_minmax(0,1fr)]">
        <div className="flex flex-col gap-4">
          {group.bridge ? (
            <AmountBridgeView bridge={group.bridge} />
          ) : (
            <Panel title="Amount bridge" subtitle="Not applicable">
              <EmptyState
                title="No bridge for this group"
                body="A bridge is computed where a gross-to-net identity exists. This rule matches on identifiers, so there is nothing to bridge."
              />
            </Panel>
          )}

          {group.evidence.length > 0 && <EvidenceList evidence={group.evidence} />}

          <RecordList records={group.transactions} />
        </div>

        <aside className="flex flex-col gap-4">
          {group.gate.length > 0 ? (
            <GatePanel conditions={group.gate} />
          ) : (
            <Panel title="Auto-resolution gate" subtitle="Not evaluated">
              <EmptyState
                title="The gate did not run on this group"
                body="Only proposed matches are put to the gate."
              />
            </Panel>
          )}

          {Object.keys(group.confidenceComponents).length > 0 && (
            <Panel title="Confidence" subtitle="What the score is made of">
              <ul>
                {Object.entries(group.confidenceComponents).map(([key, value]) => (
                  <li
                    key={key}
                    className="flex items-baseline justify-between gap-3 border-b px-4 py-1.5 last:border-b-0"
                    style={{ borderColor: "var(--line)" }}
                  >
                    <span className="text-[12px]" style={{ color: "var(--ink-2)" }}>
                      {key.replace(/^score_/, "").replace(/_/g, " ")}
                    </span>
                    <span className="num text-[12px]" style={{ color: "var(--ink)" }}>
                      {typeof value === "number" ? value.toFixed(3) : String(value)}
                    </span>
                  </li>
                ))}
              </ul>
              <p className="px-4 py-2 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                Confidence is an input to the gate, never an override. A group with a
                high score and a failed condition is still routed to a human.
              </p>
            </Panel>
          )}
        </aside>
      </div>
    </div>
  );
}
