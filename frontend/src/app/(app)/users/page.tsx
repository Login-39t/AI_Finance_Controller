import Link from "next/link";

import { UserAdmin } from "@/components/user-admin";
import { listUsers } from "@/lib/api";
import { currentUser } from "@/lib/session";

/**
 * Admin user management.
 *
 * Gated to admins here as well as at the API. The gate on the page is a
 * convenience - it renders the right thing rather than a wall of failed
 * calls - but it is not the control: every create and role change is a
 * request the API authorises against the access token, so a non-admin who
 * reached this page could still do nothing.
 */
export default async function UsersPage() {
  const me = await currentUser();

  if (!me || me.role !== "admin") {
    return (
      <div className="mx-auto max-w-[46ch] px-4 py-16">
        <h1 className="text-[19px] font-semibold" style={{ color: "var(--ink)" }}>
          Administrators only
        </h1>
        <p className="mt-1 text-[13px]" style={{ color: "var(--ink-2)" }}>
          Managing users needs an administrator account. Ask an admin to grant you
          access, or return to the queue.
        </p>
        <Link href="/exceptions" className="mt-4 inline-block text-[13px]"
          style={{ color: "var(--flag)" }}>
          Back to exceptions
        </Link>
      </div>
    );
  }

  const users = (await listUsers()) ?? [];

  return (
    <>
      <div className="mx-auto max-w-[1100px] px-4 pt-6">
        <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
          Users
        </h1>
        <p className="mt-1 text-[13px]" style={{ color: "var(--ink-2)" }}>
          Create accounts and assign roles. A new user can sign in immediately with
          the password you set.
        </p>
      </div>
      <UserAdmin users={users} currentUserId={me.id} />
    </>
  );
}
