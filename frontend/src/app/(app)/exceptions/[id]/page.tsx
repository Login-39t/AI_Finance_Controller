import Link from "next/link";
import { notFound } from "next/navigation";
import { ArrowLeftIcon } from "@phosphor-icons/react/dist/ssr";

import { getCase, latestRun } from "@/lib/api";
import { currentUser } from "@/lib/session";
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
 * see identical evidence, which is the claim that makes the word
 * "grounded" mean anything.
 */

const REVIEW_THRESHOLD_MINOR = "25000000"; // ₹2,50,000, from the active policy
const CANDIDATE_MARGIN = 0.05;

const TIMELINE_STAGES = [
  "payment",
  "settlement_batch",
  "bank_transaction",
  "ledger_entry",
] as const;

export default async function CaseDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const [packet, run, viewer] = await Promise.all([
    getCase(id),
    latestRun(),
    currentUser(),
  ]);
  if (packet === null) notFound();

  // The timeline is built from whichever stages this case actually
  // touches; a stage with no record renders as a dashed gap rather than
  // being omitted, because the gap in the chain is the finding.
  const present = TIMELINE_STAGES.flatMap((entity) => {
    const member = packet.transactions.find(
      (m) => m.transaction.entityType === entity,
    );
    return member
      ? [{
          entity,
          label: member.transaction.externalId,
          at: member.transaction.eventAt,
        }]
      : [];
  });

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      <Link
        href="/exceptions"
        className="mb-3 inline-flex items-center gap-1.5 text-[12.5px]"
        style={{ color: "var(--ink-3)" }}
      >
        <ArrowLeftIcon size={12} weight="bold" /> Exceptions
      </Link>

      <header className="border-b pb-4" style={{ borderColor: "var(--line)" }}>
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          <SeverityMark severity={packet.severity} withLabel />
          <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            {EXCEPTION_LABEL[packet.caseType] ?? packet.caseType}
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
          <Field label="Subject" mono>{packet.primaryExternalId}</Field>
          <Field label="Source">
            {SOURCE_LABEL[packet.primarySourceSystem] ?? packet.primarySourceSystem}
          </Field>
          <div>
            <dt className="label">Confidence</dt>
            <dd className="mt-0.5 text-[13px]">
              <ConfidenceBadge value={packet.confidence} />
            </dd>
          </div>
          <Field label="Age" mono>{ageInDays(packet.openedAt)}d</Field>
          <Field label="Ruleset" mono>{packet.rulesetVersion}</Field>
        </dl>

        {packet.hypothesis && (
          <p className="mt-3 max-w-[80ch] text-[13px]" style={{ color: "var(--ink-2)" }}>
            {packet.hypothesis}
          </p>
        )}
      </header>

      <div className="mt-5 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex flex-col gap-4">
          {present.length > 0 ? (
            <Timeline
              present={present}
              note={
                packet.recommendation ||
                "Stages with no attributed record are shown as gaps rather than omitted."
              }
            />
          ) : (
            <Panel title="Timeline">
              <EmptyState
                title="No linked records"
                body="This case names a record that could not be grouped with any other, which is itself the finding."
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
            caseId={packet.id}
            investigation={packet.aiInvestigations[0] ?? null}
            evidence={packet.evidence}
          />
        </div>

        <aside className="flex flex-col gap-4">
          <DecisionPanel
            caseId={packet.id}
            amountAtRiskMinor={packet.amountAtRiskMinor}
            currency={packet.currency}
            requiresControllerApproval={packet.requiresControllerApproval}
            viewerRole={viewer?.role ?? "analyst"}
            reviewThresholdMinor={REVIEW_THRESHOLD_MINOR}
            decided={
              packet.resolution
                ? {
                    resolution: packet.resolution,
                    reasonCode: packet.reasonCode,
                    note: packet.decisionNote,
                    by: packet.decidedBy,
                    byRole: packet.decidedByRole,
                    at: packet.decidedAt,
                  }
                : null
            }
          />

          {packet.gate.length > 0 && <GatePanel conditions={packet.gate} />}

          {packet.audit.length > 0 ? (
            <AuditList events={packet.audit} />
          ) : (
            <Panel title="Audit history" subtitle="Append-only">
              <EmptyState
                title="No activity yet"
                body="Decisions and investigations on this case will appear here."
              />
            </Panel>
          )}
        </aside>
      </div>

      {run && (
        <p className="mt-4 text-[12px]" style={{ color: "var(--ink-3)" }}>
          From run {run.id}, completed {run.completedAt ?? "—"}.
        </p>
      )}
    </div>
  );
}

function Field({
  label,
  children,
  mono = false,
}: {
  label: string;
  children: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd
        className={`mt-0.5 text-[13px] ${mono ? "num" : ""}`}
        style={{ color: "var(--ink)" }}
      >
        {children}
      </dd>
    </div>
  );
}
