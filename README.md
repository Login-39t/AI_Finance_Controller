# LedgerGraph

**AI-assisted financial reconciliation and exception investigation.**
Razorpay Hackathon — Track 4: AI Finance Controller.

Connects payments, Razorpay settlements, bank statements, invoices, and internal ledgers; matches records deterministically; explains discrepancies with grounded evidence; and routes genuinely uncertain cases to a human.

> **Core principle:** trusted because it can show its work. Deterministic code owns every number. The AI makes investigations clearer and faster — never less accountable.

---

## Repository layout

```text
ledgergraph/
├── backend/       FastAPI service      · Python 3.11 · Postgres 16
├── frontend/      Next.js 15 dashboard · TypeScript · Tailwind v4
├── packages/      Framework-free domain and engine code
│   └── domain/    money.py, enums, canonical model, normalisers
├── data/synthetic/ Generator + anomaly injector → CSVs + ground truth
├── db/            schema.sql (source of truth) and seeds
├── docs/          PRD, tech stack, architecture, database, UI flows
└── tests/         unit · integration · evaluation
```

**One rule worth enforcing in CI:** nothing in `packages/` may import from `backend/` or `frontend/`. That is what lets the evaluation harness run the real matching engine without booting an HTTP server, which is what keeps the held-out metrics honest.

---

## Running it

```bash
make install
```

Then two terminals:

```bash
make api
```

```bash
make web
```

API on `:8000` (`/docs` for the browsable OpenAPI), frontend on `:3000`.

Tests:

```bash
make test
```

Synthetic dataset (no database needed — see [`data/synthetic/README.md`](data/synthetic/README.md)):

```bash
make gen-data
```

### You need a Postgres

There is no Docker on this machine and the schema depends on Postgres-specific features — enums, `JSONB`, partial indexes, constraint triggers — so SQLite is not a fallback. A free Neon project is the fastest unblock and doubles as the hosted database. Put the URL in `.env` as `DATABASE_URL`, then:

```bash
make migrate
```

Until then `/healthz` returns 200 and `/readyz` returns 503 naming the database as the reason, which is the correct behaviour rather than a failure to boot.

---

## Current state

| Piece | Status |
|---|---|
| Design docs (5) + `db/schema.sql` | Written |
| `packages/domain/money.py` | **No float path in or out** |
| `packages/domain/` — enums, canonical model, 6 normalisers | **Enums verified against `schema.sql`; all 714 generated rows normalise** |
| `backend/` — app factory, config, DB session, health, problem+json errors | **Runs on :8000** |
| `backend/alembic/` — migration 0001 applies `db/schema.sql` | Written, **never executed** (no Postgres yet) |
| `frontend/` — exceptions queue, case detail | **Builds; verified in light and dark** |
| `data/synthetic/` — generator + 12-type anomaly injector | **Deterministic; every anomaly type verified to fire** |
| `packages/reconciliation/` — rules R1–R6, bridge, 8 detectors, the gate | **Runs; false-clear rate 0.0000 on holdout** |
| `tests/evaluation/` — held-out metrics vs ground truth | **`make eval`** |
| Auth, imports, runs, AI investigation | Not built |

**205 tests passing**, lint clean.

### Held-out evaluation (`make eval`)

| Metric | Holdout | Target |
|---|---|---|
| **False-clear rate** | **0.0000** | 0 |
| Auto-resolution precision | 1.0000 | ≥ 0.99 |
| Match precision | 1.0000 | ≥ 0.98 |
| Match recall | 1.0000 | ≥ 0.85 |
| Coverage | 0.7421 | ≥ 0.70 |
| Anomaly detection | 11 of 11 types at 100% | — |

3,571 transactions in ~10ms. The holdout partition is separated by a hash of the truth id, not by call order, so a rule change cannot move a record between partitions.

The frontend currently reads `frontend/src/fixtures/cases.ts`, not the API. That file is deleted the moment `GET /v1/exceptions` exists.

`data/synthetic/out/` is gitignored — regenerate with `make gen-data`. At the default scale (1200 payments, 30-day lookback): 22 settlement batches, 971 lines, 991 ground-truth links (805 tuning / 186 holdout), and every one of the twelve labeled anomaly types fires at least once — a regression that previously let five types silently produce zero instances is now a named test (`test_every_anomaly_type_fires_at_least_once`).

---

## The build in four days

| Day | Focus | Ships |
|---|---|---|
| 1 | Foundation | Money type · schema · synthetic generator with ground truth · ingestion · walking-skeleton deploy |
| 2 | The engine | Run orchestration · rules R1–R5 · amount bridge · 8 exception detectors · confidence · the auto-resolve gate |
| 3 | The product | Full auth + RBAC · exceptions queue · case detail · decision workflow · audit trail |
| 4 | The differentiator | Grounded AI investigation with citation verification · held-out evaluation metrics · export · hosted deploy |

**Never cut:** the evidence packet, the auto-resolve gate, the audit trail, the held-out metrics. Those four *are* the submission.

---

## Design documents

| # | Document | Covers |
|---|---|---|
| — | [Project blueprint](LedgerGraph-Track-4-Project-Blueprint.md) | The original problem brief |
| 1 | [PRD](docs/01-PRD.md) | Problem · users · features · user stories · requirements · edge cases · MVP scope |
| 2 | [Tech stack](docs/02-tech-stack.md) | Every layer, with the reasoning and the rejected alternatives |
| 3 | [Architecture](docs/03-architecture.md) | Structure · flows · auth · data flow · security and performance risks |
| 4 | [Database design](docs/04-database-design.md) | Tables · keys · constraints · indexes, and why each exists |
| — | [`db/schema.sql`](db/schema.sql) | Complete PostgreSQL 16 DDL |
| 5 | [UI/UX flowcharts](docs/05-ui-ux-flowcharts.md) | Every screen, function, and state machine, in build order |

---

## The claim worth leading with

Most reconciliation systems optimise for match rate. This one optimises for **false-clear rate** — the number of problematic records it wrongly declares fine. The target is zero, measured on a held-out partition the tuning never saw.

Two pieces of deterministic code carry that claim:

- **the auto-resolve gate** (`packages/reconciliation/policy.py`) — six conditions, all of which must hold; the model's confidence is an input and never an override;
- **the grounding verifier** (`packages/ai_investigation/verify.py`) — every citation must resolve to a record in the case, and every number must be one the engine computed.

Roughly 160 lines between them. Neither is written yet.
