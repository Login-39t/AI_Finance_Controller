# TallyProof — Tech Stack

**Input** `docs/01-PRD.md` · **Constraints** solo, 2–4 days, Python/FastAPI backend, full auth, runs locally *and* deployed.

Every choice below is scored against three things, in this order:

1. **Simplicity** — can one person stand it up, debug it at 2am, and demo it without a surprise?
2. **Security** — does it make the correct thing the default?
3. **Scalability** — does it survive being right, without paying for that today?

A fourth filter runs underneath all three: **does it help the system show its work?** That is the product's whole claim, and it eliminates several otherwise-reasonable options.

---

## 0. The stack at a glance

| Layer | Choice | Version | Why in one line |
|---|---|---|---|
| Frontend | **Next.js (App Router) + TypeScript** | 15.x | Server components for the data-heavy tables, one deploy target, generated API types. |
| Styling | **Tailwind CSS + shadcn/ui** | 4.x | Dense financial tables need utility CSS; shadcn gives accessible primitives you own outright. |
| Data fetching | **TanStack Query** | 5.x | Polling a run's progress and cache invalidation after a decision are its two core competencies. |
| Charts | **Recharts** | 2.x | Four charts, React-native, no imperative canvas layer to fight. |
| Backend | **FastAPI + Pydantic v2** | 0.115+ / 2.x | Validation *is* the product; Pydantic makes the ingestion contract executable, and OpenAPI comes free. |
| ORM / migrations | **SQLAlchemy 2.0 + Alembic** | 2.0 / 1.13 | Typed Core for set-based matching SQL, ORM for CRUD, versioned migrations from day 1. |
| Database | **PostgreSQL** | 16 | `NUMERIC`/`BIGINT` exactness, `JSONB` for raw payloads, CTEs and window functions for matching, real constraints. |
| Raw file storage | **Postgres `bytea`** (behind an `ObjectStore` interface) | — | Deletes an entire subsystem from the 4-day build; transactional with the import row. S3 is a one-class swap. |
| Background work | **FastAPI `BackgroundTasks`** + DB-persisted run state | — | Zero infra. ARQ + Redis is a documented one-file upgrade. |
| Matching | **Pure Python + SQLAlchemy Core + Polars** | Polars 1.x | Deterministic rules as set-based SQL; Polars only for the generator and eval harness. |
| Auth | Argon2id (`argon2-cffi`) + JWT access (`PyJWT`) + rotating httpOnly refresh cookie | — | **Built, deviating from the `fastapi-users` choice below.** Every dangerous primitive still comes from a library; only the glue is ours. |
| AI | **Provider-neutral**, schema-constrained JSON. Default `gemini-3.6-flash` | — | The architecture distrusts the model, so provider is config. Free tiers suffice; Bedrock is not free. Pin the model — Google retires them, and a retired one answers 404 rather than degrading. |
| Testing | **pytest + httpx + testcontainers**, Vitest, Playwright | — | Golden-file rule tests and the eval harness are the credibility of the whole submission. |
| Local deploy | **Docker Compose** | — | `docker compose up` → Postgres + API + web. Two services, one command. |
| Hosted deploy | **Render (API + Postgres) + Vercel (web)** | — | `render.yaml` is infrastructure-as-code; Vercel is Next.js's home turf. Same Dockerfile both ways. |
| Observability | **structlog** + Sentry (optional) | — | JSON logs correlated by `run_id`; every rule fire traceable. |

---

## 1. Frontend — Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui

### Why Next.js and not plain Vite + React

Three things decide it:

1. **The heavy screens are read-mostly tables.** The exceptions queue and the reconciliation explorer render thousands of rows with server-side filters and sorts. React Server Components let the filter/sort/paginate round-trip stay on the server and ship only rendered rows — no client-side dataset, no memory ceiling on a laptop demo.
2. **Route handlers give you an escape hatch you will need.** Streaming a CSV export, or proxying an upload that must not pass through the client, is a five-line route handler. With Vite you would add an extra server.
3. **Vercel deployment is a git push.** You asked for a hosted version; this removes an entire afternoon of build config from a four-day budget.

