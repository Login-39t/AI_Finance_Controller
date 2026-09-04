import Link from "next/link";
import { GraphIcon } from "@phosphor-icons/react/dist/ssr";

import { SignUpForm } from "@/components/sign-up-form";

/**
 * Create an account.
 *
 * Public and outside the `(app)` group, like sign-in. Self-registration
 * only ever mints an analyst - the role is not a field on the form or the
 * request - so opening this page cannot escalate anyone. An admin grants a
 * higher role afterwards from the Users page.
 */
export default function RegisterPage() {
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
          Create your account
        </h1>
        <p className="mb-5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
          Every decision you record will be kept against your name and role.
        </p>

        <SignUpForm />

        <p className="mt-5 text-[12.5px]" style={{ color: "var(--ink-2)" }}>
          Already have an account?{" "}
          <Link href="/login" style={{ color: "var(--flag)" }}>
            Sign in
          </Link>
        </p>
      </div>
    </main>
  );
}
