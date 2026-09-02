import { NextResponse, type NextRequest } from "next/server";

/**
 * Clear a dead session, then go to sign-in.
 *
 * This exists because of a loop that only shows up when a token stops
 * being valid for a reason the *token itself* cannot express — the API
 * restarted and no longer knows the user id, or the account was
 * disabled. The access cookie is still present and unexpired, so:
 *
 *   page renders -> API returns 401 -> redirect("/login")
 *   -> middleware sees a present access cookie -> redirect("/exceptions")
 *   -> page renders -> ...
 *
 * The fix has to *delete* the cookie, and a Server Component cannot
 * write one. A Route Handler can. So the API client redirects here, this
 * clears the session, and only then hands over to /login — where the
 * absence of a cookie means middleware lets the page through.
 */

export async function GET(request: NextRequest) {
  const target = new URL("/login", request.url);
  target.searchParams.set("expired", "1");

  const next = request.nextUrl.searchParams.get("next");
  if (next && next.startsWith("/") && !next.startsWith("//")) {
    // Same-origin paths only. `//evil.com` parses as a protocol-relative
    // URL, so the leading-slash check alone would be an open redirect.
    target.searchParams.set("next", next);
  }

  const response = NextResponse.redirect(target);
  for (const name of ["lg_access", "lg_refresh", "lg_user"]) {
    response.cookies.delete(name);
  }
  return response;
}
