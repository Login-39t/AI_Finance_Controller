# LedgerGraph — Product Requirements Document

**Version** 1.0 · **Owner** solo build · **Window** 2–4 days · **Context** Razorpay Hackathon, Track 4: AI Finance Controller

---

## 0. Decisions locked before this document

| Decision | Answer | Consequence for scope |
|---|---|---|
| Build window | Solo, 2–4 days | MVP = Phase 1 + the high-value half of Phase 2. Phase 3 is explicitly out. |
| Backend | Python / FastAPI | Matching engine, workers, synthetic data generator, and eval harness all live in one language. |
| Auth | Full stack (register, verify, login, refresh, reset, RBAC) | Delivered via `fastapi-users` so it costs hours, not a day. |
| Deployment | Local **and** hosted | One set of Dockerfiles drives Docker Compose locally and Render + Vercel in the cloud. |

---

## 1. Problem

A finance operations team has to answer one question every day: **does the money in our books agree with what the gateway, the settlement report, and the bank actually say?**

The evidence for a single customer payment is scattered across five systems that never line up cleanly:

- one settlement batch pays out many payments at once, so amounts never match 1:1;
- settlement lands T+1 to T+3, so dates never match either;
- gateway fees and GST make net settlement smaller than gross capture, so totals never match without a component bridge;
- refunds, reversals, disputes, failed payouts, duplicate imports, missing files, timezone drift, partial payments, and truncated bank narrations each break the chain in a different way.

Today this is reconciled in spreadsheets. That is slow, unauditable, and error-prone — but the deeper failure is this: **a spreadsheet can tell you two numbers differ. It cannot tell you why, and it cannot tell you how sure it is.** The cost of that gap is real money: a missing bank credit nobody chases, a duplicate journal that inflates revenue, a fee mapping error that quietly compounds for a quarter.

### The problem this product solves

Turn a pile of multi-source financial records into **three unambiguous buckets** — automatically resolved with proof, routed to a human with evidence, or explicitly unresolved — and never let a record silently fall out of the count.

### What makes it hard, and what makes it interesting

The naive version of this product is dangerous. An LLM asked "do these reconcile?" will confidently say yes. A fuzzy matcher tuned for recall will pair a ₹4,999 payment with the wrong ₹4,999 payment on the same day. **Both failure modes cost more than doing nothing,** because they manufacture a false sense of closure.

So the design constraint is inverted from most AI products: *precision over coverage, abstention over guessing, arithmetic in deterministic code and never in the model.*

---

## 2. Target users

Four personas, each with a distinct job and a distinct screen.

### 2.1 Finance operations analyst — the primary user

Works the queue all day. Wants exceptions sorted by money at risk, enough evidence to decide in under two minutes, and to never re-investigate the same case twice.

> "Give me today's exceptions, worst first, and tell me what you think happened."

**Success:** median time-to-decision under 2 minutes; no case reopened for missing evidence.

### 2.2 Finance controller — the approver

Owns the close. Wants reconciliation rate, unresolved exposure, aging, and an audit-ready explanation for every material discrepancy. Approves anything above the review threshold.

> "What is still unreconciled, how old is it, and how much is it worth?"

**Success:** can sign off the period knowing the unresolved number is complete and correct.

### 2.3 Auditor / reviewer — the read-only sceptic

Wants immutable evidence: original source values, which rule fired, which ruleset and model version, what the AI said, who approved it, and when. Must be able to reconstruct any decision without asking anyone.

> "Show me why record X was cleared, and prove nobody edited it afterwards."

**Success:** every decision reproducible from source records plus a versioned ruleset.

### 2.4 Engineering / data operations — the pipeline owner

Wants loud, specific ingestion failures instead of silent corruption, and predictable idempotent APIs.

> "Row 4,182 of `bank_2026_03.csv` was rejected because `amount` was `1,2 34.00`. Here is the row."

**Success:** zero silently coerced values; every rejected row retrievable with a reason.

