import Link from "next/link";
import { GraphIcon, KeyIcon } from "@phosphor-icons/react/dist/ssr";

import { SignInForm } from "@/components/sign-in-form";

/**
 * Sign in.
 *
 * Outside the `(app)` group on purpose: no nav, no run context, nothing
 * that would make an API call the visitor is not yet allowed to make.
 *
 * The role accounts are listed on the page so a first-time reviewer can
 * see each role from the inside without reading a README first. They exist
 * only where `SEED_DEMO_USERS=true`; the config refuses to create them
 * under `ENVIRONMENT=production`, so this is a walkthrough aid, not a
 * published credential.
 */

const DEMO_ROLES = [
  { email: "analyst@tallyproof.dev", can: "reads and investigates" },
  { email: "reviewer@tallyproof.dev", can: "decides below the threshold" },
  { email: "controller@tallyproof.dev", can: "decides material cases" },
  { email: "admin@tallyproof.dev", can: "everything, plus users" },
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
            TallyProof
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

        <p className="mt-5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
          New here?{" "}
          <Link href="/register" style={{ color: "var(--flag)" }}>
            Create an account
          </Link>
        </p>

        <section
          className="mt-6 overflow-hidden border"
          style={{
            background: "var(--surface)",
            borderColor: "var(--line)",
            borderRadius: "var(--radius)",
            backdropFilter: "blur(12px)",
          }}
        >
          <header
            className="flex items-center gap-2 border-b px-3 py-2"
            style={{ borderColor: "var(--line)", background: "var(--flag-wash)" }}
          >
            <KeyIcon size={13} weight="duotone" style={{ color: "var(--flag)" }} />
            <span className="label" style={{ color: "var(--ink-2)" }}>
              Role accounts
            </span>
            <span
              className="num ml-auto text-[11px]"
              style={{ color: "var(--ink-3)" }}
              title="Shared password for every role account"
            >
              tallyproof-demo-2026
            </span>
          </header>
          <ul>
            {DEMO_ROLES.map((d) => (
              <li
                key={d.email}
                className="flex items-baseline justify-between gap-3 border-b px-3 py-1.5 last:border-b-0"
                style={{ borderColor: "var(--line-soft)" }}
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
