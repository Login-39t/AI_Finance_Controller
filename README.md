# TallyProof

**AI-assisted financial reconciliation and exception investigation.**
Razorpay Hackathon — Track 4: AI Finance Controller.

Connects payments, Razorpay settlements, bank statements, invoices, and internal ledgers; matches records deterministically; explains discrepancies with grounded evidence; and routes genuinely uncertain cases to a human.

> **Core principle:** trusted because it can show its work. Deterministic code owns every number. The AI makes investigations clearer and faster — never less accountable.

---

## Live demo

| | URL |
|---|---|
| **App** (Next.js on Vercel) | **https://ai-finance-controller-seven.vercel.app** |
| API (FastAPI + Postgres on Render) | https://ledgergraph-api.onrender.com — [`/docs`](https://ledgergraph-api.onrender.com/docs) · [`/healthz`](https://ledgergraph-api.onrender.com/healthz) |

Grounded AI investigation (Groq) is enabled, so the **Investigate** button on
any case makes a live, citation-verified model call.

> **Free-tier notes.** The API sleeps after ~15 minutes idle; the first
> request wakes it in ~30–50s (open `/healthz` once to warm it up before a
> demo). A redeploy restarts the process and clears the in-memory run cache,
> so start one reconciliation afterwards to repopulate the queue — the data
> stays in Postgres. See [deployment](docs/06-deployment.md) for the full setup.

**Signing in.** *Create an account* on the login page self-registers an
analyst — enough to import, run a reconciliation, and investigate a case.
Reviewer, controller, and admin are granted by an admin from the **Users**
page. Where the deploy is seeded (`SEED_DEMO_USERS=true`), one account per
role is listed on the login page under **Role accounts**, sharing the
password `tallyproof-demo-2026`, so each role can be seen from the inside
without provisioning anyone.

---

## Repository layout