**The honest cost:** the App Router's server/client boundary is a real learning tax if you have not used it. If that lands as friction on day 3, the escape is cheap — mark the dashboard pages `"use client"` and fetch through TanStack Query. You lose the server-rendered table but nothing else, and no other decision in this document changes.

### Why TypeScript, non-negotiably

The API returns money as **strings of paise** (`"1234500"`), never numbers. TypeScript is what stops `amount * 1.18` from ever being written in a component — the value is a `string`, and the compiler rejects the multiplication. In a system whose central claim is arithmetic correctness, the frontend must be unable to do arithmetic on money by accident.

Types are generated from the backend's OpenAPI schema (`openapi-typescript`), so a backend field rename breaks the frontend build rather than a demo.

### Why Tailwind + shadcn/ui and not a component library

MUI or Ant Design ship a design system you then fight. Financial tables need dense, custom, mono-spaced numeric alignment and a colour language for confidence bands that no library ships. shadcn/ui gives accessible Radix primitives (dialog, dropdown, tooltip, tabs) **as source files in your repo** — you own them, you restyle them, there is no theme override cascade. Tailwind handles the density.

### Why TanStack Query

Two problems it solves for free that are annoying by hand: polling `GET /v1/reconciliation-runs/{id}` until status is terminal (with backoff and automatic stop), and invalidating the queue cache after a decision so the row disappears without a full refetch.

### Rejected

| Option | Why not |
|---|---|
| **Streamlit / Gradio** | Fastest to a demo, and it would cap the ceiling exactly where the judging happens. The case-detail page — timeline, bridge, candidates, reviewer controls — is the product. Streamlit cannot make that feel like a finance tool. |
| **Vite + React SPA** | Viable. Loses server-side table rendering and adds hosting work. Keep as the fallback if App Router friction appears. |
| **Server-rendered Jinja from FastAPI** | Fewer moving parts, but the interactive queue and case page would become a pile of HTMX. Slower by day 3, not faster. |

---

## 2. Backend — FastAPI + Pydantic v2

### Why FastAPI

You chose Python, and among Python frameworks FastAPI is the one whose core abstraction matches this product's core requirement.

**Validation is the feature, not the plumbing.** FR-3 says reject malformed rows with a reason code. In FastAPI, the ingestion contract is a Pydantic model, and a rejection is a structured `ValidationError` with field path, input value, and error type — which is exactly the shape of the per-row rejection report A1 demands. In Django or Flask you would build that reporting layer yourself.

**The money validator lives in one place.** A single `MinorUnitAmount` Pydantic type — rejects `float`, parses `Decimal`, quantises to 2dp, refuses precision loss, returns `int` paise — is then reused by every source schema, every API request, and every test. NFR-1 becomes a type rather than a code review convention.

**OpenAPI is generated, not maintained.** The frontend's types come from it. The API sketch in the blueprint becomes an executable, browsable contract at `/docs` on day 1 — which is also a genuinely good thing to show a judge.

**Dependency injection is how RBAC gets enforced.** `Depends(require_role("controller"))` on a route is one line, testable in isolation, and impossible to forget in a way that silently passes.

### Why Pydantic v2 specifically

v2's Rust core is 5–20× faster than v1 on the validation path, and ingestion validates every row of every file. On a 10,000-row import that difference is the gap between a demo that feels instant and one that doesn't.

### Why SQLAlchemy 2.0 Core for the matching engine, ORM for everything else

This is the one place to be deliberate. The deterministic rules R1–R5 are **set operations over the whole run**, not per-record loops:

```sql
-- R1, conceptually: every payment that has an exact settlement line, in one statement
INSERT INTO reconciliation_links (...)
SELECT ... FROM canonical_transactions p
JOIN canonical_transactions s
  ON s.parent_external_id = p.external_id
WHERE p.entity_type = 'payment' AND s.entity_type = 'settlement_line' ...
```

Written as an ORM loop over 10,000 payments this is 10,000 round-trips and blows NFR-7. Written as SQLAlchemy Core it is one statement, and Postgres does what Postgres is good at. So: **Core for the engine, ORM for CRUD.** Use `select()` with typed models everywhere so you get autocomplete without the N+1.

