# Deploying LedgerGraph — Step by Step (Render + Vercel)

A complete, click-by-click guide to putting LedgerGraph online: the API
and PostgreSQL on **Render**, the Next.js frontend on **Vercel**. Follow
it top to bottom the first time — the ordering matters, and one step
(wiring the two URLs together) cannot be skipped.

> For the *why* behind these choices (why the split, how cookies work
> across two domains, what has and hasn't been executed), see
> [`06-deployment.md`](06-deployment.md). This file is the *how*.

---

## 0. The shape of the deployment

```
   Browser
      │  (HTTPS)
      ▼
  ┌─────────────────────┐        ┌──────────────────────────┐
  │  Vercel             │  API   │  Render                  │
  │  Next.js frontend   │ ─────► │  FastAPI  +  PostgreSQL   │
  │  (frontend/)        │  calls │  (backend/ + db/)         │
  └─────────────────────┘        └──────────────────────────┘
```

- The **browser never calls the API directly.** Every request goes
  through a Next.js Server Component, Server Action, or route handler,
  which attaches the session token server-side. That is why the frontend
  needs `API_URL` (a *server* variable), not `NEXT_PUBLIC_API_URL`.
- The API and the frontend live on **different domains**, so the refresh
  cookie is issued `SameSite=None; Secure`. The code derives this
  automatically from `ENVIRONMENT` — you do not configure it.

**You will need:** a GitHub account with this repo pushed, a
[Render](https://render.com) account, a [Vercel](https://vercel.com)
account, and (for AI investigations) a free
[Groq](https://console.groq.com/keys) API key. No credit card is required
for any of them on the free tiers.

---

## 1. Push the repository to GitHub

Render and Vercel both deploy *from* GitHub. If the repo is already at
`github.com/Login-39t/AI_Finance_Controller`, make sure `main` is
current:

```bash
git push origin main
```

Everything below reads from that repository. Each later `git push`
triggers an automatic redeploy on both platforms.

---

## 2. Render — the database and the API

Render reads [`render.yaml`](../render.yaml) and provisions **both** the
PostgreSQL database and the API from it. This is called a *Blueprint*.

### 2.1 Create the Blueprint

1. Go to the [Render dashboard](https://dashboard.render.com) → **New +**
   → **Blueprint**.
2. Connect your GitHub account and pick the
   **AI_Finance_Controller** repository.
3. Render detects `render.yaml` and shows what it will create:
   - `ledgergraph-db` — PostgreSQL 16 (free plan)
   - `ledgergraph-api` — a Docker web service (free plan)
4. Click **Apply**. Render creates the database first, then starts
   building the API image from `backend/Dockerfile`.

### 2.2 Fill in the prompted secrets

`render.yaml` deliberately contains **no secrets**. Two values are marked
`sync: false`, so Render asks you for them. During the Blueprint apply (or
afterwards under the service's **Environment** tab):

| Variable | What to enter now |
|---|---|
| `FRONTEND_ORIGIN` | A placeholder for the moment — e.g. `https://example.com`. You will replace this with the real Vercel URL in **Step 4**. It cannot be blank. |
| `AI_API_KEY` | Leave blank for now. You will set it in **Step 5** if you want AI investigations. |

`JWT_SECRET` is **not** prompted — `render.yaml` generates it once with
`generateValue: true`, and it never appears in git.

### 2.3 What happens on deploy

Before the new instance takes traffic, Render runs the **pre-deploy
command** from `render.yaml`:

```
cd /app/backend && alembic upgrade head
```

This applies `db/schema.sql` verbatim — every table, enum, trigger and
partial index — through Alembic revision `0001`. Running it here, rather
than at app startup, means it happens **once** rather than racing every
replica.

> **This is the first time the schema has ever run against a real
> Postgres.** It is parsed and checked in the test suite, but never
> executed against a server from the development machine. If the
> pre-deploy step fails, read the log — it will name the SQL statement.

### 2.4 Confirm the API is up

When the deploy finishes, open the service URL Render gives you
(e.g. `https://ledgergraph-api.onrender.com`) and check:

- `https://<api>/healthz` → `200`, `{"status":"ok"}` (process is alive)
- `https://<api>/readyz` → `200` once the database is reachable
  (`503` naming the database if not)

**Copy the API URL.** You need it in Step 3.

> **Free-tier note:** Render spins the free API down after ~15 minutes of
> inactivity; the next request takes ~30–50s to wake it. Fine for a demo,
> surprising if you don't expect it.

---

## 3. Vercel — the frontend

1. Go to the [Vercel dashboard](https://vercel.com/dashboard) → **Add
   New…** → **Project**.
2. Import the **AI_Finance_Controller** repository.
3. **Set the Root Directory to `frontend`.** This is essential — the
   Next.js app is not at the repo root. Click **Edit** next to Root
   Directory and choose `frontend`.
4. Framework preset auto-detects as **Next.js**. Leave the build and
   output settings at their defaults.
5. Under **Environment Variables**, add one:

   | Name | Value |
   |---|---|
   | `API_URL` | The Render API URL from Step 2.4, e.g. `https://ledgergraph-api.onrender.com` |

   Use `API_URL`, **not** `NEXT_PUBLIC_API_URL`. The browser never needs
   the API address; shipping it to the client would leak it for no
   purpose.
6. Click **Deploy**. When it finishes, **copy the Vercel URL**
   (e.g. `https://ai-finance-controller.vercel.app`).

At this point the frontend loads but **every API call fails CORS** — the
API does not yet trust the Vercel origin. That is Step 4.

---

## 4. Wire them together (do not skip)

The API only accepts credentialed requests from the exact origin in
`FRONTEND_ORIGIN`. Now that you have the real Vercel URL:

1. Render dashboard → `ledgergraph-api` → **Environment**.
2. Edit `FRONTEND_ORIGIN` → set it to your **exact** Vercel URL, with
   `https://` and **no trailing slash**:
   ```
   https://ai-finance-controller.vercel.app
   ```
3. Save. Render redeploys the API automatically.

Why exact: CORS runs with `allow_credentials=True`, and browsers silently
ignore a wildcard origin once credentials (the refresh cookie) are
involved. A near-miss here reads as "auth is broken in production" with no
error in the logs.

After the redeploy, sign-in from the Vercel site works.

---

## 5. Enable AI investigations (optional, but it's the headline feature)

AI is **off by default** so a missing key degrades investigations rather
than breaking the deploy. To turn it on for the demo:

1. Get a free key at [console.groq.com/keys](https://console.groq.com/keys)
   (sign in with Google/GitHub — no card). Keys start with `gsk_`.
2. Render dashboard → `ledgergraph-api` → **Environment**, set:

   | Variable | Value |
   |---|---|
   | `AI_ENABLED` | `true` |
   | `AI_API_KEY` | your `gsk_…` key |

   `AI_PROVIDER` (`groq`) and `AI_MODEL` (`openai/gpt-oss-120b`) are
   already set in `render.yaml` to the verified-working pair.
3. Save → redeploy.

Now the **Investigate** button on any case makes a live, grounded model
call. If the key is wrong or missing, investigations show as
*unavailable* — the reconciliation itself is unaffected.

> **Switching to AWS Bedrock later?** Set `AI_PROVIDER=bedrock`,
> `AI_MODEL` to the console's inference-profile id (e.g.
> `us.anthropic.claude-sonnet-4-5-20250929-v1:0`), and add
> `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` / `AWS_REGION`. No key is
> needed in `AI_API_KEY` for Bedrock. The code already supports it.

---

## 6. Getting a login that can decide (the production seeding question)

**Production seeds no users.** `SEED_DEMO_USERS=false` in `render.yaml`,
and `config.py` refuses to seed them under `ENVIRONMENT=production`
anyway, because the demo password is published in the README. Self-service
registration (`/register`) only ever creates an **analyst**, who cannot
close material cases — so a straight production deploy leaves you with no
controller or admin.

Pick one:

### Option A — a *demo* deployment with the four role accounts (recommended for the hackathon)

Run the deployment as **staging** instead of production. Staging still
gets cross-site cookies (only `local` is treated as same-site), so nothing
about the security posture changes except that the four demo accounts are
seeded.

On Render → `ledgergraph-api` → **Environment**:

| Variable | Value |
|---|---|
| `ENVIRONMENT` | `staging` |
| `SEED_DEMO_USERS` | `true` |

Redeploy. You can now sign in with the seeded accounts, password
`ledgergraph-demo-2026`:

- `controller@ledgergraph.dev` — decides material cases
- `admin@ledgergraph.dev` — everything, plus users
- `reviewer@ledgergraph.dev` — decides below the threshold
- `analyst@ledgergraph.dev` — reads and investigates

> These passwords are public. Use this only for a throwaway demo URL,
> never for anything holding real data.

### Option B — a true production deployment

Keep `ENVIRONMENT=production` and `SEED_DEMO_USERS=false`. Register your
own analyst account through the sign-in page, then promote it to `admin`
directly in the database (there is no admin-bootstrap endpoint yet — see
[Status](#status-what-is-and-isnt-done)):

```sql
UPDATE users SET role = 'admin' WHERE email = 'you@example.com';
```

Use Render's PostgreSQL **Connect** panel (psql or a GUI) to run it.

---

## 7. Load data so there is something to reconcile

A fresh deployment has an empty database. To populate the demo, sign in
and use the **Imports** page to upload the six synthetic source files from
`data/synthetic/out/` (generate them locally first with `make gen-data` if
they aren't present):

| Upload | File |
|---|---|
| Gateway payments | `payments.csv` |
| Razorpay settlements | `settlement_batches.csv`, then `settlement_lines.csv` |
| Bank statement | `bank_statement.csv` |
| Invoices | `invoices.csv` |
| Internal ledger | `ledger.csv` |

Then open the **Runs** page and start a reconciliation. When it completes,
the queue fills with cases you can open, decide, and investigate.

---

## 8. Verify the whole thing end to end

1. Open the Vercel URL. You should land on the sign-in page.
2. Sign in (Step 6).
3. Confirm the **Overview** dashboard shows exposure and case counts.
4. Open a case → click **Investigate** (if AI is enabled) → a grounded
   hypothesis appears within a few seconds.
5. Record a decision → check it shows in the case's **Audit history**.

---

## 9. Troubleshooting

| Symptom | Cause & fix |
|---|---|
| API deploy fails at `alembic upgrade head` | The migration log names the failing SQL. Most often the database wasn't fully ready — Render retries; if it persists, check the `DATABASE_URL` binding in `render.yaml`. |
| API boots then crashes with *"PERSISTENCE=memory in production"* | `PERSISTENCE=postgres` missing. It is set in `render.yaml`; if you edited env vars, restore it. |
| Sign-in fails, browser console shows a CORS error | `FRONTEND_ORIGIN` on Render doesn't exactly match the Vercel URL. No trailing slash, correct `https://`. Redeploy after fixing (Step 4). |
| Signs in, but the session doesn't persist (bounced back to login) | The refresh cookie was dropped. This happens if the API is served over plain HTTP or the origins don't match — both are correct automatically on Render+Vercel, so re-check `FRONTEND_ORIGIN` and that you're using the `https://` URLs. |
| `/readyz` returns 503 | The database is unreachable. Check the `ledgergraph-db` service is running and `DATABASE_URL` is bound. `/healthz` staying 200 is correct — it reports the process, not the database. |
| Investigate button shows *"unavailable"* | AI is off or the key is wrong. Set `AI_ENABLED=true` and a valid `AI_API_KEY` (Step 5). The reconciliation is unaffected either way. |
| First request after idle takes ~40s | Render free tier cold start. Expected; upgrade the plan to remove it. |
| Frontend build fails on Vercel | Root Directory not set to `frontend` (Step 3.3), or `API_URL` missing. |

---

## 10. What each variable is for (reference)

**Render — `ledgergraph-api`:**

| Variable | Set by | Purpose |
|---|---|---|
| `ENVIRONMENT` | `render.yaml` | `production` (or `staging` for the seeded demo) |
| `PERSISTENCE` | `render.yaml` | `postgres` — production refuses `memory` |
| `DATABASE_URL` | Render (auto) | Connection string; driver normalised to `+asyncpg` in code |
| `JWT_SECRET` | `render.yaml` (generated) | Signs access tokens; 256-bit, never in git |
| `SEED_DEMO_USERS` | `render.yaml` | `false` in production; `true` under staging for the demo accounts |
| `FRONTEND_ORIGIN` | **you** (Step 4) | Exact Vercel URL, for CORS with credentials |
| `AI_ENABLED` | **you** (Step 5) | `true` to turn on investigations |
| `AI_PROVIDER` / `AI_MODEL` | `render.yaml` | `groq` / `openai/gpt-oss-120b` |
| `AI_API_KEY` | **you** (Step 5) | Groq key (`gsk_…`) |
| `BUSINESS_TIMEZONE` / `BASE_CURRENCY` | `render.yaml` | `Asia/Kolkata` / `INR` |

**Vercel — frontend:**

| Variable | Set by | Purpose |
|---|---|---|
| `API_URL` | **you** (Step 3) | Render API base; used server-side only |

---

## Status: what is and isn't done

Honest about the edges, so nothing surprises you on stage:

| Piece | State |
|---|---|
| API image, migrations, `render.yaml` | Written; `render.yaml` now sets `PERSISTENCE` and the Groq provider |
| Frontend (Next.js, standalone) on Vercel | Written |
| AI investigations (Groq) | **Working end-to-end** — verified in the browser |
| `db/schema.sql` against a real Postgres | Runs for the first time on your Render deploy — see Step 2.3 |
| Postgres repository under real load | Reviewed; exercised the first time you deploy |
| Admin-bootstrap endpoint | **Not built.** Production has no way to create the first controller/admin except the SQL in Step 6B. The staging demo path (6A) sidesteps this. |
