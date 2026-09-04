"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { SpinnerGapIcon, WarningCircleIcon } from "@phosphor-icons/react/dist/ssr";

import { signUp } from "@/lib/auth-actions";

const FIELD =
  "w-full border px-2.5 py-2 text-[13px] outline-none transition-colors duration-100";

function fieldStyle() {
  return {
    borderRadius: "var(--radius)",
    borderColor: "var(--line)",
    background: "var(--surface-2)",
    color: "var(--ink)",
    backdropFilter: "blur(12px)",
  } as const;
}

function SubmitButton() {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex w-full items-center justify-center gap-2 px-3 py-2.5 text-[13px] font-medium transition-all duration-150 active:translate-y-px"
      style={{
        borderRadius: "var(--radius)",
        background: pending ? "var(--surface-2)" : "var(--flag)",
        color: pending ? "var(--ink-3)" : "#ffffff",
        cursor: pending ? "not-allowed" : "pointer",
        boxShadow: pending ? "none" : "0 4px 14px rgba(0, 112, 243, 0.35)",
      }}
    >
      {pending && <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />}
      {pending ? "Creating account" : "Create account"}
    </button>
  );
}

export function SignUpForm() {
  const [state, action] = useActionState(signUp, { error: null });

  return (
    <form action={action} className="mt-5 flex flex-col gap-3.5">
      <div className="flex flex-col gap-1">
        <label htmlFor="email" className="label">
          Work email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          required
          autoComplete="username"
          placeholder="analyst@tallyproof.dev"
          className={FIELD}
          style={fieldStyle()}
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="name" className="label">
          Full name
        </label>
        <input
          id="name"
          name="name"
          type="text"
          required
          autoComplete="name"
          placeholder="Ada Lovelace"
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
          required
          minLength={10}
          autoComplete="new-password"
          className={FIELD}
          style={fieldStyle()}
        />
        <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
          At least 10 characters, and not the name in your email.
        </span>
      </div>

      <SubmitButton />

      <p className="text-[11.5px]" style={{ color: "var(--ink-3)" }}>
        New accounts start as an analyst — read and investigate. An
        administrator can grant a higher role.
      </p>

      {state.error && (
        <p
          className="flex items-start gap-1.5 border-l-2 py-1.5 pl-3 text-[12px] rounded-r-[var(--radius)]"
          style={{
            borderColor: "var(--danger)",
            background: "var(--danger-wash)",
            color: "var(--danger)",
          }}
          role="alert"
        >
          <WarningCircleIcon size={13} weight="bold" className="mt-px shrink-0" />
          {state.error}
        </p>
      )}
    </form>
  );
}