### Why Polars only at the edges

Polars is superb for the **synthetic data generator** and the **evaluation harness**, which are genuinely dataframe-shaped: generate 10,000 rows, inject anomalies, join predictions against ground truth, compute precision/recall. It is the wrong tool inside the engine, where every match must emit an auditable evidence row tied to a database identity. A dataframe join produces a result; it does not produce a *reason*. Since NFR-3 requires the reason, the engine stays in SQL.

*(If you would rather not add a dependency: pandas does the generator and eval fine at this scale. Polars is a preference, not a requirement.)*

### Why background tasks and not Celery/ARQ+Redis on day 1

A reconciliation run must not block an HTTP request, so it needs to be asynchronous — but "asynchronous" and "distributed queue" are different requirements, and only the first is real here.

FastAPI's `BackgroundTasks` runs the job in the same process after the response is sent. Run state — `status`, `current_stage`, `progress_pct`, `error` — lives in the `reconciliation_runs` table, which the UI polls. That gives you the entire user-visible behaviour of a job queue with **zero added infrastructure**: no Redis container, no worker service, no second deploy target, no serialisation boundary to debug at midnight on day 3.

**What you give up, stated plainly:** an API restart mid-run loses that run. The mitigations are that runs are minutes not hours, and that a lost run is marked `failed` and simply re-run — which is safe because runs are already idempotent and versioned (NFR-2). On the hosted deploy this matters more, because a free instance can spin down; run the API on a paid always-on instance for the demo, or accept the re-run.

**The upgrade path is deliberately one file.** The engine entry point is `RunExecutor.execute(run_id)` — a pure function of a run ID. Swapping `BackgroundTasks` for ARQ means changing who calls it, not what it does. Redis is pre-written in `docker-compose.yml`, commented out.

### Rejected

| Option | Why not |
|---|---|
| **Django + DRF** | The admin and the batteries are real assets, but the ORM fights set-based matching SQL, and DRF serialisers are a weaker fit for per-row rejection reporting than Pydantic. Heavier for a 4-day build. |
| **Litestar** | Genuinely good, arguably cleaner DI. Smaller ecosystem, and `fastapi-users` has no equivalent — you would hand-roll auth, which is the day you were trying not to spend. |
| **Node/NestJS** | You chose Python, and correctly: the generator, the eval harness, and `Decimal` handling are all better in Python. |
| **Celery on day 1** | Redis + worker + Flower for a job that takes 90 seconds. Infrastructure spent on a problem you do not have yet. |

---

### Deviation, stated: `fastapi-users` was not used

The table above originally named `fastapi-users`, and the reasoning behind that choice — do not hand-roll auth — still holds. Two concrete facts changed the answer during the build, and both are recorded here rather than quietly:

1. **It needs a persistence adapter, and there is no database yet.** `fastapi-users` binds to SQLAlchemy or Beanie. With the repository still in-memory, using it would have meant writing a custom adapter that gets deleted the day Postgres lands.
2. **It ships no refresh-token rotation.** Rotation with reuse detection is the property architecture risk R5 actually cares about: it turns a stolen refresh token from indefinitely usable into usable once, after which the theft announces itself and the whole family is revoked. That would have had to be built on top regardless.

What was *not* hand-rolled: Argon2id hashing comes from `argon2-cffi` at library defaults, and JWT signing and verification from `PyJWT` with an explicit algorithm list. The code in `backend/src/ledgergraph_api/auth.py` is the glue between those and the repository — the part that has to know this system's rules.

The endpoint shapes match what `fastapi-users` produces (`/register`, `/login`, `/refresh`, `/logout`, `/me`), so adopting it for verification and password reset once Postgres exists is a wiring change, not a client rewrite.

---

## 3. Database — PostgreSQL 16

Not a close call. Four properties are load-bearing:

**Exact numerics.** `BIGINT` paise for all money, with `NUMERIC(20,4)` available for intermediate fee/tax computation. No float type touches money. SQLite's dynamic typing would let a float in.

