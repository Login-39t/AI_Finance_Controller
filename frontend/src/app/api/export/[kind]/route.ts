import { NextResponse, type NextRequest } from "next/server";

import { apiBaseUrl } from "@/lib/api";
import { accessToken } from "@/lib/session";

/**
 * Export downloads, proxied.
 *
 * A plain `<a href>` to the API would be the obvious implementation and
 * it cannot work: the session token is an httpOnly cookie on *this*
 * origin, so the browser neither can read it nor would send it to the
 * API's origin. Putting the token in a query string would fix the
 * mechanics and put a credential in browser history, server logs, and
 * every Referer header the page emits.
 *
 * So the download is a normal same-origin link to this handler, which
 * attaches the bearer server-side and streams the response back with its
 * `Content-Disposition` intact.
 */

const KINDS: Record<string, string> = {
  exceptions: "/v1/exports/exceptions.csv",
  matches: "/v1/exports/matches.csv",
  audit: "/v1/exports/audit.csv",
};

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ kind: string }> },
) {
  const { kind } = await params;
  const path = KINDS[kind];
  if (!path) {
    return NextResponse.json({ error: `unknown export ${kind}` }, { status: 404 });
  }

  const token = await accessToken();
  if (!token) {
    return NextResponse.redirect(new URL("/login", request.url));
  }

  // Only the filters the API actually understands are forwarded. Passing
  // the query string through wholesale would let a crafted link reach
  // parameters this route never meant to expose.
  const allowed = ["severity", "caseType", "undecidedOnly"];
  const forwarded = new URLSearchParams();
  for (const key of allowed) {
    const value = request.nextUrl.searchParams.get(key);
    if (value) forwarded.set(key, value);
  }
  const query = forwarded.toString();

  let upstream: Response;
  try {
    upstream = await fetch(`${apiBaseUrl}${path}${query ? `?${query}` : ""}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return NextResponse.json(
      { error: `cannot reach the API at ${apiBaseUrl}` },
      { status: 502 },
    );
  }

  if (!upstream.ok) {
    return NextResponse.json(
      { error: `export failed (${upstream.status})` },
      { status: upstream.status },
    );
  }

  return new NextResponse(upstream.body, {
    status: 200,
    headers: {
      "Content-Type": upstream.headers.get("content-type") ?? "text/csv",
      // Carried through verbatim so the saved file keeps the run id the
      // API put in its name.
      "Content-Disposition":
        upstream.headers.get("content-disposition") ?? `attachment; filename="${kind}.csv"`,
      "Cache-Control": "no-store",
    },
  });
}
