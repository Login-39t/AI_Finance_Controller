import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/ssr";

import { findCase } from "@/fixtures/cases";
import { ageInDays } from "@/lib/money";
import { EXCEPTION_LABEL, SOURCE_LABEL } from "@/lib/types";
import {
  ConfidenceBadge,
  EmptyState,
  Money,
  Panel,
  SeverityMark,
  StatusPill,
} from "@/components/primitives";
import {
  AiPanel,
  AmountBridgeView,
  AuditList,
  CandidateList,
  EvidenceList,
  GatePanel,
  RecordList,
  Timeline,
} from "@/components/case-sections";
import { DecisionPanel } from "@/components/decision-panel";

/**
 * Case detail. The most important screen in the product.
 *
 * The whole packet arrives in one request, and the same assembled object
 * feeds the model prompt. One assembler means the analyst and the model
 * are looking at identical evidence, which is the claim that makes the
 * word "grounded" mean anything.
 */

const REVIEW_THRESHOLD_MINOR = "25000000"; // ₹2,50,000, from the active policy
const CANDIDATE_MARGIN = 0.05;
const VIEWER_ROLE = "analyst" as const;

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const packet = findCase(id);
  if (!packet) notFound();

  const subject = packet.transactions[0]?.transaction;

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      <Link
        href="/exceptions"
        className="mb-3 inline-flex items-center gap-1.5 text-[12.5px]"
        style={{ color: "var(--ink-3)" }}
      >
        <ArrowLeftIcon size={12} weight="bold" /> Exceptions
      </Link>

      {/* Header. Everything a reviewer needs to triage without scrolling. */}
      <header className="border-b pb-4" style={{ borderColor: "var(--line)" }}>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <SeverityMark severity={packet.severity} withLabel />
          <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            {EXCEPTION_LABEL[packet.caseType]}
          </h1>
          <StatusPill status={packet.status} />
          <span className="num text-[12px]" style={{ color: "var(--ink-3)" }}>
            {packet.id}
          </span>
        </div>

        <dl className="mt-3 flex flex-wrap items-end gap-x-9 gap-y-3">
          <div>
            <dt className="label">Amount at risk</dt>
            <dd className="mt-0.5">
              <Money
                minor={packet.amountAtRiskMinor}
                currency={packet.currency}
                className="text-[19px] font-semibold"
              />
            </dd>
          </div>
          <div>
            <dt className="label">Subject</dt>
            <dd className="num mt-0.5 text-[13px]" style={{ color: "var(--ink)" }}>
              {packet.primaryExternalId}
            </dd>
          </div>
          <div>
            <dt className="label">Source</dt>
            <dd className="mt-0.5 text-[13px]" style={{ color: "var(--ink)" }}>
              {SOURCE_LABEL[packet.primarySourceSystem]}
            </dd>
          </div>
          <div>
            <dt className="label">Confidence</dt>
            <dd className="mt-0.5 text-[13px]">
              <ConfidenceBadge value={packet.confidence} />
            </dd>
          </div>
          <div>
            <dt className="label">Age</dt>
            <dd className="num mt-0.5 text-[13px]" style={{ color: "var(--ink)" }}>
              {ageInDays(packet.openedAt)}d
            </dd>
          </div>
          <div>
            <dt className="label">Assignee</dt>
            <dd className="mt-0.5 text-[13px]" style={{ color: "var(--ink)" }}>
              {packet.assignedTo ?? "Unassigned"}
            </dd>
          </div>
        </dl>

        {packet.hypothesis && (
          <p className="mt-3 max-w-[80ch] text-[13px]" style={{ color: "var(--ink-2)" }}>
            {packet.hypothesis}
          </p>
        )}
      </header>

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        {/* Main column: the evidence, in the order a reviewer reads it. */}
        <div className="flex flex-col gap-4">
          {subject ? (
            <Timeline
              present={[
                {
                  entity: "settlement_batch",
                  label: subject.externalId,
                  at: subject.eventAt,
                },
              ]}
              note="The settlement is marked paid and its arithmetic is sound. No bank credit can be attributed to it, and no ledger posting follows, because the attribution is unresolved."
            />
          ) : (
            <Panel title="Timeline">
              <EmptyState
                title="No packet assembled yet"
                body="This case exists in the queue but its evidence packet has not been built. It arrives with the matching engine."
              />
            </Panel>
          )}

          {packet.bridge && <AmountBridgeView bridge={packet.bridge} />}

          {packet.evidence.length > 0 && <EvidenceList evidence={packet.evidence} />}

          {packet.candidates.length > 0 && (
            <CandidateList candidates={packet.candidates} margin={CANDIDATE_MARGIN} />
          )}

          {packet.transactions.length > 0 && <RecordList records={packet.transactions} />}

          <AiPanel
            investigation={packet.aiInvestigations[0] ?? null}
            evidence={packet.evidence}
          />
        </div>

        {/* Sidebar: what the reviewer does about it. */}
        <aside className="flex flex-col gap-4">
          <DecisionPanel
            amountAtRiskMinor={packet.amountAtRiskMinor}
            currency={packet.currency}
            requiresControllerApproval={packet.requiresControllerApproval}
            viewerRole={VIEWER_ROLE}
            reviewThresholdMinor={REVIEW_THRESHOLD_MINOR}
          />

          {packet.gate.length > 0 && <GatePanel conditions={packet.gate} />}

          <AuditList events={packet.audit} />
        </aside>
      </div>
    </div>
  );
}
