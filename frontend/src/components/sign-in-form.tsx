"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { SpinnerGapIcon, WarningCircleIcon } from "@phosphor-icons/react/dist/ssr";

import { signIn } from "@/lib/auth-actions";

const FIELD =
  "w-full border px-2.5 py-2 text-[13px] outline-none transition-colors duration-100";

function fieldStyle() {
  return {
    borderRadius: "var(--radius)",
    borderColor: "var(--line)",
    background: "var(--surface)",
    color: "var(--ink)",
  } as const;
}

function SubmitButton() {
  // `useFormStatus` has to read the status of the form it sits inside, so
  // it lives in a child of <form> rather than beside the action call.
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex w-full items-center justify-center gap-2 px-3 py-2 text-[13px] font-medium transition-colors duration-100 active:translate-y-px"
      style={{
        borderRadius: "var(--radius)",
        background: pending ? "var(--surface-2)" : "var(--flag)",
        color: pending ? "var(--ink-3)" : "#ffffff",
        cursor: pending ? "not-allowed" : "pointer",
      }}
    >
      {pending && <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />}
      {pending ? "Signing in" : "Sign in"}
    </button>
  );
}

export function SignInForm() {
  const [state, action] = useActionState(signIn, { error: null });

  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="email" className="label">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="username"
          required
          defaultValue="controller@ledgergraph.dev"
          className={FIELD}
          style={fieldStyle()}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="password" className="label">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          className={FIELD}
          style={fieldStyle()}
        />
      </div>

      <SubmitButton />

      {state.error && (
        <p
          className="flex items-start gap-1.5 border-l-2 py-1 pl-2.5 text-[12px]"
          style={{ borderColor: "var(--flag)", color: "var(--ink-2)" }}
          role="alert"
        >
          <WarningCircleIcon size={13} weight="bold" className="mt-px shrink-0" />
          {state.error}
        </p>
      )}
    </form>
  );
}