**Explicitly not a user in the MVP:** the merchant or end customer. There is no external-facing surface.

---

## 3. Core features

Twelve features, ordered by build dependency and tagged with MVP status.

| # | Feature | Status | One-line definition |
|---|---|---|---|
| F1 | Multi-source ingestion | **MVP** | Upload CSV/JSON for payments, settlements, bank, invoices, ledger; preserve raw bytes and raw rows. |
| F2 | Validation & quarantine | **MVP** | Reject malformed rows with a per-row reason; never coerce a bad amount into a good one. |
| F3 | Normalisation | **MVP** | Everything to a canonical transaction: paise integers, UTC instants, controlled status vocabulary, extracted references. |
| F4 | Reconciliation runs | **MVP** | A versioned, repeatable, idempotent execution over a dataset snapshot, with live progress. |
| F5 | Deterministic matching engine | **MVP** | Ordered high-precision rules R1–R5 producing groups, links, and per-rule evidence. |
| F6 | Exception engine | **MVP** | Classify every unmatched or inconsistent record into one of 8 exception types with severity and amount at risk. |
| F7 | Confidence & auto-resolution policy | **MVP** | Deterministic gate deciding auto-resolve vs. review vs. unresolved. The model cannot override it. |
| F8 | Grounded AI investigation | **MVP** | Evidence packet in; schema-validated JSON out: classification, ranked hypotheses, cited evidence IDs, recommendation, uncertainties. |
| F9 | Review workflow & audit trail | **MVP** | Approve / reject / override with mandatory reason code; append-only audit events. |
| F10 | Reporting, metrics & export | **MVP** | Reconciliation rate, unresolved exposure, aging, held-out precision/recall, CSV export. |
| F11 | Candidate scoring (fuzzy R6–R7) | **Stretch** | Bounded-window scored candidates for records deterministic rules could not touch. |
| F12 | Reconciliation explorer | **Stretch** | Search any reference and view its full relationship graph. |

### Feature detail worth pinning down now

**F5 — the rule ladder.** Rules run in strict order and stop at the first match. Each emits an evidence row.

| Rule | Matches | Condition | Base confidence |
|---|---|---|---|
| R1 | Payment → Settlement line | Exact `payment_id` on the settlement line | 0.99 |
| R2 | Settlement batch → Bank credit | `settlement_id` extracted from bank narration **and** `net` equal to the paise | 0.98 |
| R3 | Settlement batch integrity | `Σ(line.net) == batch.net` **and** per line `gross − fee − tax == net` | validation, not a match |
| R4 | Invoice → Payment | Exact `order_id` **and** `amount_paid == payment.gross` | 0.97 |
| R5 | Ledger → Payment/Settlement | `reference` equals a known ID **and** `Σdebits == Σcredits` **and** revenue+fee+tax decomposes to gross | 0.95 |
| R6 *(stretch)* | Bank ↔ Settlement, no reference | Exact net + date in T+0…T+3 + **no competing candidate** | 0.85 → review |
| R7 *(stretch)* | Fuzzy reference | Narration reference similarity ≥ 0.85 + amount within tolerance + date window | scored → review |

**F7 — the auto-resolve gate.** All six conditions must hold. Any failure routes to review.

```text
auto_resolve  IF  confidence            >= 0.95
              AND rule_tier             == 'deterministic'
              AND amount_at_risk_minor  <= policy.auto_resolve_max_minor   (default ₹50,000)
              AND case_type NOT IN policy.never_auto_resolve
                  (duplicate, missing_bank_credit, amount_mismatch)
              AND no member record has entity_type = 'dispute'
              AND margin_to_runner_up   >= 0.05
              AND no open data-quality flag on any member record
```

**F8 — what the model is and is not allowed to do.** The model receives only a retrieved evidence packet plus policy text, and returns structured JSON. Its `confidence` is advisory input to F7 and never the final word. Every `evidence_id` it cites is verified to belong to the case; a citation to anything outside the packet fails the response and the case falls back to `ai_unavailable` with the deterministic finding intact. **The model never performs arithmetic** — every number in its explanation is a value the engine computed and passed in.

