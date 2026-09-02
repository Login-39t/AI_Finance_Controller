import {
  CheckIcon,
  RobotIcon,
  WarningIcon,
  XIcon,
} from "@phosphor-icons/react/dist/ssr";

import { formatInstant, formatMinor } from "@/lib/money";
import type {
  AiInvestigation,
  AmountBridge,
  AuditEvent,
  Candidate,
  Evidence,
  GateCondition,
  Transaction,
} from "@/lib/types";
import { ENTITY_LABEL, SOURCE_LABEL } from "@/lib/types";
import { InvestigateButton } from "./investigate-button";
import { Money, Panel } from "./primitives";

// --------------------------------------------------------------------------
// Timeline
// --------------------------------------------------------------------------

const STAGES = ["payment", "settlement_batch", "bank_transaction", "ledger_entry"] as const;
const STAGE_LABEL: Record<(typeof STAGES)[number], string> = {
  payment: "Payment",
  settlement_batch: "Settlement",
  bank_transaction: "Bank",
  ledger_entry: "Ledger",
};

/**
 * A missing stage renders as a dashed outline, not as an omission. The
 * gap in the chain *is* the finding, so it has to be visible rather than
 * absent.
 */
export function Timeline({
  present,
  note,
}: {
  present: { entity: (typeof STAGES)[number]; label: string; at: string }[];
  note?: string;
}) {
  return (
    <Panel title="Timeline" subtitle="Payment to ledger, with the actual dates">
      <div className="overflow-x-auto px-4 py-4">
        <ol className="flex min-w-[640px] items-stretch gap-0">
          {STAGES.map((stage, i) => {
            const hit = present.find((p) => p.entity === stage);
            return (
              <li key={stage} className="flex flex-1 items-stretch">
                <div
                  className="flex-1 border px-3 py-2.5"
                  style={{
                    borderRadius: "var(--radius)",
                    borderColor: hit ? "var(--line)" : "var(--flag-line)",
                    borderStyle: hit ? "solid" : "dashed",
                    background: hit ? "var(--surface-2)" : "transparent",
                  }}
                >
                  <div className="label" style={{ color: hit ? "var(--ink-3)" : "var(--flag)" }}>
                    {STAGE_LABEL[stage]}
                  </div>
                  {hit ? (
                    <>
                      <div className="num mt-1 text-[12px]" style={{ color: "var(--ink)" }}>
                        {hit.label}
                      </div>
                      <div className="mt-0.5 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
                        {formatInstant(hit.at)}
                      </div>
                    </>
                  ) : (
                    <div className="mt-1 text-[12px]" style={{ color: "var(--flag)" }}>
                      Not attributed
                    </div>
                  )}
                </div>
                {i < STAGES.length - 1 && (
                  <div className="flex w-6 shrink-0 items-center justify-center" aria-hidden>
                    <span className="h-px w-full" style={{ background: "var(--line)" }} />
                  </div>
                )}
              </li>
            );
          })}
        </ol>
        {note && (
          <p className="mt-3 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            {note}
          </p>
        )}
      </div>
    </Panel>
  );
}

// --------------------------------------------------------------------------
// Amount bridge
// --------------------------------------------------------------------------

/**
 * The arithmetic, laid out as arithmetic.
 *
 * A finance reviewer should be able to check this with their eyes the way
 * they would check a column on paper, which is why every component sits on
 * its own line with its operator visible and the total is ruled off.
 */
