import "server-only";

import { cookies } from "next/headers";

import type { Role } from "./types";

/**
 * The session, held by the Next.js server.
 *
 * This app renders on the server, so the browser never holds a token and
 * never talks to the API directly. Both cookies below are `httpOnly`,
 * which means an XSS in this app cannot read the session - it could still
 * *act* as the user while the page is open, but it cannot exfiltrate a
 * credential to use later, and that difference is most of the damage.
 *
 * Two cookies rather than one, because they have different lifetimes and
 * different jobs:
 *
 * * `lg_access` expires with the token it holds (15 minutes), so its
 *   absence is exactly the signal "time to refresh";
 * * `lg_refresh` is the long-lived opaque token, and the API rotates it
 *   on every use.
 *
 * The refresh itself happens in `middleware.ts`, not here. A Server
 * Component cannot set a cookie during render, so a token refreshed
 * mid-render could not be persisted - it would be re-fetched on every
 * request until the page happened to be reached through an action.
 */

export const ACCESS_COOKIE = "lg_access";
export const REFRESH_COOKIE = "lg_refresh";
export const USER_COOKIE = "lg_user";

export interface SessionUser {
  id: string;
  email: string;
  fullName: string;
  role: Role;
}

/** The bearer token for outbound API calls, or null when signed out. */
export async function accessToken(): Promise<string | null> {
  return (await cookies()).get(ACCESS_COOKIE)?.value ?? null;
}

/**
 * The signed-in user, as recorded at sign-in.
 *
 * Read from a cookie rather than from `GET /v1/auth/me`, so rendering the
 * header costs no round trip. The cookie is not a credential and is not
 * trusted for anything: every authorisation decision is made by the API
 * against the access token. This only decides what the chrome says.
 */
export async function currentUser(): Promise<SessionUser | null> {
  const raw = (await cookies()).get(USER_COOKIE)?.value;
  if (!raw) return null;
  try {
    return JSON.parse(decodeURIComponent(raw)) as SessionUser;
  } catch {
    return null;
  }
}

export interface TokenResponse {
  accessToken: string;
  expiresIn: number;
  user: SessionUser;
}

/** Pull the API's rotating refresh token out of its Set-Cookie header. */
export function readRefreshCookie(response: Response): string | null {
  const header = response.headers.get("set-cookie");
  if (!header) return null;
  const match = /(?:^|,\s*)lg_refresh=([^;]+)/.exec(header);
  return match ? match[1] : null;
}

/**
 * Persist a session. Callable only from a Server Action or middleware -
 * Next.js does not allow a cookie write during a component render.
 */
export async function writeSession(
  body: TokenResponse,
  refresh: string | null,
): Promise<void> {
  const jar = await cookies();
  const secure = process.env.NODE_ENV === "production";
  const common = { httpOnly: true, sameSite: "lax", secure, path: "/" } as const;

  jar.set(ACCESS_COOKIE, body.accessToken, {
    ...common,
    // Expire with the token itself. An access cookie that outlives its
    // token would make every page render a failed API call before the
    // app noticed it needed to refresh.
    maxAge: body.expiresIn,
  });

  if (refresh) {
    jar.set(REFRESH_COOKIE, refresh, { ...common, maxAge: 7 * 24 * 3600 });
  }

  jar.set(USER_COOKIE, encodeURIComponent(JSON.stringify(body.user)), {
    ...common,
    maxAge: 7 * 24 * 3600,
  });
}

export async function clearSession(): Promise<void> {
  const jar = await cookies();
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, USER_COOKIE]) jar.delete(name);
}