---

## 4. User stories

Each story carries acceptance criteria a test can assert.

### Epic A — Get data in

**A1.** As a *data ops engineer*, I want to upload a CSV and see exactly which rows were accepted and which were rejected and why, so that I never discover corruption three days later.
- *Given* a 5,000-row bank CSV with 12 malformed rows, *when* I upload it, *then* the import reports `accepted=4988, rejected=12`, and each rejection carries row number, column, raw value, and reason code.
- Raw file bytes and every raw row are stored before any parsing.
- Re-uploading the identical file with the same idempotency key creates **no** new records and returns the original import.

**A2.** As a *data ops engineer*, I want money parsed as exact decimals, so that ₹1,234.56 is never stored as 1234.5599999.
- Amounts arrive as strings, are parsed with `Decimal`, quantised to 2dp, stored as `123456` (BIGINT paise).
- A float amount on the wire is **rejected**, not coerced.
- A value that loses precision on quantisation is rejected with `AMOUNT_PRECISION_LOSS`.

**A3.** As a *data ops engineer*, I want duplicate rows detected on import, so that a re-run does not inflate revenue.
- `(source_system, external_id)` is unique. `row_hash` over the normalised payload is unique.
- A second row with the same natural key but different content is accepted **and** flagged `duplicate` for review — never silently dropped.

### Epic B — Reconcile

**B1.** As an *analyst*, I want to start a run over a date range and watch it progress, so that I know it is working and roughly when it will finish.
- Run row created `queued` → `running` → `completed` / `failed`, with `progress_pct` and `current_stage`.
- The UI polls and shows the stage; the request that started the run returns immediately.

**B2.** As an *analyst*, I want a settlement to reconcile end to end with its arithmetic shown, so that I can trust the clear.
- For a matched settlement the case shows the bridge: `Σ gross − refunds − fees − taxes ± adjustments = net`, each component tied to its source record.
- The bridge must balance to the paise, or the case is an `amount_mismatch` exception rather than a clear.

**B3.** As a *controller*, I want re-running the same input to be safe, so that I can rerun after a data fix without corrupting history.
- Re-running produces a **new** run; prior runs and their groups/cases are immutable.
- Given identical input and ruleset version, two runs produce identical group membership.

### Epic C — Investigate

**C1.** As an *analyst*, I want the exception queue sorted by financial risk, so that I work the expensive problems first.
- Default sort: `amount_at_risk_minor DESC`, tie-broken by `severity`, then `age`.
- Filters: status, severity, type, date range, source, assignee, amount band, confidence band.

**C2.** As an *analyst*, I want a case page showing the timeline, the amount bridge, the candidates considered, and why each was rejected, so that I can decide without opening another tool.
- Timeline renders payment → settlement → bank → ledger with actual dates.
- Every candidate considered is listed with its score and its rejection reason.
- Source records are viewable in raw form, one click away.

**C3.** As an *analyst*, I want a grounded AI explanation with its uncertainties stated, so that I get a head start without being misled.
- Requesting an investigation returns classification, ranked hypotheses with evidence IDs, recommended action, confidence, and an explicit `uncertainties` list.
- Every cited evidence ID resolves to a record in this case. If not, the response is rejected and the UI says the AI could not produce a grounded answer.
- The AI panel is visually separated from engine-computed facts and labelled as assistance.

### Epic D — Decide

**D1.** As a *reviewer*, I want to approve, reject, or override a proposed resolution with a reason code, so that the decision is defensible later.
- Override requires a reason code from a controlled list plus free text.
- Every decision writes a `decision_audit_event` with actor, role, ruleset version, model version, and the full before/after payload.

**D2.** As a *controller*, I want anything above the material threshold to require my approval regardless of confidence, so that large amounts are never auto-cleared.
- A case above `policy.review_required_above_minor` cannot be auto-resolved and cannot be approved by an `analyst`.

