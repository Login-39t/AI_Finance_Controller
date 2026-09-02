/**
 * The API contract, hand-written for now.
 *
 * These types will be replaced wholesale by `openapi-typescript` output
 * once `apps/api` serves `/openapi.json`. They are written to match the
 * schema in `db/schema.sql` exactly so that swap is a delete, not a
 * rewrite - including the rule that every money field is a string of
 * minor units.
 */

import type { MinorUnits } from "./money";

export type ExceptionType =
  | "unmatched_payment"
  | "missing_bank_credit"
  | "amount_mismatch"
  | "date_mismatch"
  | "duplicate"
  | "refund_unlinked"
  | "status_conflict"
  | "fee_tax_discrepancy";

export type Severity = "critical" | "high" | "medium" | "low";

export type CaseStatus =
  | "open"
  | "investigating"
  | "pending_approval"
  | "resolved"
  | "dismissed"
  | "unresolved";

export type EntityType =
  | "payment"
  | "refund"
  | "settlement_batch"
  | "settlement_line"
  | "bank_transaction"
  | "invoice"
  | "ledger_entry"
  | "adjustment"
  | "dispute";

export type SourceSystem =
  | "gateway_payments"
  | "razorpay_settlements"
  | "bank_statement"
  | "invoices"
  | "internal_ledger";

export type Role = "analyst" | "reviewer" | "controller" | "admin";

export type CaseResolution =
  | "approved"
  | "rejected"
  | "overridden"
  | "dismissed"
  | "auto_resolved";

export type AiValidationStatus =
  | "valid"
  | "schema_invalid"
  | "citation_violation"
  | "numeric_violation"
  | "unavailable";

export interface Transaction {
  id: string;
  entityType: EntityType;
  sourceSystem: SourceSystem;
  externalId: string;
  parentExternalId?: string | null;
  referenceId?: string | null;
  currency: string;
  grossAmountMinor: MinorUnits;
  feeAmountMinor: MinorUnits;
  taxAmountMinor: MinorUnits;
  netAmountMinor: MinorUnits;
  direction: "credit" | "debit";
  status: string;
  eventAt: string;
  businessDate: string;
  tzAssumed: boolean;
  counterparty?: string | null;
  description?: string | null;
  dataQualityFlags: string[];
}

/** One line of the gross - refunds - fees - taxes ± adjustments = net bridge. */
export interface BridgeComponent {
  label: string;
  amountMinor: MinorUnits;
  /** Negative components subtract. The sign is explicit, never inferred. */
  operation: "base" | "subtract" | "add";
  transactionId?: string | null;
  sourceRef?: string | null;
}

export interface AmountBridge {
  currency: string;
  components: BridgeComponent[];
  expectedNetMinor: MinorUnits;
  observedNetMinor: MinorUnits;
  differenceMinor: MinorUnits;
  toleranceMinor: MinorUnits;
  balances: boolean;
}

export interface Evidence {
  id: string;
  ruleCode: string;
  evidenceType: string;
  statement: string;
  computed: Record<string, string>;
  passed: boolean;
}

export interface Candidate {
  id: string;
  candidateTransaction: Transaction;
  score: number;
  scoreComponents: {
    identifier: number;
    amount: number;
    date: number;
    status: number;
    counterparty: number;
  };
  rank: number;
  accepted: boolean;
  rejectionReason?: string | null;
  marginToRunnerUp?: number | null;
}

/** Each of the six conditions, evaluated. This is the auditor's record. */
export interface GateCondition {
  key: string;
  label: string;
  passed: boolean;
  detail: string;
}

export interface AiInvestigation {
  id: string;
  modelVersion: string;
  promptVersion: string;
  validationStatus: AiValidationStatus;
  validationErrors: string[];
  classification?: ExceptionType | null;
  hypotheses: { statement: string; evidenceIds: string[]; likelihood: "high" | "medium" | "low" }[];
  recommendedAction?: string | null;
  requiresHumanApproval?: boolean | null;
  confidence?: number | null;
  uncertainties: string[];
  latencyMs?: number | null;
  createdAt: string;
}

