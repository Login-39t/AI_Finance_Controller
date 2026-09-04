import { SignOutIcon } from "@phosphor-icons/react/dist/ssr";

import { signOut } from "@/lib/auth-actions";
import type { Role } from "@/lib/types";

/**
 * Who is signed in, and the way out.
 *
 * The role is displayed because it changes what the user is allowed to
 * do on the next screen, and a person who has forgotten which account
 * they are in will read a disabled button as a broken one.
 *
 * A plain form rather than a dropdown: sign-out is a server action, and
 * one visible control beats a menu that hides the only thing in it.
 */
export function UserMenu({ name, role }: { name: string; role: Role }) {
  return (
    <div className="flex items-center gap-3">
      <span
        className="hidden max-w-[160px] truncate text-[12.5px] sm:inline"
        style={{ color: "var(--ink-2)" }}
        title={name}
      >
        {name}
      </span>
      <span className="label">{role}</span>
      <form action={signOut}>
        <button
          type="submit"
          aria-label="Sign out"
          title="Sign out"
          className="flex cursor-pointer items-center px-1.5 py-1 transition-colors duration-100"
          style={{ color: "var(--ink-3)", borderRadius: "var(--radius)" }}
        >
          <SignOutIcon size={15} weight="bold" />
        </button>
      </form>
    </div>
  );
}