export function AmountBridgeView({ bridge }: { bridge: AmountBridge }) {
  return (
    <Panel
      title="Amount bridge"
      subtitle="gross − refunds − fees − taxes = net"
      actions={
        <span
          className="inline-flex items-center gap-1.5 px-2 py-[2px] text-[11.5px] font-medium"
          style={{
            borderRadius: "var(--radius)",
            color: bridge.balances ? "var(--ok)" : "var(--flag)",
            background: bridge.balances ? "var(--ok-wash)" : "var(--flag-wash)",
          }}
        >
          {bridge.balances ? <CheckIcon size={11} weight="bold" /> : <XIcon size={11} weight="bold" />}
          {bridge.balances ? "Balances to the paise" : "Does not balance"}
        </span>
      }
    >
      <div className="px-4 py-3">
        <table className="w-full border-collapse">
          <tbody>
            {bridge.components.map((c, i) => (
              <tr key={`${c.label}-${i}`}>
                <td className="w-5 py-[5px] align-baseline">
                  <span className="num text-[12px]" style={{ color: "var(--ink-3)" }}>
                    {c.operation === "base" ? "" : c.operation === "subtract" ? "−" : "+"}
                  </span>
                </td>
                <td className="py-[5px] pr-4 align-baseline text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                  {c.label}
                </td>
                <td className="py-[5px] pr-4 text-right align-baseline">
                  <Money minor={c.amountMinor} currency={bridge.currency} />
                </td>
                <td className="num py-[5px] text-right align-baseline text-[11px]" style={{ color: "var(--ink-3)" }}>
                  {c.sourceRef}
                </td>
              </tr>
            ))}

            <tr style={{ borderTop: "1px solid var(--ink-3)" }}>
              <td />
              <td className="py-[6px] pr-4 text-[12.5px] font-medium" style={{ color: "var(--ink)" }}>
                Expected net
              </td>
              <td className="py-[6px] pr-4 text-right">
                <Money minor={bridge.expectedNetMinor} currency={bridge.currency} className="font-semibold" />
              </td>
              <td />
            </tr>
            <tr>
              <td />
              <td className="py-[5px] pr-4 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                Observed net
              </td>
              <td className="py-[5px] pr-4 text-right">
                <Money minor={bridge.observedNetMinor} currency={bridge.currency} />
              </td>
              <td />
            </tr>
            <tr style={{ borderTop: "1px solid var(--line)" }}>
              <td />
              <td className="py-[6px] pr-4 text-[12.5px] font-medium" style={{ color: "var(--ink)" }}>
                Difference
              </td>
              <td className="py-[6px] pr-4 text-right">
                <Money
                  minor={bridge.differenceMinor}
                  currency={bridge.currency}
                  className="font-semibold"
                />
              </td>
              <td className="num py-[6px] text-right text-[11px]" style={{ color: "var(--ink-3)" }}>
                tolerance {formatMinor(bridge.toleranceMinor, bridge.currency)}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

// --------------------------------------------------------------------------
// Evidence
// --------------------------------------------------------------------------

export function EvidenceList({ evidence }: { evidence: Evidence[] }) {
  return (
    <Panel title="Evidence" subtitle={`${evidence.length} rule checks, with the values compared`}>
      <ul>
        {evidence.map((e, i) => (
          <li
            key={e.id}
            className="px-4 py-3"
            style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
          >
            <div className="flex items-start gap-2.5">
              <span
                className="mt-[3px] inline-flex h-[15px] w-[15px] shrink-0 items-center justify-center"
                style={{
                  borderRadius: "var(--radius)",
                  background: e.passed ? "var(--ok-wash)" : "var(--flag-wash)",
                  color: e.passed ? "var(--ok)" : "var(--flag)",
                }}
                aria-label={e.passed ? "Passed" : "Failed"}
              >
                {e.passed ? <CheckIcon size={10} weight="bold" /> : <XIcon size={10} weight="bold" />}
              </span>

              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-2">
                  <span className="num text-[11px] font-medium" style={{ color: "var(--ink-3)" }}>
                    {e.ruleCode}
                  </span>
                  <span className="text-[12.5px]" style={{ color: "var(--ink)" }}>
                    {e.statement}
                  </span>
                </div>
                <dl className="mt-1.5 flex flex-wrap gap-x-5 gap-y-1">
                  {Object.entries(e.computed).map(([k, v]) => (
                    <div key={k} className="flex items-baseline gap-1.5">
                      <dt className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
                        {k}
                      </dt>
                      <dd className="num text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                        {v}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// --------------------------------------------------------------------------
// Candidates
// --------------------------------------------------------------------------

/**
 * Every candidate the engine considered, with its score and the reason it
 * was not taken. When two candidates sit inside the margin, that fact is
 * stated in plain words at the top: the abstention is the finding, and
 * burying it would defeat the point of showing candidates at all.
 */
export function CandidateList({ candidates, margin }: { candidates: Candidate[]; margin: number }) {
  const contested =
    candidates.length > 1 &&
    candidates[0].marginToRunnerUp != null &&
    candidates[0].marginToRunnerUp < margin;

  return (
    <Panel title="Candidates considered" subtitle={`${candidates.length} within the retrieval window`}>
      {contested && (
        <div
          className="flex items-start gap-2.5 border-b px-4 py-3"
          style={{ background: "var(--flag-wash)", borderColor: "var(--flag-line)" }}
        >
          <WarningIcon size={15} weight="fill" style={{ color: "var(--flag)", marginTop: 1 }} />
          <p className="text-[12.5px]" style={{ color: "var(--ink)" }}>
            <strong className="font-semibold">Two candidates are indistinguishable.</strong> The
            leading candidate is {candidates[0].marginToRunnerUp?.toFixed(2)} ahead, inside the{" "}
            {margin.toFixed(2)} margin the policy requires. The engine will not choose between them,
            so this case is left unresolved with both shown.
          </p>
        </div>
      )}

      <ul>
        {candidates.map((c, i) => (
          <li
            key={c.id}
            className="px-4 py-3"
            style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <div className="flex items-baseline gap-2.5">
                <span className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
                  #{c.rank}
                </span>
                <span className="num text-[12.5px] font-medium" style={{ color: "var(--ink)" }}>
                  {c.candidateTransaction.externalId}
                </span>
                <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                  {ENTITY_LABEL[c.candidateTransaction.entityType]} ·{" "}
                  {SOURCE_LABEL[c.candidateTransaction.sourceSystem]}
                </span>
              </div>
              <div className="flex items-baseline gap-4">
                <Money
                  minor={c.candidateTransaction.netAmountMinor}
                  currency={c.candidateTransaction.currency}
                />
                <span className="num text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
                  {c.score.toFixed(2)}
                </span>
              </div>
            </div>

            <p className="num mt-1 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              {c.candidateTransaction.description}
            </p>

            {/* Component breakdown, as numbers rather than progress bars.
                A filled track would imply a magnitude the score does not
                have, and it is dashboard clutter on a decision screen. */}
            <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1">
              {Object.entries(c.scoreComponents).map(([k, v]) => (
                <div key={k} className="flex items-baseline gap-1.5">
                  <dt className="label">{k}</dt>
                  <dd
                    className="num text-[11.5px]"
                    style={{ color: v === 0 ? "var(--flag)" : "var(--ink-2)" }}
                  >
                    {v.toFixed(2)}
                  </dd>
                </div>
              ))}
            </dl>

            {c.rejectionReason && (
              <p className="mt-2 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                {c.rejectionReason}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// --------------------------------------------------------------------------
// The gate
// --------------------------------------------------------------------------

/**
 * All six conditions, evaluated. This is the auditor's screen: it answers
 * "why did the system not clear this" without anyone having to read code.
 */
export function GatePanel({ conditions }: { conditions: GateCondition[] }) {
  const failed = conditions.filter((c) => !c.passed).length;
  return (
    <Panel
      title="Auto-resolution gate"
      subtitle={`${conditions.length - failed} of ${conditions.length} conditions met`}
    >
      <p className="border-b px-4 py-2.5 text-[12.5px]" style={{ borderColor: "var(--line-soft)", color: "var(--ink-2)" }}>
        Every condition must hold for the system to clear a case on its own. A single failure routes
        it to a human. This case fails {failed}.
      </p>
      <ul>
        {conditions.map((c, i) => (
          <li
            key={c.key}
            className="flex items-center gap-2.5 px-4 py-2"
            style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
          >
            <span
              className="inline-flex h-[15px] w-[15px] shrink-0 items-center justify-center"
              style={{
                borderRadius: "var(--radius)",
                background: c.passed ? "var(--ok-wash)" : "var(--flag-wash)",
                color: c.passed ? "var(--ok)" : "var(--flag)",
              }}
              aria-label={c.passed ? "Met" : "Not met"}
            >
              {c.passed ? <CheckIcon size={10} weight="bold" /> : <XIcon size={10} weight="bold" />}
            </span>
            <span className="flex-1 text-[12.5px]" style={{ color: "var(--ink)" }}>
              {c.label}
            </span>
            <span className="num text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              {c.detail}
            </span>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

// --------------------------------------------------------------------------
// AI investigation
// --------------------------------------------------------------------------

const AI_FAILURE_COPY: Record<string, string> = {
  schema_invalid: "The response did not match the required structure after one repair attempt.",
  citation_violation: "The response cited a record that is not in this case. It was rejected.",
  numeric_violation: "The response asserted a number the engine did not compute. It was rejected.",
  unavailable: "The model could not be reached. The deterministic finding below stands unchanged.",
};

/**
 * The AI panel is visually quarantined: its own tint, its own border, an
 * explicit label. A reader must never be unsure whether they are looking
 * at a computed fact or a generated sentence.
 */
export function AiPanel({
  caseId,
  investigation,
  evidence,
}: {
  caseId: string;
  investigation: AiInvestigation | null;
  evidence: Evidence[];
}) {
  const evidenceRule = (id: string) => evidence.find((e) => e.id === id)?.ruleCode ?? id;

  return (
    <section
      className="border"
      style={{
        background: "var(--warn-wash)",
        borderColor: "var(--line)",
        borderRadius: "var(--radius)",
      }}
    >
      <header
        className="flex flex-wrap items-baseline justify-between gap-2 border-b px-4 py-2.5"
        style={{ borderColor: "var(--line)" }}
      >
        <div className="flex items-center gap-2">
          <RobotIcon size={15} weight="regular" style={{ color: "var(--warn)" }} />
          <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
            AI investigation
          </h2>
          <span className="label">Assistance, not a decision</span>
        </div>
        {investigation && (
          <span className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
            {investigation.modelVersion} · {investigation.promptVersion}
          </span>
        )}
      </header>

      {!investigation && (
        <div className="px-4 py-5">
          <p className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            No investigation has been requested for this case. The evidence above is complete
            without one.
          </p>
        </div>
      )}

      {investigation && investigation.validationStatus !== "valid" && (
        <div className="px-4 py-4">
          <p className="text-[12.5px] font-medium" style={{ color: "var(--flag)" }}>
            No grounded answer was produced.
          </p>
          <p className="mt-1 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            {AI_FAILURE_COPY[investigation.validationStatus]}
          </p>
        </div>
      )}

      {investigation && investigation.validationStatus === "valid" && (
        <div className="flex flex-col gap-4 px-4 py-4">
          <div>
            <span className="label">Ranked hypotheses</span>
            <ol className="mt-2 flex flex-col gap-2.5">
              {investigation.hypotheses.map((h, i) => (
                <li key={i} className="flex gap-2.5">
                  <span className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
                    {i + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="text-[12.5px]" style={{ color: "var(--ink)" }}>
                      {h.statement}
                    </p>
                    <div className="mt-1 flex flex-wrap items-center gap-1.5">
                      <span className="label">{h.likelihood}</span>
                      {h.evidenceIds.map((id) => (
                        <span
                          key={id}
                          className="num border px-1.5 py-[1px] text-[10.5px]"
                          style={{
                            borderRadius: "var(--radius)",
                            borderColor: "var(--line)",
                            color: "var(--ink-2)",
                          }}
                          title="Verified against this case's evidence packet"
                        >
                          {evidenceRule(id)}
                        </span>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          </div>

          {investigation.recommendedAction && (
            <div>
              <span className="label">Recommended action</span>
              <p className="mt-1 text-[12.5px]" style={{ color: "var(--ink)" }}>
                {investigation.recommendedAction}
              </p>
            </div>
          )}

          {/* Uncertainties get the same weight as the hypotheses. A model
              that states what it does not know is more useful than one
              that sounds certain. */}
          <div>
            <span className="label">Stated uncertainties</span>
            <ul className="mt-1 flex flex-col gap-1">
              {investigation.uncertainties.map((u, i) => (
                <li key={i} className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
                  {u}
                </li>
              ))}
            </ul>
          </div>

          <p className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
            All {investigation.hypotheses.reduce((n, h) => n + h.evidenceIds.length, 0)} citations
            verified against this packet. Model confidence {investigation.confidence?.toFixed(2)} is
            advisory and does not feed the gate.
          </p>
        </div>
      )}

      <footer className="border-t px-4 py-3" style={{ borderColor: "var(--line)" }}>
        <InvestigateButton caseId={caseId} hasInvestigation={investigation !== null} />
      </footer>
    </section>
  );
}

// --------------------------------------------------------------------------
// Records and audit
// --------------------------------------------------------------------------

export function RecordList({ records }: { records: { role: string; transaction: Transaction }[] }) {
  return (
    <Panel title="Records" subtitle={`${records.length} in this case`}>
      <ul>
        {records.map(({ role, transaction: t }, i) => (
          <li
            key={t.id}
            className="px-4 py-3"
            style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
          >
            <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
              <div className="flex items-baseline gap-2.5">
                <span className="num text-[12.5px] font-medium" style={{ color: "var(--ink)" }}>
                  {t.externalId}
                </span>
                <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
                  {ENTITY_LABEL[t.entityType]} · {SOURCE_LABEL[t.sourceSystem]} · {t.status}
                </span>
              </div>
              <Money minor={t.netAmountMinor} currency={t.currency} className="font-medium" />
            </div>

            <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 sm:grid-cols-4">
              <Cell label="Gross" value={formatMinor(t.grossAmountMinor, t.currency)} />
              <Cell label="Fee" value={formatMinor(t.feeAmountMinor, t.currency)} />
              <Cell label="Tax" value={formatMinor(t.taxAmountMinor, t.currency)} />
              <Cell label="Business date" value={t.businessDate} />
            </dl>

            {t.dataQualityFlags.length > 0 && (
              <p className="num mt-2 text-[11.5px]" style={{ color: "var(--flag)" }}>
                Data quality: {t.dataQualityFlags.join(", ")}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Panel>
  );
}

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="label">{label}</dt>
      <dd className="num text-[12px]" style={{ color: "var(--ink-2)" }}>
        {value}
      </dd>
    </div>
  );
}

export function AuditList({ events }: { events: AuditEvent[] }) {
  return (
    <Panel title="Audit history" subtitle="Append-only">
      <ul>
        {[...events].reverse().map((e, i) => (
          <li
            key={e.id}
            className="px-4 py-2.5"
            style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
          >
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-[12.5px] font-medium" style={{ color: "var(--ink)" }}>
                {e.action}
              </span>
              <span className="num shrink-0 text-[11px]" style={{ color: "var(--ink-3)" }}>
                {formatInstant(e.createdAt)}
              </span>
            </div>
            <p className="mt-0.5 text-[12px]" style={{ color: "var(--ink-2)" }}>
              {e.detail}
            </p>
            <p className="mt-0.5 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              {e.actorName}
              {e.actorRole ? `, ${e.actorRole}` : ""}
              {e.rulesetVersion ? ` · ${e.rulesetVersion}` : ""}
            </p>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