export interface AuditEvent {
  id: string;
  action: string;
  actorType: "user" | "system" | "ai";
  actorName?: string | null;
  actorRole?: Role | null;
  reasonCode?: string | null;
  detail: string;
  rulesetVersion?: string | null;
  createdAt: string;
}

export interface ExceptionCase {
  id: string;
  runId: string;
  caseType: ExceptionType;
  severity: Severity;
  status: CaseStatus;
  amountAtRiskMinor: MinorUnits;
  currency: string;
  confidence?: number | null;
  hypothesis?: string | null;
  recommendation?: string | null;
  assignedTo?: string | null;
  openedAt: string;
  primaryExternalId: string;
  primarySourceSystem: SourceSystem;
  rulesetVersion: string;
  /** Above the policy threshold, only a controller may approve. */
  requiresControllerApproval: boolean;
  /** Present once a person has decided. Null while the case is open. */
  resolution?: CaseResolution | null;
  reasonCode?: string | null;
  decisionNote?: string | null;
  decidedBy?: string | null;
  decidedByRole?: Role | null;
  decidedAt?: string | null;
}

/** The fat packet returned by GET /v1/exceptions/{id}. One request, one page. */
export interface CasePacket extends ExceptionCase {
  transactions: { role: string; transaction: Transaction }[];
  bridge?: AmountBridge | null;
  evidence: Evidence[];
  candidates: Candidate[];
  gate: GateCondition[];
  aiInvestigations: AiInvestigation[];
  audit: AuditEvent[];
}

export const EXCEPTION_LABEL: Record<ExceptionType, string> = {
  unmatched_payment: "Unmatched payment",
  missing_bank_credit: "Missing bank credit",
  amount_mismatch: "Amount mismatch",
  date_mismatch: "Date mismatch",
  duplicate: "Duplicate",
  refund_unlinked: "Refund unlinked",
  status_conflict: "Status conflict",
  fee_tax_discrepancy: "Fee / tax discrepancy",
};

export const STATUS_LABEL: Record<CaseStatus, string> = {
  open: "Open",
  investigating: "Investigating",
  pending_approval: "Pending approval",
  resolved: "Resolved",
  dismissed: "Dismissed",
  unresolved: "Unresolved",
};

export const SOURCE_LABEL: Record<SourceSystem, string> = {
  gateway_payments: "Gateway",
  razorpay_settlements: "Settlements",
  bank_statement: "Bank",
  invoices: "Invoices",
  internal_ledger: "Ledger",
};

export const ENTITY_LABEL: Record<EntityType, string> = {
  payment: "Payment",
  refund: "Refund",
  settlement_batch: "Settlement batch",
  settlement_line: "Settlement line",
  bank_transaction: "Bank transaction",
  invoice: "Invoice",
  ledger_entry: "Ledger entry",
  adjustment: "Adjustment",
  dispute: "Dispute",
};

/** Reason codes for an override. A controlled list, per PRD story D1. */
/**
 * The controlled list an override must cite.
 *
 * These strings are the API's `ReasonCode` values verbatim. They were
 * previously a set of invented uppercase codes that no endpoint would
 * have accepted - harmless while the panel was a mock, and a guaranteed
 * 422 the moment it was wired up.
 */
export const REASON_CODES = [
  { code: "timing_difference", label: "Timing difference" },
  { code: "fee_variance_accepted", label: "Fee variance accepted" },
  { code: "bank_error_confirmed", label: "Bank error confirmed" },
  { code: "gateway_error_confirmed", label: "Gateway error confirmed" },
  { code: "duplicate_confirmed", label: "Duplicate confirmed" },
  { code: "manual_adjustment_posted", label: "Manual adjustment posted" },
  { code: "evidence_insufficient", label: "Evidence insufficient" },
  { code: "written_off_immaterial", label: "Written off, immaterial" },
  { code: "escalated_externally", label: "Escalated externally" },
  { code: "other", label: "Other, see note" },
] as const;