**D3.** As an *auditor*, I want the audit trail to be append-only, so that I can trust it.
- No API path updates or deletes an audit event. Enforced by a DB trigger, not only by convention.

### Epic E — Prove it works

**E1.** As a *controller*, I want held-out evaluation metrics, so that I know the system's real accuracy rather than its self-report.
- The generator writes ground-truth links. The eval harness computes precision, recall, F1, auto-resolution precision, false-clear rate, and coverage on a partition never used for tuning.
- Metrics render in the dashboard with the run and ruleset version they came from.

**E2.** As a *controller*, I want to export results, so that I can hand them to an accountant.
- CSV export per run: every record, its bucket, group, confidence, exception type, and resolution.

### Epic F — Access control

**F1.** As a *new user*, I want to register, verify my email, log in, and reset a forgotten password, so that the system is usable by a real team.
- Register → verification token → verify → login. Forgot-password → reset token → set new password.
- Passwords hashed with Argon2. Tokens single-use and expiring.

**F2.** As a *controller*, I want roles enforced server-side, so that an analyst cannot approve a material adjustment.
- Roles: `analyst`, `reviewer`, `controller`, `admin`, enforced as FastAPI route dependencies.
- The UI hides what the user cannot do; the API **rejects** it regardless of what the UI showed.

---

## 5. Requirements

### 5.1 Functional

| ID | Requirement |
|---|---|
| FR-1 | Ingest CSV and JSON for five source types via upload and via API, with a declared schema per source. |
| FR-2 | Persist raw file bytes plus each raw row payload before parsing; retain SHA-256 per file and per row. |
| FR-3 | Validate required fields, date parseability, currency validity, allowed status values, and amount format; quarantine failures with a reason code. |
| FR-4 | Normalise to `canonical_transactions`: paise integers, UTC instants, trimmed/case-normalised IDs (originals retained), controlled status vocabulary, extracted references. |
| FR-5 | Create versioned reconciliation runs scoped to a dataset snapshot and a ruleset version; expose status and progress. |
| FR-6 | Execute rules R1–R5 in order, first-match-wins, emitting evidence per rule fire. |
| FR-7 | Support 1:1, many:1, 1:many, and many:many groups with strict total validation. |
| FR-8 | Detect and classify the 8 exception types with severity and `amount_at_risk_minor`. |
| FR-9 | Compute composite confidence and apply the six-condition auto-resolve gate deterministically. |
| FR-10 | Build an evidence packet per case; call the model with only that packet; validate the JSON response against a schema; verify every cited evidence ID. |
| FR-11 | Provide approve / reject / override / assign / comment / resolve, with mandatory reason codes on override. |
| FR-12 | Write an append-only audit event for every mutation, including actor, role, ruleset version, model version, and payload. |
| FR-13 | Report totals, reconciliation rate, unresolved count and value, aging buckets, and held-out accuracy. |
| FR-14 | Export per-run results as CSV. |
| FR-15 | Full auth: register, email verification, login, JWT access + refresh, logout, forgot/reset password, and four-role RBAC. |

### 5.2 Non-functional

