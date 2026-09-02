"use server";

import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { apiBaseUrl } from "./api";
import {
  REFRESH_COOKIE,
  type TokenResponse,
  clearSession,
  readRefreshCookie,
  writeSession,
} from "./session";

/**
 * Signing in and out.
 *
 * Server Actions, because a Server Action is one of only two contexts
 * Next.js allows a cookie to be written from. The other is middleware,
 * which is where the silent refresh lives.
 */

export async function signIn(
  _prev: { error: string | null },
  form: FormData,
): Promise<{ error: string | null }> {
  const email = String(form.get("email") ?? "").trim();
  const password = String(form.get("password") ?? "");

  if (!email || !password) {
    return { error: "Enter an email and a password." };
  }

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/v1/auth/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
      cache: "no-store",
    });
  } catch {
    return { error: `Cannot reach the API at ${apiBaseUrl}. Is it running?` };
  }

  if (!response.ok) {
    let detail = "Email or password is incorrect.";
    try {
      detail = (await response.json()).detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    return { error: detail };
  }

  await writeSession((await response.json()) as TokenResponse, readRefreshCookie(response));

  // Outside the try: redirect() signals by throwing, and a catch here
  // would swallow the navigation and report it as a login failure.
  redirect("/exceptions");
}

export async function signOut(): Promise<void> {
  const refresh = (await cookies()).get(REFRESH_COOKIE)?.value;

  // Tell the API first, so the whole token family is revoked server-side
  // rather than merely forgotten by this browser.
  if (refresh) {
    try {
      await fetch(`${apiBaseUrl}/v1/auth/logout`, {
        method: "POST",
        headers: { Cookie: `lg_refresh=${refresh}` },
        cache: "no-store",
      });
    } catch {
      /* the local session is cleared regardless */
    }
  }

  await clearSession();
  redirect("/login");
}