**`JSONB` for `raw_payload`.** FR-2 requires storing every source row unchanged. `JSONB` stores it, indexes it with GIN, and lets you query into it during investigation without a second store.

**Real constraints as the last line of defence.** `UNIQUE(source_system, external_id)`, `UNIQUE(row_hash)`, `CHECK (net_amount_minor = gross_amount_minor - fee_amount_minor - tax_amount_minor)`, and `EXCLUDE` constraints for group membership conflicts. These enforce NFR-1 and NFR-2 **in the database**, so a bug in the service layer cannot corrupt the ledger. In a financial system, constraints belong where they cannot be bypassed.

**CTEs and window functions.** Candidate generation with a bounded date window, ranking by score, and detecting "is there a competing candidate within 0.05" (F7's margin condition) are each one window function. This is the query that makes abstention possible, and it is a `RANK() OVER (PARTITION BY ...)`.

Plus: **triggers** make the audit log append-only (NFR-6) at the storage layer, not by convention. **Advisory locks** implement the concurrent-run guard (§6.6). **Transactional DDL** makes Alembic migrations safe to run against the demo database.

### Why not SQLite, even though the blueprint permits it

The blueprint says SQLite is sufficient for the MVP. It is not, for three specific reasons: dynamic typing weakens the money guarantee that is this product's headline; there is no `JSONB` with proper indexing; and the hosted deployment needs a real network database anyway. Since you need Postgres for the deploy, running it locally in Compose costs nothing and eliminates a dev/prod divergence class.

### Raw file storage: Postgres `bytea`, behind an interface

The blueprint suggests S3-compatible object storage. For this build, store the raw file bytes in a `bytea` column on `source_files`.

**Why:** it removes MinIO from Compose, removes a bucket and credentials from the hosted deploy, and — the real reason — makes the file and its import row **transactionally consistent**. FR-2 says preserve the raw file *before* parsing; with `bytea` that is one transaction, with no orphaned-object failure mode.

**The ceiling, stated honestly:** this is correct up to roughly 20–30 MB per file. The hackathon dataset is 1–3 MB per source. Beyond that, `bytea` bloats the table and slows backups.

**So it goes behind an interface** — `ObjectStore.put(key, bytes) -> uri` / `.get(uri) -> bytes` — with `PostgresObjectStore` today and `S3ObjectStore` as a 40-line class when a file gets large. The rest of the codebase never knows which one is wired in.

---

## 4. Authentication — fastapi-users + Argon2 + JWT/refresh-cookie

You asked for a full auth stack. Hand-rolling it costs about a day; `fastapi-users` costs about three hours and is better than what you would write under time pressure.

### What it gives you as mounted routers

`register` · `verify` (email token) · `login` · `logout` · `forgot-password` · `reset-password` · `users/me` · JWT issuance and validation · pluggable password hashing.

That is FR-15 almost entirely, with token expiry, single-use tokens, and timing-safe comparison already correct — the parts of auth that are quietly easy to get wrong.

### What you add

**Argon2id, not bcrypt.** Set `password_hash` to Argon2id (`argon2-cffi`). It is the current password-hashing recommendation and has no 72-byte truncation trap.

**The `role` column and four dependencies.** `fastapi-users` ships `is_superuser` only. Add `role AS ENUM('analyst','reviewer','controller','admin')` to the user table and one dependency factory:

```python
def require_role(*allowed: Role):
    def dep(user: User = Depends(current_active_user)) -> User:
        if user.role not in allowed:
            raise HTTPException(403, "insufficient_role")
        return user
    return dep
```

Then `Depends(require_role(Role.controller, Role.admin))` on the approve route. **This is the enforcement point** — story F2 is explicit that the UI hiding a button is not a control.

**The material-amount rule is checked in the service, not the route,** because it depends on the case's amount, not just the caller's role: a `reviewer` may approve a ₹4,000 case and must not approve a ₹4,00,000 one. Route-level RBAC plus a service-level amount check together satisfy D2.

### Token strategy

- **Access token:** JWT, 15-minute lifetime, sent as `Authorization: Bearer`, held in memory by the frontend — never in `localStorage`, which is XSS-readable.
- **Refresh token:** opaque, 7-day, stored **hashed** in a `refresh_tokens` table, delivered as an `httpOnly; Secure; SameSite=Lax` cookie. Rotated on every use; reuse of a consumed token revokes the family (a standard reuse-detection scheme).
- **Logout** deletes the server-side row, so it is a real revocation and not just a client forgetting a string.

**One deployment detail worth writing down now, because it bites late:** with the web app on Vercel and the API on Render, the refresh cookie is cross-site, which forces `SameSite=None; Secure` and exact-origin CORS with `allow_credentials=True`. Wildcard CORS origins are silently ignored by browsers once credentials are involved. Set `FRONTEND_ORIGIN` as an env var and use it in both the CORS config and the cookie domain. Locally, both are `localhost`, so `SameSite=Lax` works and the difference never shows up in dev — which is exactly why it must be configured, not hardcoded.

### Rejected

| Option | Why not |
|---|---|
| **Auth0 / Clerk / Supabase Auth** | Fastest of all, and it puts the user table outside the database that owns the audit trail. Every `decision_audit_event` needs a durable local `actor_id` with a role; a hosted IdP adds a sync problem and a third-party dependency to a demo that must work offline. |
| **NextAuth on the frontend** | Then the FastAPI service must independently verify sessions anyway. Two auth systems, one of which is the real one. |
| **Hand-rolled** | A day you do not have, spent on the part of the system nobody is judging. |
| **Both tokens in localStorage** | XSS-readable. Refresh tokens belong in `httpOnly` cookies. |

---

## 5. APIs — REST, versioned, OpenAPI-generated

### Why REST and not GraphQL or tRPC

The blueprint's API sketch is already resource-shaped, and the access pattern is boring on purpose: list exceptions, get one exception, post a decision. GraphQL solves over-fetching across a rich object graph and would add a schema layer, resolver N+1 management, and a client cache for zero benefit here. tRPC needs a TypeScript backend, which this is not.

REST also gives you two things this product specifically needs: **HTTP caching semantics** for the read-heavy queue, and **`Idempotency-Key`** as a first-class header on POSTs (NFR-2).

### Conventions worth fixing on day 1

| Concern | Convention |
|---|---|
| Versioning | `/v1` prefix on everything. |
| Money on the wire | **Strings of minor units**: `{"gross_amount_minor": "1234500", "currency": "INR"}`. Strings survive JSON without float coercion in any client. |
| Timestamps | ISO-8601 UTC with `Z`. A separate `business_date` field where business-date logic applies. |
| Pagination | Cursor-based (`?cursor=&limit=`) on the queue, because rows shift as decisions land and offsets skip records. |
| Errors | RFC 9457 `application/problem+json` with a stable machine `code` — the frontend switches on codes, never on message text. |
| Idempotency | `Idempotency-Key` on `POST /imports` and `POST /exceptions/{id}/decision`. Key + request hash stored; a replay returns the original response. |
| Mutations | Every mutation writes a `decision_audit_event` in the **same transaction** as the change. Not a background write — a partial audit is worse than none. |

### Type generation

`openapi-typescript` reads `/openapi.json` at build time and emits `types/api.d.ts`. One npm script, run in CI and pre-commit. A backend field rename becomes a frontend compile error instead of a runtime `undefined` on stage.

---

## 6. AI — provider-neutral, schema-constrained JSON

### The requirement, stated before the vendor

The investigation layer needs exactly one capability: **JSON generation constrained to a schema**. Read an evidence packet, classify into the 8-value taxonomy, rank hypotheses, cite only what it was given, state its uncertainties.

Volume is trivial. The model is called **per exception case, on demand**, not per record. A demo run opens tens of cases at a few thousand tokens each — call it 100–150k tokens for an entire demo, which sits inside every free tier below with room to spare.

### Why the model does not have to be a frontier model

This is the consequence of a design decision made much earlier, and it is worth stating plainly because it inverts the usual calculus.

`verify.py` checks every citation against the packet and every number against what the engine computed. `policy.py` gates resolution on six deterministic conditions and reads none of the model's output. The model contributes **prose and a label, never an outcome** — there is no code path from a model response to a money column or a group status.

So the failure mode of a weaker model here is *a less insightful paragraph*, not *a wrong reconciliation*. Model choice is a cost and latency decision, not a correctness one. A system that needed a frontier model to stay correct would have the guardrails in the wrong place.

### The provider is configuration

`AI_PROVIDER` selects the adapter; `packages/ai_investigation/client.py` implements a small protocol behind it. Nothing else in the codebase knows which vendor is wired in, and `verify.py` is entirely provider-agnostic.

| Provider | Free tier | Schema enforcement | Notes |
|---|---|---|---|
| `gemini` **(default)** | Yes, no card. Flash models only | Native `responseSchema`, constrained decoding | 1M context, high TPM. Pro tier is not free. |
| `groq` | Yes, no card. 30 RPM / 14.4k RPD | Strict `json_schema` on *supported models only* | Fastest inference; check per-model support before relying on it. |
| `openai_compatible` | Varies | Varies | Cerebras, OpenRouter, Together, vLLM. Needs `AI_BASE_URL`. |
| `ollama` | Free, local, offline | Format-constrained | Demo insurance when the venue wifi fails. Needs `AI_BASE_URL`. |

**Deliberately not used: AWS Bedrock.** It has no permanent free tier — inference is pay-as-you-go from the first call, and the $200 new-account credit is a six-month trial, not a free tier. It also adds an AWS account, IAM, and region configuration to a four-day build. It is the right answer for enterprise compliance or for running Claude specifically, and the wrong answer here.

### Structured outputs, not prompt-and-hope

The schema is one Pydantic model, shared across every provider adapter:

```python
class Hypothesis(BaseModel):
    statement: str
    evidence_ids: list[str]
    likelihood: Literal["high", "medium", "low"]

class Investigation(BaseModel):
    classification: ExceptionType          # the 8-value enum, nothing else parses
    hypotheses: list[Hypothesis]
    recommended_action: str
    requires_human_approval: bool
    confidence: float = Field(ge=0, le=1)   # advisory; never reaches the gate
    uncertainties: list[str]
```

Each adapter hands the provider its native constrained-decoding hook — `responseSchema` for Gemini, `response_format={"type": "json_schema", ...}` for Groq and the OpenAI-compatible set — and then validates the result against `Investigation` regardless. The provider's constraint is an optimisation that removes a failure class; the Pydantic validation is the actual guarantee, and it runs even if a provider's enforcement is weak or absent.

`classification` cannot come back as a type outside the taxonomy; `confidence` cannot come back as `"quite high"`. That satisfies §11.4 of the blueprint — schema validation — before any of the grounding checks run.

### The two checks that must be yours, not the SDK's

Schema validity is not grounding. Two post-validation gates:

1. **Citation verification.** Every `evidence_id` is checked for membership in the packet's ID set. A citation outside it fails the whole response and logs a grounding violation with the offending ID. This is the check that makes "grounded" a claim you can defend rather than assert.
2. **Numeric cross-check.** Any number appearing in `recommended_action` or a hypothesis is matched against the values the engine put in the packet. A number the engine did not compute fails the response. This enforces §11 — *do not use AI for arithmetic* — mechanically rather than by prompt instruction.

Both are cheap functions, and both are what separates this from a wrapper around a chat completion.

### Prompt and version handling

Prompt templates live as versioned files in `packages/ai_investigation/prompts/`, with a `prompt_version` string stamped onto every `ai_investigation` row alongside `model_version`. NFR-10 requires reconstructing any decision; that requires knowing which prompt produced it.

**PII redaction runs before the packet leaves the process** (NFR-5): customer names, emails, phone numbers, and card fragments are replaced with stable pseudonyms so the model can still reason about identity ("the same customer as record 3") without receiving the actual value. A test asserts that a packet containing a seeded email never appears unredacted in an outbound payload.

---

## 7. Testing

The eval harness is not a testing nicety here — the submission's central claim is a set of numbers, and the harness is what makes those numbers true. Budget for it explicitly.

| Layer | Tool | What it covers | Priority |
|---|---|---|---|
| Money & normalisation | pytest, property-based (Hypothesis) | Every amount string → paise. Property: parse→format→parse is identity; no float ever appears. | **P0** |
| Matching rules | pytest + golden files in `data/fixtures/` | One tiny hand-built fixture per rule and per edge case in §6. Expected groups/links/evidence committed as JSON. | **P0** |
| Auto-resolve gate | pytest, table-driven | Every one of the six conditions, each independently forced to fail. Plus the explicit test: *model confident + gate says review → review wins.* | **P0** |
| Evaluation | pytest suite over the held-out partition | Asserts precision, recall, auto-resolution precision, and **false-clear rate == 0**. Fails the build if a rule change breaks safety. | **P0** |
| API | pytest + `httpx.AsyncClient` + testcontainers-postgres | Auth flows, RBAC (403 on the analyst-approves-material path), idempotency replay, import rejection reporting. | **P1** |
| Frontend units | Vitest + React Testing Library | The amount-bridge component, confidence badges, queue sorting. | **P2** |
| E2E | Playwright | Exactly the demo path: login → upload → run → open a case → approve → see audit. | **P2** |

### Why testcontainers rather than SQLite-for-tests

Half the guarantees are database-level: the append-only trigger, the `CHECK` on the net-amount identity, the unique constraints, the advisory lock. Testing against SQLite would test a different system and pass while the real one is broken. `testcontainers` spins up real Postgres 16 per session; on a machine where Docker-in-test is awkward, fall back to a `ledgergraph_test` database in the Compose Postgres and truncate between tests.

### The golden-file discipline

For each edge case in PRD §6, commit a fixture of 3–10 records and the expected engine output. This is what lets you change a rule on day 4 and know in seconds whether you broke the same-amount-same-day abstention. Without it, every rule change is a re-verification of the whole demo by hand — and on day 4 you will not do it, and something will be quietly wrong on stage.

---

## 8. Deployment — Compose locally, Render + Vercel hosted

You need both, so the requirement is **one artifact, two targets**: the same `backend/Dockerfile` runs locally under Compose and on Render.

### Local

```yaml
# docker-compose.yml — three services, one command
services:
  db:    # postgres:16-alpine, named volume, healthcheck
  api:   # build backend, depends_on db healthy, hot reload via volume mount
  web:   # build frontend, NEXT_PUBLIC_API_URL=http://localhost:8000
  # redis: commented out — uncomment when ARQ replaces BackgroundTasks
```

`docker compose up` → API on `:8000`, web on `:3000`, Postgres on `:5432`. Migrations run as an entrypoint step; seeding is `make seed`.

### Hosted

**Render** for API + Postgres, via a committed `render.yaml`:

- a Docker web service built from `backend/Dockerfile`, health check on `/healthz`;
- a managed Postgres instance, `DATABASE_URL` injected;
- migrations as a pre-deploy command;
- secrets (`AI_API_KEY`, `JWT_SECRET`) as environment variables, never committed.

**Vercel** for the Next.js app: connect the repo, root directory `frontend`, set `NEXT_PUBLIC_API_URL` to the Render URL.

**Why this split rather than one platform:** Vercel is where Next.js is fastest to deploy and hardest to misconfigure; Render is where a Dockerised Python service with a managed Postgres is fastest to deploy and hardest to misconfigure. Each half runs on its home turf. `render.yaml` means the backend infra is version-controlled and reproducible rather than a sequence of dashboard clicks you cannot repeat.

**Railway is an equally good single-platform alternative** if you would rather have one dashboard and one bill — the Dockerfiles are unchanged either way.

### The three deployment gotchas, written down now so they do not eat day 4

1. **CORS + cookies across origins.** Exact-origin `allow_origins`, `allow_credentials=True`, and `SameSite=None; Secure` on the refresh cookie. Wildcard origins silently fail with credentials. Locally this never reproduces — configure it from `FRONTEND_ORIGIN`, do not hardcode.
2. **Free-tier spin-down kills in-process runs.** A free Render instance sleeps after inactivity and can be reaped mid-run. Use a paid always-on instance for the demo window, or accept that a slept run is marked `failed` and re-run. This is the concrete price of choosing `BackgroundTasks` over a worker.
3. **Upload size limits.** Platform request caps are lower than local. Keep demo files a few MB, and note chunked upload as the Phase 3 answer rather than discovering the limit live.

### Rejected

| Option | Why not |
|---|---|
| **Fly.io** | Excellent, and more config concepts (volumes, regions, machines) than a 4-day budget wants. |
| **AWS ECS/Fargate** | Correct at scale, days of setup. Wrong shape for this window. |
| **Everything on Vercel** | Serverless functions and a minutes-long batch run are the wrong fit, and you already chose FastAPI. |
| **Kubernetes** | No. |

---

## 9. Observability

**structlog**, JSON output, with `run_id` bound into the context for the whole run so every rule fire, every exception created, and every AI call for that run is greppable by one identifier. A `run_metrics` row per run persists throughput, stage timings, counts by bucket, and validation failure counts — which doubles as the data behind the dashboard's run-health panel.

Sentry is a five-line optional add for the hosted deploy. OpenTelemetry is the right answer at scale and is not worth a day here; the structured logs plus the `run_metrics` table cover what a demo needs to prove.

---

## 10. The complete dependency list

**`backend` (Python 3.12)**

```
fastapi · uvicorn[standard] · pydantic · pydantic-settings
sqlalchemy[asyncio] · asyncpg · alembic
fastapi-users[sqlalchemy] · argon2-cffi · python-jose[cryptography]
anthropic · structlog · python-multipart
polars · python-dateutil · rapidfuzz          # generator, eval, R7 similarity
# dev: pytest · pytest-asyncio · httpx · testcontainers[postgres] · hypothesis · ruff · mypy
```

**`frontend` (Node 20)**

```
next · react · react-dom · typescript
tailwindcss · class-variance-authority · clsx · tailwind-merge · lucide-react
@tanstack/react-query · recharts · zod · date-fns
# dev: vitest · @testing-library/react · @playwright/test · openapi-typescript · eslint · prettier
```

Two runtimes, no message broker, no object store, no search index. **Every piece of infrastructure you do not run is a piece that cannot break during the demo.**

---

## 11. Where this stack will hurt, and when

Being honest about the ceiling, so none of it is a surprise:

| Limit | Bites at | The fix, when it matters |
|---|---|---|
| In-process runs die with the API process | A long run on a spinning-down free instance | ARQ + Redis worker. One file changes. |
| `bytea` file storage bloats the table | Files over ~20–30 MB | Swap in `S3ObjectStore` behind the existing interface. |
| Single Postgres instance | Sustained concurrent runs | Read replica for reporting; the engine already reads the snapshot. |
| Whole-run set-based SQL | Roughly 10⁶ records per run | Partition by business date and run per partition; the run model already scopes to a snapshot. |
| No rules DSL — rules are Python | A finance user wanting to edit tolerances | Tolerances and thresholds are already config (PRD §5.3). A rules DSL is Phase 3. |

None of these bind in a hackathon. All of them have a known move, which is the point of writing them down.

---

## 12. Summary of the reasoning

Every meaningful choice here traces back to the same principle from blueprint §22 — **trusted because it can show its work**:

- **Postgres over SQLite** — constraints and exact numerics are enforced where they cannot be bypassed.
- **SQL over dataframes in the engine** — a join gives a result; an evidence row gives a reason, and the reason is the product.
- **Structured outputs plus citation verification** — "grounded" becomes a mechanical check, not a promise in a prompt.
- **`fastapi-users` over hand-rolled auth** — buy the commodity, spend the day on the differentiator.
- **`BackgroundTasks` over Celery** — infrastructure you do not run is infrastructure that cannot fail on stage.
- **TypeScript money-as-strings** — the frontend is made structurally incapable of doing arithmetic on money.

The stack is deliberately small. In a four-day window, the systems you did not add are as important as the ones you did.