| ID | Requirement | How it is enforced |
|---|---|---|
| NFR-1 **Money** | No floating-point money anywhere. | `BIGINT` paise in DB; `int` in Python; Pydantic validator rejects `float` on the wire; a lint rule bans `float(` inside `packages/reconciliation`. |
| NFR-2 **Idempotency** | Re-processing identical input must not duplicate outcomes. | `Idempotency-Key` on POST; unique `(source_system, external_id)`; unique `row_hash`; runs are append-only versions. |
| NFR-3 **Explainability** | Every resolution shows the links and arithmetic supporting it. | A group cannot reach `resolved` without at least one `reconciliation_evidence` row. Enforced in the service layer, asserted in tests. |
| NFR-4 **Safety** | Auto-resolution is policy-gated by confidence, value, and type. | The six-condition gate in F7; gate inputs stored on the group for replay. |
| NFR-5 **Security** | Encrypted secrets, RBAC, PII masked in list views and in every model prompt. | Argon2 hashing; secrets from env; a `redact()` pass applied to every packet before it leaves the process, with a test asserting no unmasked PII in prompts. |
| NFR-6 **Auditability** | Append-only decision log. | DB trigger raising on `UPDATE`/`DELETE` of `decision_audit_events`. |
| NFR-7 **Performance** | 10,000 records reconciled in under 3 minutes with visible progress. | Bulk `COPY` ingestion, set-based SQL for R1–R5, indexed candidate windows, chunked progress checkpoints. |
| NFR-8 **Observability** | Structured JSON logs correlated by `run_id`; run metrics persisted. | `structlog`; a `run_metrics` row per run; validation failures queryable. |
| NFR-9 **Reliability** | A crashed run must not leave partial state visible as complete. | Each stage in a transaction; run status advances only on commit; failed runs marked `failed` with the stage recorded. |
| NFR-10 **Reproducibility** | Any decision reconstructible from source + ruleset version. | `ruleset_version` and `model_version` stamped on every group, case, and audit event. |

### 5.3 Policy configuration (values, not code)

| Key | Default | Meaning |
|---|---|---|
| `auto_resolve_min_confidence` | `0.95` | Floor for automatic clearing. |
| `auto_resolve_max_minor` | `5_000_000` (₹50,000) | Above this, a human decides regardless of confidence. |
| `review_required_above_minor` | `25_000_000` (₹2,50,000) | Above this, only `controller`/`admin` may approve. |
| `candidate_margin` | `0.05` | Required score gap to the runner-up candidate. |
| `settlement_window_days` | `3` | T+0…T+3 expected settlement window. |
| `amount_tolerance_minor` | `100` (₹1.00) | Absolute tolerance for rounding differences. |
| `never_auto_resolve` | `[duplicate, missing_bank_credit, amount_mismatch]` | Hard block list. *Chargebacks are not a separate exception type in the 8-value taxonomy — a case whose members include a `dispute` entity is blocked by the same rule via a member check.* |

---

## 6. Edge cases

These decide whether the demo survives a sceptical question. Each has a defined, tested behaviour.

### 6.1 Money and arithmetic

| Case | Behaviour |
|---|---|
| Amount with thousands separators (`1,23,456.78`) | Parse Indian and Western grouping; reject anything still ambiguous. Never `float()`. |
| More than 2 decimal places (`100.005`) | Reject with `AMOUNT_PRECISION_LOSS`. Do not round silently. |
| Negative amount where direction is also given | Reject as `AMBIGUOUS_SIGN` — sign must come from exactly one source. |
| Fee/tax rounding drift of ±1 paise across a batch | Allowed within `amount_tolerance_minor`; the tolerance consumed is **shown** in the bridge, never hidden. |
| Zero-amount payment | Valid record, excluded from matching, flagged `data_quality`. |
| Currency other than INR in a single-currency MVP | Ingested, excluded from matching, exception `unsupported_currency`. No FX conversion is attempted. |

### 6.2 Time

| Case | Behaviour |
|---|---|
| Naive timestamp with no timezone | Interpreted as `Asia/Kolkata`, converted to UTC, and the assumption recorded on the record. |
| Bank posts date-only, gateway posts an instant | Compare on business date in the configured timezone, never on raw UTC instants. |
| Settlement lands on a weekend or bank holiday | Window extended by the holiday calendar; if the calendar is absent, the case becomes `date_mismatch` for review rather than a clear. |
| Settlement outside T+3 but otherwise perfect | Matched, flagged `date_mismatch`, **not** auto-resolved. |
| A payment captured 23:58 IST settling "next day" | Business-date logic, not instant arithmetic. Explicitly in the fixture set. |

### 6.3 Ambiguity — the dangerous ones

