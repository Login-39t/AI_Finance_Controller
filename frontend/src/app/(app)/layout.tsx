import { AppHeader } from "@/components/app-header";
import { latestRun } from "@/lib/api";
import { currentUser } from "@/lib/session";

/**
 * App shell. Nav on one line, 56px tall.
 *
 * A reconciliation console gives its vertical space to rows, not chrome.
 * The run context sits in the bar because every number on every screen
 * below is scoped to a run, and a user who forgets which run they are
 * looking at will misread every figure on the page. The bar itself is
 * pinned to the top and reacts to scroll - see AppHeader.
 */

const NAV = [
  { href: "/overview", label: "Overview" },
  { href: "/exceptions", label: "Exceptions" },
  { href: "/imports", label: "Imports" },
  { href: "/runs", label: "Runs" },
  { href: "/explorer", label: "Explorer" },
] as const;

//: Admin-only destinations, appended to the nav when the signed-in user is
//: an admin. The page and the API both refuse a non-admin regardless; this
//: only decides whether the link is shown.
const ADMIN_NAV = [{ href: "/users", label: "Users" }] as const;

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // Read rather than hardcoded. A stale run id in the chrome is worse
  // than none: it silently tells the user their figures came from a run
  // that is not the one they are looking at.
  let run = null;
  try {
    run = await latestRun();
  } catch {
    /* the pages below render their own API-unreachable state */
  }

  // Middleware guarantees a session before this renders, so a missing
  // user here means the cookie was tampered with rather than absent.
  const user = await currentUser();
  const navItems = user?.role === "admin" ? [...NAV, ...ADMIN_NAV] : NAV;

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <AppHeader
        navItems={navItems}
        runId={run?.id ?? null}
        user={user ? { fullName: user.fullName, role: user.role } : null}
      />

      {/* min-w-0 is load-bearing. Without it a flex child is sized by its
          widest content, so the 980px-wide queue table pushed the whole
          document sideways instead of scrolling inside its own container -
          the page scrolled horizontally, which the design rules forbid. */}
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
