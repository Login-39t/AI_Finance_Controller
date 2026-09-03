"use server";

import { revalidatePath } from "next/cache";

import { ApiError, createUser, updateUserRole, type UserRole } from "./api";

/**
 * Admin user management.
 *
 * Server Actions, so the API token never leaves the Next.js server. The
 * API is the authority on every rule here - only an admin may create a
 * user or change a role, and an admin may not change their own - so these
 * carry whatever it says back to the form rather than re-checking it.
 */

export interface UserActionState {
  status: "idle" | "ok" | "error";
  message: string | null;
}

const ROLES: UserRole[] = ["analyst", "reviewer", "controller", "admin"];

export async function createUserAction(
  _prev: UserActionState,
  form: FormData,
): Promise<UserActionState> {
  const email = String(form.get("email") ?? "").trim();
  const fullName = String(form.get("fullName") ?? "").trim();
  const password = String(form.get("password") ?? "");
  const role = String(form.get("role") ?? "") as UserRole;

  if (!email || !fullName || !password) {
    return { status: "error", message: "Name, email and password are all required." };
  }
  if (!ROLES.includes(role)) {
    return { status: "error", message: "Choose a role." };
  }

  try {
    const user = await createUser({ email, fullName, password, role });
    if (user === null) {
      return { status: "error", message: "Could not create the account." };
    }
    revalidatePath("/users");
    return { status: "ok", message: `Created ${user.email} as ${user.role}.` };
  } catch (error) {
    if (error instanceof ApiError) return { status: "error", message: error.message };
    throw error;
  }
}

export async function changeRoleAction(
  _prev: UserActionState,
  form: FormData,
): Promise<UserActionState> {
  const id = String(form.get("userId") ?? "");
  const role = String(form.get("role") ?? "") as UserRole;

  if (!id || !ROLES.includes(role)) {
    return { status: "error", message: "Missing user or role." };
  }

  try {
    const user = await updateUserRole(id, role);
    if (user === null) {
      return { status: "error", message: "That user no longer exists." };
    }
    revalidatePath("/users");
    return { status: "ok", message: `${user.email} is now ${user.role}.` };
  } catch (error) {
    if (error instanceof ApiError) return { status: "error", message: error.message };
    throw error;
  }
}