| Case | Behaviour |
|---|---|
| Two payments, same amount, same day, one bank credit | R6 requires **no competing candidate**. Two candidates within `candidate_margin` → **unresolved**, both listed. This is the flagship abstention case. |
| Settlement references a payment never imported | `unmatched_payment` with `missing_source_data`; the case names the missing file. Never invent the record. |
| Bank narration truncated mid-reference (`UTR7739…`) | Prefix match allowed **only** with amount + date corroboration; alone it is never sufficient. |
| One payment plausibly fits two open invoices | Unresolved with both candidates ranked. No split is guessed. |
| Refund with no original payment in the dataset | `refund_unlinked`; never netted off a random payment. |

### 6.4 Duplicates and reruns

| Case | Behaviour |
|---|---|
| Identical file uploaded twice | Idempotency key returns the original import. Zero new rows. |
| Same file, different filename, identical content | Caught by file SHA-256; warns and returns the original import. |
| Same `payment_id`, different amount | Both retained; `duplicate` exception with `conflicting_values`. Requires a human. |
| Overlapping date ranges across two runs | Runs are independent snapshots; a record may appear in both. Metrics are always per-run, never summed across runs. |
| Ledger journal posted twice | `duplicate`; never auto-resolved (hard block list). |

### 6.5 Model failure

| Case | Behaviour |
|---|---|
| Model returns unparseable or schema-invalid JSON | One retry with a repair instruction, then `ai_unavailable`. The deterministic finding stands unchanged. |
| Model cites an evidence ID not in the packet | Response rejected outright. Logged as a grounding violation with the offending ID. |
| Model asserts a number the engine did not compute | Numeric assertions cross-checked against packet values; mismatch → rejected. |
| API timeout or rate limit | Exponential backoff, capped; the case remains fully usable without AI. |
| Model is confident, the gate says review | **The gate wins.** Model confidence is an input, never an override. Asserted by test. |

### 6.6 Ingestion and operations

| Case | Behaviour |
|---|---|
| CSV with BOM, CRLF, or `latin-1` encoding | Sniffed and handled; encoding recorded on the import. |
| Header row missing or reordered | Mapped by declared schema; unknown columns preserved in `raw_payload`; missing required columns fail the whole file, not row-by-row. |
| Empty file / header only | Import succeeds with `accepted=0` and a warning. Not an error. |
| File larger than the request limit | Rejected with a clear size message. *Hosted note: the platform request cap is lower than local — chunked upload is the Phase 3 answer.* |
| Run crashes mid-way | Marked `failed` with the stage; partial groups are not visible as `completed`. Rerun creates a fresh run. |
| Two runs started concurrently on the same snapshot | Advisory lock on `(snapshot_id, ruleset_version)`; the second is rejected with a pointer to the first. |

### 6.7 Auth

| Case | Behaviour |
|---|---|
| Unverified user tries to log in | Rejected with `EMAIL_NOT_VERIFIED`. |
| Expired access token, valid refresh cookie | Silent refresh; the original request retried once. |
| Analyst calls the approve endpoint directly | `403`. The UI hiding the button is a convenience, not the control. |
| Reset token reused | Rejected; tokens are single-use. |
| Logout | Refresh cookie cleared server-side and client-side; access token allowed to expire. |

---

## 7. MVP scope

### 7.1 In scope — the four-day build

**Day 1 — foundation and data**
Repo scaffold, Docker Compose, Alembic migrations, canonical schema, **synthetic data generator with ground truth**, CSV ingestion, validation, normalisation, imports API. *Ship the generator on day 1 — every later day depends on having data with known answers.*

**Day 2 — the engine**
Run orchestration with progress, rules R1–R5, group and link persistence, settlement bridge arithmetic, exception detection across all 8 types, confidence computation, the auto-resolve gate, run metrics.

**Day 3 — the product**
Auth (`fastapi-users` + four roles) and the Next.js dashboard: upload, run status, executive overview, exceptions queue, case detail with timeline + bridge + candidates, reviewer controls, audit history.

