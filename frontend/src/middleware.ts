import { NextResponse, type NextRequest } from "next/server";

/**
 * The route guard and the silent refresh.
 *
 * Middleware rather than a per-page check, for one reason that matters: a
 * page added later is protected by default. A guard you have to remember
 * to add is a guard that eventually gets forgotten, and the page that
 * forgets it is the one that leaks.
 *
 * The refresh lives here because middleware is the only place that runs
 * before a render *and* can set a cookie. A Server Component cannot
 * persist a rotated token, so refreshing there would re-refresh on every
 * single request - and with reuse detection on the API side, that would
 * look like an attack.
 */

//: Public routes. /register lets a visitor self-provision an analyst
//: account; /session-expired clears a dead session and forwards to
//: /login, so it must be reachable *with* a (dead) cookie present.
const PUBLIC_PATHS = ["/login", "/register", "/session-expired"];

const API =
  process.env.API_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";

const ACCESS_COOKIE = "lg_access";
const REFRESH_COOKIE = "lg_refresh";
const USER_COOKIE = "lg_user";

function toLogin(request: NextRequest): NextResponse {
  const url = request.nextUrl.clone();
  url.pathname = "/login";
  // Where they were headed, so signing in lands them there rather than
  // on a default page they then have to navigate away from.
  url.search = `?next=${encodeURIComponent(request.nextUrl.pathname)}`;

  const response = NextResponse.redirect(url);
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE, USER_COOKIE]) {
    response.cookies.delete(name);
  }
  return response;
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const access = request.cookies.get(ACCESS_COOKIE)?.value;
  const refresh = request.cookies.get(REFRESH_COOKIE)?.value;

  // `/` is the public marketing landing page; it must be matched exactly,
  // since every path starts with "/".
  const isLanding = pathname === "/";
  if (isLanding || PUBLIC_PATHS.some((p) => pathname.startsWith(p))) {
    // A signed-in visitor has no use for the landing or the auth pages;
    // send them into the app. Never redirect /session-expired, which
    // exists precisely to be reached while a (dead) cookie is still set.
    if (access) {
      const to = isLanding ? "/overview" : null;
      const authPage = pathname.startsWith("/login") || pathname.startsWith("/register");
      const dest = to ?? (authPage ? "/exceptions" : null);
      if (dest) {
        const url = request.nextUrl.clone();
        url.pathname = dest;
        url.search = "";
        return NextResponse.redirect(url);
      }
    }
    return NextResponse.next();
  }

  if (access) return NextResponse.next();
  if (!refresh) return toLogin(request);

  // The access token expired but the session has not. Rotate it, and
  // carry the new pair forward on this same response so the render that
  // follows is already authenticated.
  let refreshed: Response;
  try {
    refreshed = await fetch(`${API}/v1/auth/refresh`, {
      method: "POST",
      headers: { Cookie: `lg_refresh=${refresh}` },
      cache: "no-store",
    });
  } catch {
    // The API being down is not a reason to destroy a valid session.
    // Let the page render its own API-unreachable state instead.
    return NextResponse.next();
  }

  if (!refreshed.ok) return toLogin(request);

  const body = (await refreshed.json()) as {
    accessToken: string;
    expiresIn: number;
    user: unknown;
  };
  const setCookie = refreshed.headers.get("set-cookie") ?? "";
  const rotated = /(?:^|,\s*)lg_refresh=([^;]+)/.exec(setCookie)?.[1];

  // The freshly minted token has to reach *this* request's render, not
  // just the next one: a cookie set on the response is not visible to the
  // Server Components rendering now. So it travels forward as a header
  // and is persisted as a cookie in the same pass.
  const headers = new Headers(request.headers);
  headers.set("x-lg-access", body.accessToken);

  const response = NextResponse.next({ request: { headers } });
  const secure = process.env.NODE_ENV === "production";
  const common = { httpOnly: true, sameSite: "lax", secure, path: "/" } as const;

  response.cookies.set(ACCESS_COOKIE, body.accessToken, {
    ...common,
    maxAge: body.expiresIn,
  });
  if (rotated) {
    response.cookies.set(REFRESH_COOKIE, rotated, { ...common, maxAge: 7 * 24 * 3600 });
  }
  response.cookies.set(USER_COOKIE, encodeURIComponent(JSON.stringify(body.user)), {
    ...common,
    maxAge: 7 * 24 * 3600,
  });

  return response;
}

export const config = {
  // Everything except Next's own assets and the favicon. Health of the
  // API is not this app's concern; the pages handle that.
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
