/**
 * Fixture data, shaped exactly like the API contract in `lib/types.ts`.
 *
 * This exists so the two screens that matter can be designed and reviewed
 * before `apps/api` serves anything. Every value here is realistic: the
 * fee is 2% with 18% GST on the fee, the settlement window is T+1 to T+3,
 * the bank narrations are truncated the way real NEFT narrations are.
 *
 * When the API lands, delete this file. Nothing imports it except the
 * page-level loaders.
 */

import type { CasePacket, ExceptionCase, Transaction } from "@/lib/types";

const RUN = "run_2026_03_04_0912";
const RULESET = "rules@1.4.0";

// --------------------------------------------------------------------------
// The queue
// --------------------------------------------------------------------------

export const QUEUE: ExceptionCase[] = [
  {
    id: "exc_8f3a21",
    runId: RUN,
    caseType: "missing_bank_credit",
    severity: "critical",
    status: "unresolved",
    amountAtRiskMinor: "48746770",
    currency: "INR",
    confidence: 0.62,
    hypothesis:
      "Settlement is marked paid but no bank credit can be attributed to it without ambiguity.",
    assignedTo: "Meera Balakrishnan",
    openedAt: "2026-03-04T09:14:22Z",
    primaryExternalId: "setl_QpR8vT2aBn40",
    primarySourceSystem: "razorpay_settlements",
    rulesetVersion: RULESET,
    requiresControllerApproval: true,
  },
  {
    id: "exc_7b1c94",
    runId: RUN,
    caseType: "amount_mismatch",
    severity: "critical",
    status: "pending_approval",
    amountAtRiskMinor: "21440000",
    currency: "INR",
    confidence: 0.71,
    hypothesis: "Ledger revenue posting excludes the GST component on gateway fees.",
    assignedTo: "Rohit Deshpande",
    openedAt: "2026-03-04T09:14:31Z",
    primaryExternalId: "JNL-2026-03-1187",
    primarySourceSystem: "internal_ledger",
    rulesetVersion: RULESET,
    requiresControllerApproval: true,
  },
  {
    id: "exc_2d90fe",
    runId: RUN,
    caseType: "duplicate",
    severity: "high",
    status: "open",
    amountAtRiskMinor: "8925000",
    currency: "INR",
    confidence: 0.98,
    hypothesis: "Bank statement for 02 Mar was imported twice under different filenames.",
    assignedTo: null,
    openedAt: "2026-03-04T09:14:33Z",
    primaryExternalId: "BNK20260302-0088",
    primarySourceSystem: "bank_statement",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_51ae07",
    runId: RUN,
    caseType: "fee_tax_discrepancy",
    severity: "high",
    status: "investigating",
    amountAtRiskMinor: "3178400",
    currency: "INR",
    confidence: 0.83,
    hypothesis: "UPI transactions charged at the card fee rate for the 01 Mar batch.",
    assignedTo: "Farhan Qureshi",
    openedAt: "2026-03-04T09:14:35Z",
    primaryExternalId: "setl_QpR6mK4tYc18",
    primarySourceSystem: "razorpay_settlements",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_9c44b2",
    runId: RUN,
    caseType: "refund_unlinked",
    severity: "high",
    status: "open",
    amountAtRiskMinor: "1299900",
    currency: "INR",
    confidence: 0.55,
    hypothesis: "Refund references a payment captured before the imported date range.",
    assignedTo: null,
    openedAt: "2026-03-04T09:14:36Z",
    primaryExternalId: "rfnd_QpS1nD7hVe62",
    primarySourceSystem: "gateway_payments",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_a027d5",
    runId: RUN,
    caseType: "unmatched_payment",
    severity: "medium",
    status: "open",
    amountAtRiskMinor: "874500",
    currency: "INR",
    confidence: 0.68,
    hypothesis: "Captured 03 Mar at 23:51 IST; the settlement window has not closed.",
    assignedTo: null,
    openedAt: "2026-03-04T09:14:38Z",
    primaryExternalId: "pay_QpT4kR9wXa2L",
    primarySourceSystem: "gateway_payments",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_bb6134",
    runId: RUN,
    caseType: "status_conflict",
    severity: "medium",
    status: "investigating",
    amountAtRiskMinor: "655000",
    currency: "INR",
    confidence: 0.79,
    hypothesis: "Gateway reports captured; the invoice system still shows the order unpaid.",
    assignedTo: "Ananya Raghunathan",
    openedAt: "2026-03-04T09:14:39Z",
    primaryExternalId: "INV-2026-004412",
    primarySourceSystem: "invoices",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_43f8ac",
    runId: RUN,
    caseType: "date_mismatch",
    severity: "low",
    status: "open",
    amountAtRiskMinor: "412300",
    currency: "INR",
    confidence: 0.91,
    hypothesis: "Settled T+4 across the Holi holiday; totals reconcile exactly.",
    assignedTo: null,
    openedAt: "2026-03-04T09:14:41Z",
    primaryExternalId: "setl_QpR5jH2sWb09",
    primarySourceSystem: "razorpay_settlements",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_dd12e6",
    runId: RUN,
    caseType: "unmatched_payment",
    severity: "low",
    status: "resolved",
    amountAtRiskMinor: "218000",
    currency: "INR",
    confidence: 0.96,
    hypothesis: "Settlement line arrived in the 04 Mar export.",
    assignedTo: "Devika Nair",
    openedAt: "2026-03-03T09:11:02Z",
    primaryExternalId: "pay_QpQ8wE3rTy71",
    primarySourceSystem: "gateway_payments",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
  {
    id: "exc_6e7701",
    runId: RUN,
    caseType: "date_mismatch",
    severity: "low",
    status: "dismissed",
    amountAtRiskMinor: "97650",
    currency: "INR",
    confidence: 0.94,
    hypothesis: "Payment captured 23:58 IST settled the following business date.",
    assignedTo: "Devika Nair",
    openedAt: "2026-03-03T09:11:05Z",
    primaryExternalId: "pay_QpQ2aS5dFg44",
    primarySourceSystem: "gateway_payments",
    rulesetVersion: RULESET,
    requiresControllerApproval: false,
  },
];

// --------------------------------------------------------------------------
// The flagship packet: one bank credit, two settlements that both fit it.
// The engine abstains rather than guessing. This is the case worth showing.
// --------------------------------------------------------------------------

const settlement: Transaction = {
  id: "txn_0191aa",
  entityType: "settlement_batch",
  sourceSystem: "razorpay_settlements",
  externalId: "setl_QpR8vT2aBn40",
  referenceId: null,
  currency: "INR",
  grossAmountMinor: "49925000",
  feeAmountMinor: "998500",
  taxAmountMinor: "179730",
  netAmountMinor: "48746770",
  direction: "credit",
  status: "settled",
  eventAt: "2026-03-04T05:30:00Z",
  businessDate: "2026-03-04",
  tzAssumed: false,
  counterparty: "Razorpay Software Private Limited",
  description: "Settlement batch, 214 payments, 3 refunds",
  dataQualityFlags: ["settlement_utr_missing"],
};

const bankA: Transaction = {
  id: "txn_0191b7",
  entityType: "bank_transaction",
  sourceSystem: "bank_statement",
  externalId: "BNK20260304-0117",
  referenceId: "UTR773941",
  currency: "INR",
  grossAmountMinor: "48746770",
  feeAmountMinor: "0",
  taxAmountMinor: "0",
  netAmountMinor: "48746770",
  direction: "credit",
  status: "posted",
  eventAt: "2026-03-04T11:42:00Z",
  businessDate: "2026-03-04",
  tzAssumed: true,
  counterparty: "HDFC Bank, current account 5021",
  description: "NEFT CR-RAZORPAY SOFTWARE PVT LT-UTR773941",
  dataQualityFlags: [],
};

const bankB: Transaction = {
  id: "txn_0191c2",
  entityType: "bank_transaction",
  sourceSystem: "bank_statement",
  externalId: "BNK20260304-0142",
  referenceId: "UTR773948",
  currency: "INR",
  grossAmountMinor: "48746770",
  feeAmountMinor: "0",
  taxAmountMinor: "0",
  netAmountMinor: "48746770",
  direction: "credit",
  status: "posted",
  eventAt: "2026-03-04T14:07:00Z",
  businessDate: "2026-03-04",
  tzAssumed: true,
  counterparty: "HDFC Bank, current account 5021",
  description: "NEFT CR-RAZORPAY SOFTWARE-UTR773948",
  dataQualityFlags: [],
};

export const PACKET: CasePacket = {
  ...QUEUE[0],

  transactions: [
    { role: "subject", transaction: settlement },
  ],

  bridge: {
    currency: "INR",
    components: [
      { label: "Gross captured, 214 payments", amountMinor: "50240000", operation: "base", sourceRef: "setl_QpR8vT2aBn40" },
      { label: "Refunds, 3", amountMinor: "315000", operation: "subtract", sourceRef: "setl_QpR8vT2aBn40" },
      { label: "Gateway fee, 2.00%", amountMinor: "998500", operation: "subtract", sourceRef: "fee_schedule@2026-01" },
      { label: "GST on fee, 18.00%", amountMinor: "179730", operation: "subtract", sourceRef: "fee_schedule@2026-01" },
    ],
    expectedNetMinor: "48746770",
    observedNetMinor: "48746770",
    differenceMinor: "0",
    toleranceMinor: "100",
    balances: true,
  },

  evidence: [
    {
      id: "ev_01",
      ruleCode: "R3",
      evidenceType: "amount_identity",
      statement: "Sum of 214 settlement lines equals the batch net, to the paise.",
      computed: { "Σ line.net": "48746770", "batch.net": "48746770", difference: "0" },
      passed: true,
    },
    {
      id: "ev_02",
      ruleCode: "R3",
      evidenceType: "fee_identity",
      statement: "gross − fee − tax = net holds for every line in the batch.",
      computed: { lines_checked: "214", lines_failing: "0" },
      passed: true,
    },
    {
      id: "ev_03",
      ruleCode: "R2",
      evidenceType: "exact_reference",
      statement: "No settlement identifier could be extracted from either bank narration.",
      computed: {
        "settlement.utr": "(absent from source export)",
        "narration_a.utr": "UTR773941",
        "narration_b.utr": "UTR773948",
      },
      passed: false,
    },
    {
      id: "ev_04",
      ruleCode: "R6",
      evidenceType: "amount_and_window",
      statement: "Two bank credits match the net exactly, both inside the T+0 to T+3 window.",
      computed: { candidates_in_window: "2", exact_amount_matches: "2" },
      passed: false,
    },
  ],

  candidates: [
    {
      id: "cnd_01",
      candidateTransaction: bankA,
      score: 0.87,
      scoreComponents: { identifier: 0.0, amount: 1.0, date: 1.0, status: 1.0, counterparty: 0.94 },
      rank: 1,
      accepted: false,
      rejectionReason:
        "Not accepted: a competing candidate scores within the 0.05 margin, so no single attribution is defensible.",
      marginToRunnerUp: 0.02,
    },
    {
      id: "cnd_02",
      candidateTransaction: bankB,
      score: 0.85,
      scoreComponents: { identifier: 0.0, amount: 1.0, date: 1.0, status: 1.0, counterparty: 0.81 },
      rank: 2,
      accepted: false,
      rejectionReason:
        "Not accepted: indistinguishable from the leading candidate on every signal except a weaker counterparty string match.",
      marginToRunnerUp: null,
    },
  ],

  gate: [
    { key: "confidence", label: "Confidence at or above 0.95", passed: false, detail: "0.62" },
    { key: "tier", label: "Matched by a deterministic rule", passed: false, detail: "Scored, R6" },
    { key: "amount", label: "At or below the ₹50,000 auto-resolve cap", passed: false, detail: "₹4,87,467.70" },
    { key: "type", label: "Case type is not on the block list", passed: false, detail: "missing_bank_credit is blocked" },
    { key: "margin", label: "Runner-up is at least 0.05 behind", passed: false, detail: "Margin 0.02" },
    { key: "quality", label: "No open data-quality flag on any member", passed: false, detail: "settlement_utr_missing" },
  ],

  aiInvestigations: [
    {
      id: "ai_01",
      modelVersion: "claude-opus-5",
      promptVersion: "investigate@v1",
      validationStatus: "valid",
      validationErrors: [],
      classification: "missing_bank_credit",
      hypotheses: [
        {
          statement:
            "The settlement export omitted the UTR field, so the only remaining link to the bank is the amount and the date. Two credits satisfy both.",
          evidenceIds: ["ev_03", "ev_04"],
          likelihood: "high",
        },
        {
          statement:
            "The batch arithmetic is sound, so this is an attribution problem rather than a shortfall. Money has probably arrived; which batch it belongs to is unknown.",
          evidenceIds: ["ev_01", "ev_02"],
          likelihood: "high",
        },
        {
          statement:
            "The two credits posted 2 hours 25 minutes apart, consistent with two payout cycles landing on the same business date.",
          evidenceIds: ["ev_04"],
          likelihood: "medium",
        },
      ],
      recommendedAction:
        "Request the UTR for setl_QpR8vT2aBn40 from the settlement report, or ask the bank for the remitter reference on BNK20260304-0117 and BNK20260304-0142. Do not attribute either credit until one of those returns.",
      requiresHumanApproval: true,
      confidence: 0.74,
      uncertainties: [
        "Whether a second settlement batch on 04 Mar also awaits a credit was not part of this evidence packet.",
        "The narration for BNK20260304-0142 is truncated; the full remitter string may distinguish the two.",
        "No refund or chargeback activity after 04 Mar was retrieved, so a later reversal cannot be ruled out.",
      ],
      latencyMs: 4180,
      createdAt: "2026-03-04T10:02:14Z",
    },
  ],

  audit: [
    {
      id: "aud_01",
      action: "Case created",
      actorType: "system",
      actorName: "Reconciliation engine",
      detail: "R6 produced two candidates within the margin. Auto-resolution gate failed 6 of 6 conditions.",
      rulesetVersion: RULESET,
      createdAt: "2026-03-04T09:14:22Z",
    },
    {
      id: "aud_02",
      action: "Assigned",
      actorType: "user",
      actorName: "Rohit Deshpande",
      actorRole: "controller",
      detail: "Assigned to Meera Balakrishnan.",
      createdAt: "2026-03-04T09:41:07Z",
    },
    {
      id: "aud_03",
      action: "AI investigation requested",
      actorType: "user",
      actorName: "Meera Balakrishnan",
      actorRole: "analyst",
      detail: "Grounded investigation returned in 4.18s. All 4 citations verified against the packet.",
      createdAt: "2026-03-04T10:02:14Z",
    },
    {
      id: "aud_04",
      action: "Comment added",
      actorType: "user",
      actorName: "Meera Balakrishnan",
      actorRole: "analyst",
      detail: "Raised a ticket with the payments team for the missing UTR. Holding until Thursday.",
      createdAt: "2026-03-04T10:19:55Z",
    },
  ],
};

export function findCase(id: string): CasePacket | null {
  if (id === PACKET.id) return PACKET;
  const summary = QUEUE.find((c) => c.id === id);
  if (!summary) return null;
  // Other cases have no packet built yet; the page renders what exists and
  // says so rather than inventing evidence.
  return {
    ...summary,
    transactions: [],
    bridge: null,
    evidence: [],
    candidates: [],
    gate: [],
    aiInvestigations: [],
    audit: [
      {
        id: "aud_x1",
        action: "Case created",
        actorType: "system",
        actorName: "Reconciliation engine",
        detail: summary.hypothesis ?? "Created by the exception engine.",
        rulesetVersion: RULESET,
        createdAt: summary.openedAt,
      },
    ],
  };
}