**Day 4 — the differentiator**
Grounded AI investigation with schema validation and citation verification, held-out evaluation harness, CSV export, deploy to Render + Vercel, demo rehearsal against the five-minute narrative.

### 7.2 Out of scope — stated, not forgotten

| Excluded | Why |
|---|---|
| Moving money, creating payouts, writing to a real accounting system | Blueprint non-goal. The system proposes; it never executes financially. |
| Live Razorpay API integration | Cannot be tested honestly in the window. Synthetic data with ground truth is the stronger demo because it is *measurable*. |
| Multi-currency and FX | Non-INR is ingested and flagged, never converted. |
| Learned ranking model | Needs reviewer feedback data that does not exist yet. Phase 3. |
| Multi-entity accounting, period-close controls, SLA escalation | Phase 3. |
| Real-time streaming ingestion | Batch is the correct model for reconciliation. |
| Mobile layout | Desktop-first; this is a workstation tool. |

### 7.3 The cut list — in order, if day 3 runs late

1. **R6/R7 fuzzy candidate scoring** → those records land in `unresolved` with candidates listed. *Costs coverage, costs zero precision. Cut this first.*
2. **Reconciliation explorer (F12)** → the case page already shows the same graph for one case.
3. **Invoice and ledger matching (R4/R5)** → keep ingestion and display, drop the matching. The payment→settlement→bank chain is the core story.
4. **Playwright E2E** → keep the matching-engine unit tests and the eval harness. Those are what the metrics claim rests on.

**Never cut:** the evidence packet, the auto-resolve gate, the audit trail, the held-out metrics. Those four *are* the submission.

### 7.4 Definition of done

The MVP is done when, on a held-out partition the tuning never saw, LedgerGraph can:

1. ingest all five sources and report exactly what it rejected and why;
2. reconcile the clean majority with a visible amount bridge and traceable evidence;
3. surface every injected anomaly as a classified exception rather than hiding it;
4. abstain — with both candidates shown — on the same-amount-same-day ambiguity;
5. report precision, recall, auto-resolution precision, and **false-clear rate** with the numbers on screen;
6. show a grounded AI explanation whose every citation resolves to a record in the case;
7. record an approve/override with a reason code in an append-only trail;
8. export the run and explain each decision in plain language.

### 7.5 Success metrics for the demo

| Metric | Target | Why this number |
|---|---|---|
| Auto-resolution precision | **≥ 0.99** | The headline. One false clear discredits the whole system. |
| False-clear rate on injected material exceptions | **0** | Non-negotiable. This is the safety claim. |
| Match precision | ≥ 0.98 | |
| Match recall | ≥ 0.85 | Deliberately below precision. Abstention is the design. |
| Coverage (auto-resolved + correctly routed) | ≥ 0.90 | Proves abstention is not just refusing to work. |
| Exception classification accuracy | ≥ 0.85 | |
| Throughput | ≥ 10,000 records / 3 min | |

**Lead the pitch with the false-clear rate,** because it is the one metric where a competitor optimising for match rate looks worse the harder they try.

---

## 8. Open questions

Genuinely undecided — each with a working assumption so the build is never blocked.

| # | Question | Working assumption |
|---|---|---|
| Q1 | Is a bank holiday calendar available for the settlement window? | Assume weekends only. Holiday dates become a config list if time allows. |
| Q2 | What is the real gateway fee schedule (flat %, per-method, slabs)? | Assume 2% + 18% GST on the fee, with a per-method override table. The generator uses it; the engine reads it from config, never hardcoded. |
| Q3 | Can a single payment be partially settled? | Assume no in the MVP. If encountered, `amount_mismatch` for review. |
| Q4 | Should `unresolved` age into an escalation? | Assume no automatic escalation; aging is displayed, not acted on. |
| Q5 | Is email delivery available for verification tokens on the hosted deploy? | Console/log delivery locally; on the hosted deploy, log the token and surface it to `admin`. A real SMTP provider is a config swap. |
