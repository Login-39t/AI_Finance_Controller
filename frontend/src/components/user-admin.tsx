"use client";

import { useActionState } from "react";
import { useFormStatus } from "react-dom";
import { SpinnerGapIcon } from "@phosphor-icons/react/dist/ssr";

import type { User, UserRole } from "@/lib/api";
import {
  type UserActionState,
  changeRoleAction,
  createUserAction,
} from "@/lib/user-actions";
import { Select } from "@/components/select";

const ROLES: UserRole[] = ["analyst", "reviewer", "controller", "admin"];
const ROLE_NOTE: Record<UserRole, string> = {
  analyst: "reads and investigates",
  reviewer: "decides below the threshold",
  controller: "decides material cases",
  admin: "everything, plus users",
};

const INITIAL: UserActionState = { status: "idle", message: null };
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

function messageColor(status: UserActionState["status"]) {
  return status === "error"
    ? "var(--danger)"
    : status === "ok"
      ? "var(--ok)"
      : "var(--ink-2)";
}

function Submit({ label, pendingLabel }: { label: string; pendingLabel: string }) {
  const { pending } = useFormStatus();
  return (
    <button
      type="submit"
      disabled={pending}
      className="flex items-center justify-center gap-2 px-3 py-2 text-[12.5px] font-medium transition-colors duration-100 active:translate-y-px"
      style={{
        borderRadius: "var(--radius)",
        background: pending ? "var(--surface-2)" : "var(--flag)",
        color: pending ? "var(--ink-3)" : "#ffffff",
        cursor: pending ? "not-allowed" : "pointer",
      }}
    >
      {pending && <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />}
      {pending ? pendingLabel : label}
    </button>
  );
}

function CreateUserForm() {
  const [state, action] = useActionState(createUserAction, INITIAL);
  return (
    <form action={action} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor="fullName" className="label">Full name</label>
        <input id="fullName" name="fullName" required className={FIELD} style={fieldStyle()} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="email" className="label">Email</label>
        <input id="email" name="email" type="email" autoComplete="off" required
          className={FIELD} style={fieldStyle()} />
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="password" className="label">Password</label>
        <input id="password" name="password" type="password" autoComplete="new-password"
          required className={FIELD} style={fieldStyle()} />
        <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>
          At least 10 characters, and not the name in the email.
        </span>
      </div>
      <div className="flex flex-col gap-1">
        <label htmlFor="role" className="label">Role</label>
        <Select
          id="role"
          name="role"
          defaultValue="analyst"
          options={ROLES.map((r) => ({
            value: r,
            label: `${r} — ${ROLE_NOTE[r]}`,
          }))}
        />
      </div>
      <Submit label="Create user" pendingLabel="Creating…" />
      {state.message && (
        <p className="text-[12px]" style={{ color: messageColor(state.status) }}>
          {state.message}
        </p>
      )}
    </form>
  );
}

function RoleForm({ user, isSelf }: { user: User; isSelf: boolean }) {
  const [state, action] = useActionState(changeRoleAction, INITIAL);
  return (
    <form action={action} className="flex items-center gap-2">
      <input type="hidden" name="userId" value={user.id} />
      <div className="w-[110px]">
        <Select
          name="role"
          defaultValue={user.role}
          disabled={isSelf}
          size="sm"
          options={ROLES.map((r) => ({ value: r, label: r }))}
        />
      </div>
      {!isSelf && (
        <button
          type="submit"
          className="px-2 py-1 text-[12px] transition-colors duration-100"
          style={{ borderRadius: "var(--radius)", background: "var(--surface-2)", color: "var(--ink)" }}
        >
          Update
        </button>
      )}
      {isSelf ? (
        <span className="text-[11px]" style={{ color: "var(--ink-3)" }}>you</span>
      ) : (
        state.message && (
          <span className="text-[11px]" style={{ color: messageColor(state.status) }}>
            {state.message}
          </span>
        )
      )}
    </form>
  );
}

export function UserAdmin({ users, currentUserId }: { users: User[]; currentUserId: string }) {
  return (
    <div className="mx-auto grid max-w-[1100px] gap-6 px-4 py-6 lg:grid-cols-[320px_1fr]">
      <section
        className="h-fit border"
        style={{ background: "var(--surface)", borderColor: "var(--line)", borderRadius: "var(--radius)" }}
      >
        <header className="border-b px-4 py-3" style={{ borderColor: "var(--line)" }}>
          <span className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
            Create a user
          </span>
        </header>
        <div className="px-4 py-4">
          <CreateUserForm />
        </div>
      </section>

      <section
        className="h-fit border"
        style={{ background: "var(--surface)", borderColor: "var(--line)", borderRadius: "var(--radius)" }}
      >
        <header className="flex items-baseline justify-between border-b px-4 py-3"
          style={{ borderColor: "var(--line)" }}>
          <span className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>Users</span>
          <span className="label">{users.length} total</span>
        </header>
        <ul>
          {users.map((u) => (
            <li key={u.id} className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-2.5 last:border-b-0"
              style={{ borderColor: "var(--line)" }}>
              <div className="min-w-0">
                <div className="num truncate text-[12.5px]" style={{ color: "var(--ink)" }}>{u.email}</div>
                <div className="truncate text-[11.5px]" style={{ color: "var(--ink-3)" }}>{u.fullName}</div>
              </div>
              <RoleForm user={u} isSelf={u.id === currentUserId} />
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
