import { GraphIcon } from "@phosphor-icons/react/dist/ssr";

import { SignInForm } from "@/components/sign-in-form";

/**
 * Sign in.
 *
 * Outside the `(app)` group on purpose: no nav, no run context, nothing
 * that would make an API call the visitor is not yet allowed to make.
 *
 * The demo accounts are listed on the page because this is a hackathon
 * build and a judge should not have to read a README to get in. The API
 * refuses to create them when `ENVIRONMENT=production`, so this is a
 * local convenience rather than a published credential.
 */

const DEMO_ROLES = [
  { email: "analyst@ledgergraph.dev", role: "Analyst", can: "reads and investigates" },
  { email: "reviewer@ledgergraph.dev", role: "Reviewer", can: "decides below the threshold" },
  { email: "controller@ledgergraph.dev", role: "Controller", can: "decides material cases" },
  { email: "admin@ledgergraph.dev", role: "Admin", can: "everything, plus users" },
] as const;

export default function LoginPage() {
  return (
    <main className="flex min-h-[100dvh] items-center justify-center px-4 py-10">
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex items-center gap-2">
          <GraphIcon size={19} weight="duotone" style={{ color: "var(--flag)" }} />
          <span
            className="text-[15px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            LedgerGraph
          </span>
        </div>

        <h1
          className="mb-1 text-[19px] font-semibold tracking-tight"
          style={{ color: "var(--ink)" }}
        >
          Sign in
        </h1>
        <p className="mb-5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
          Every decision below is recorded against your name and role.
        </p>

        <SignInForm />

        <section
          className="mt-6 border"
          style={{
            background: "var(--surface)",
            borderColor: "var(--line)",
            borderRadius: "var(--radius)",
          }}
        >
          <header className="border-b px-3 py-2" style={{ borderColor: "var(--line)" }}>
            <span className="label">Demo accounts &middot; password ledgergraph-demo-2026</span>
          </header>
          <ul>
            {DEMO_ROLES.map((d) => (
              <li
                key={d.email}
                className="flex items-baseline justify-between gap-3 border-b px-3 py-1.5 last:border-b-0"
                style={{ borderColor: "var(--line)" }}
              >
                <span className="num truncate text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                  {d.email}
                </span>
                <span
                  className="shrink-0 text-[11px]"
                  style={{ color: "var(--ink-3)" }}
                  title={d.can}
                >
                  {d.can}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}
