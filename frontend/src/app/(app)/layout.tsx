import Link from "next/link";
import { GraphIcon } from "@phosphor-icons/react/dist/ssr";

import { UserMenu } from "@/components/user-menu";
import { latestRun } from "@/lib/api";
import { currentUser } from "@/lib/session";

/**
 * App shell. Nav on one line, 56px tall.
 *
 * A reconciliation console gives its vertical space to rows, not chrome.
 * The run context sits in the bar because every number on every screen
 * below is scoped to a run, and a user who forgets which run they are
 * looking at will misread every figure on the page.
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
      <header
        className="sticky top-0 z-20 flex h-14 shrink-0 items-center justify-between gap-4 border-b px-4 sm:gap-6 backdrop-blur-md"
        style={{ background: "var(--surface)", borderColor: "var(--line)" }}
      >
        <div className="flex flex-1 items-center justify-start">
          <Link href="/overview" className="flex shrink-0 items-center gap-2 whitespace-nowrap">
            <GraphIcon size={17} weight="duotone" style={{ color: "var(--flag)" }} />
            <span
              className="text-[13.5px] font-semibold tracking-tight"
              style={{ color: "var(--ink)" }}
            >
              LedgerGraph
            </span>
          </Link>
        </div>

        <nav
          className="flex shrink-0 items-center justify-center gap-1 p-1"
          style={{
            background: "rgba(255, 255, 255, 0.03)",
            borderRadius: "var(--radius)",
            border: "1px solid var(--line-soft)",
          }}
        >
          {navItems.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="whitespace-nowrap px-3 py-1 text-[13px] font-medium transition-all duration-150 hover:bg-[rgba(255,255,255,0.06)] hover:text-[var(--ink)]"
              style={{ color: "var(--ink-2)", borderRadius: "calc(var(--radius) - 3px)" }}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="flex flex-1 min-w-0 items-center justify-end gap-4 whitespace-nowrap">
          {run && (
            <>
              <span className="label hidden lg:inline">Run</span>
              <span
                className="num hidden truncate text-[12px] lg:inline"
                style={{ color: "var(--ink-2)" }}
                title={run.id}
              >
                {run.id}
              </span>
              <span
                className="hidden h-6 w-px lg:inline-block"
                style={{ background: "var(--line)" }}
                aria-hidden
              />
            </>
          )}
          {user && <UserMenu name={user.fullName} role={user.role} />}
        </div>
      </header>

      {/* min-w-0 is load-bearing. Without it a flex child is sized by its
          widest content, so the 980px-wide queue table pushed the whole
          document sideways instead of scrolling inside its own container -
          the page scrolled horizontally, which the design rules forbid. */}
      <main className="min-w-0 flex-1">{children}</main>
    </div>
  );
}