```text
tallyproof/
├── backend/       FastAPI service      · Python 3.11 · Postgres 16
├── frontend/      Next.js 15 dashboard · TypeScript · Tailwind v4
├── packages/      Framework-free domain and engine code
│   ├── domain/         money.py, enums, canonical model, normalisers
│   ├── reconciliation/ rules, bridge, detectors, the auto-resolve gate
│   └── ai_investigation/ packet, redaction, schema, grounding verifier
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

### The schema is verified, but it has never been executed

No Postgres and no Docker have been reachable from this machine, so `db/schema.sql` has never run. Rather than leave it unchecked, it is parsed with `pglast` — which wraps **libpg_query, PostgreSQL's own parser** lifted out of the server — and then cross-checked for the errors that parse fine and fail at `CREATE`: foreign keys pointing at columns that do not exist, columns typed with an undeclared enum, indexes on missing columns, triggers calling undefined functions, and any floating-point column anywhere near money.

Those checks were themselves verified by mutation: six defects injected into a copy of the schema, six caught (`tests/unit/test_schema_sql.py`). That narrows the gap. It does not close it — `make migrate` is still the first real test.

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
| `frontend/` — queue, case detail, imports, runs | **On live API data; verified in light and dark** |
| `data/synthetic/` — generator + 12-type anomaly injector | **Deterministic; every anomaly type verified to fire** |
| `packages/reconciliation/` — rules R1–R6, bridge, 8 detectors, the gate | **Runs; false-clear rate 0.0000 on holdout** |
| `tests/evaluation/` — held-out metrics vs ground truth | **`make eval`** |
| `packages/ai_investigation/` — packet, redaction, schema, grounding verifier | **Runs; adversarially tested without an API key** |
| API — imports, runs, exceptions, investigate, reports, exports | **24 endpoints; full flow verified over HTTP** |
| Frontend wired to the live API | **Fixtures deleted; queue, case detail, imports, runs all live** |
| Auth + RBAC | **Argon2id, rotating refresh tokens with reuse detection, four roles; every domain endpoint refuses an anonymous caller** |
| Decision workflow | **`POST /v1/exceptions/{id}/decision` with role + materiality + reason-code checks, and an audit event** |
| Overview dashboard, reconciliation explorer | **Live; the explorer shows auto-resolved groups, not only failures** |
| Reports and CSV exports | **Exceptions, matches, audit trail — exact amounts, no float in the path** |
| Deploy — Dockerfiles, `render.yaml`, `docker-compose.yml` | Written; see [deployment](docs/06-deployment.md) |
| Postgres `Repository` implementation | Written against the real schema; **reviewed and unexercised** — see below |
| `db/schema.sql` executed | **Never** — no Postgres reachable from this machine. Verified statically instead (below). |

**381 tests passing**, lint clean.

### The critical path, live

```
POST /v1/auth/login            controller@tallyproof.dev -> access token + refresh cookie
POST /v1/imports          x6   3,571 rows accepted, 0 rejected
POST /v1/reconciliation-runs   202 queued -> poll -> completed
GET  /v1/exceptions            143 cases, sorted by money at risk
GET  /v1/exceptions/{id}       packet: records, evidence, all 6 gate conditions
POST /v1/exceptions/{id}/decision
```

### The RBAC boundary, live

Four demo accounts exist locally, one per role (password `tallyproof-demo-2026`; the API refuses to create them when `ENVIRONMENT=production`). Every line below is a real response from the running API:

| Caller | Case | Result |
|---|---|---|
| analyst | Rs 1,50,000 | `403 INSUFFICIENT_ROLE` — an analyst reads and investigates |
| reviewer | Rs 3,54,165 | `403 CONTROLLER_APPROVAL_REQUIRED` — above the Rs 2,50,000 threshold |
| controller | override, no reason code | `422 REASON_CODE_REQUIRED` |
| controller | override + reason code | `200` — audit event names Chitra Controller, controller, `evidence_insufficient` |
| controller | the same case again | `409 ALREADY_DECIDED` — the first verdict is never silently replaced |
| reviewer | Rs 1,50,000 | `200` |

A stolen refresh token is usable **once**. Replaying a consumed one returns `401 REFRESH_REUSED` and revokes the entire family, so the legitimate successor dies too — everyone re-authenticates, which is the correct response to a token you cannot distinguish from a copy.

### Persistence: two implementations, one protocol

`PERSISTENCE=memory` (the default) runs the whole API without a database. `PERSISTENCE=postgres` installs `store_postgres.py` instead. The choice is explicit rather than "Postgres if the URL happens to connect": auto-detection would let a blip at boot silently downgrade a deployment to a store that accepts every write and loses it. `config.py` refuses `memory` when `ENVIRONMENT=production`.

The in-memory store has no durability, no concurrent writers, and none of the schema's constraints or triggers. It is correct for development and wrong for a deployment.

**The Postgres implementation has never run against a server**, because none has been reachable. What has been checked without one: every table and column it names exists in `db/schema.sql` (parsed with libpg_query), every statement it builds compiles against the PostgreSQL dialect, and it satisfies the `Repository` protocol with matching signatures — all six of those checks confirmed by mutation. That catches renamed columns and missing methods. It does not catch a wrong join or a constraint violation. Reviewed and unexercised, not working.

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

`data/synthetic/out/` is gitignored — regenerate with `make gen-data`. At the default scale (1200 payments, 30-day lookback): 22 settlement batches, 971 lines, 991 ground-truth links (805 tuning / 186 holdout), and every one of the twelve labeled anomaly types fires at least once — a regression that previously let five types silently produce zero instances is now a named test (`test_every_anomaly_type_fires_at_least_once`).

---

## Design documents

| # | Document | Covers |
|---|---|---|
| — | [Project blueprint](TallyProof-Track-4-Project-Blueprint.md) | The original problem brief |
| 1 | [PRD](docs/01-PRD.md) | Problem · users · features · user stories · requirements · edge cases · MVP scope |
| 2 | [Tech stack](docs/02-tech-stack.md) | Every layer, with the reasoning and the rejected alternatives |
| 3 | [Architecture](docs/03-architecture.md) | Structure · flows · auth · data flow · security and performance risks |
| 4 | [Database design](docs/04-database-design.md) | Tables · keys · constraints · indexes, and why each exists |
| — | [`db/schema.sql`](db/schema.sql) | Complete PostgreSQL 16 DDL |
| 5 | [UI/UX flowcharts](docs/05-ui-ux-flowcharts.md) | Every screen, function, and state machine, in build order |
| 6 | [Deployment](docs/06-deployment.md) | Local without Docker · compose · Render + Vercel, and what is still unproven |

---

## The claim worth leading with

Most reconciliation systems optimise for match rate. This one optimises for **false-clear rate** — the number of problematic records it wrongly declares fine. The target is zero, measured on a held-out partition the tuning never saw.

Two pieces of deterministic code carry that claim:

- **the auto-resolve gate** (`packages/reconciliation/policy.py`) — six conditions, all of which must hold; the model's confidence is an input and never an override;
- **the grounding verifier** (`packages/ai_investigation/verify.py`) — every citation must resolve to a record in the case, and every number must be one the engine computed.

Both are now written and tested. The gate holds the false-clear rate at zero on held-out data; the verifier rejects any response citing evidence outside its case or asserting a number the engine did not compute.

The AI layer is testable without an API key, because nothing that decides whether an answer is trustworthy involves a network call. `FakeProvider` exercises every path: schema violations, invented citations, invented arithmetic, provider timeouts, and the single repair retry.
