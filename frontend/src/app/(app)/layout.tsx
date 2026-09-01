import Link from "next/link";
import { GraphIcon } from "@phosphor-icons/react/dist/ssr";

/**
 * App shell. Nav on one line, 56px tall.
 *
 * A reconciliation console gives its vertical space to rows, not to
 * chrome. The run context sits in the bar because every number on every
 * screen below is scoped to a run, and a user who forgets which run they
 * are looking at will misread every figure on the page.
 */

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/imports", label: "Imports" },
  { href: "/runs", label: "Runs" },
  { href: "/exceptions", label: "Exceptions" },
] as const;

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-[100dvh] flex-col">
      <header
        className="sticky top-0 z-20 flex h-14 shrink-0 items-center gap-6 border-b px-4"
        style={{ background: "var(--surface)", borderColor: "var(--line)" }}
      >
        <Link href="/exceptions" className="flex items-center gap-2 whitespace-nowrap">
          <GraphIcon size={17} weight="duotone" style={{ color: "var(--flag)" }} />
          <span className="text-[13.5px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            LedgerGraph
          </span>
        </Link>

        <nav className="flex items-center gap-1 overflow-x-auto">
          {NAV.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="whitespace-nowrap px-2.5 py-1 text-[13px] transition-colors duration-100 hover:opacity-100"
              style={{ color: "var(--ink-2)", borderRadius: "var(--radius)" }}
            >
              {item.label}
            </Link>
          ))}
        </nav>

        <div className="ml-auto flex items-center gap-4 whitespace-nowrap">
          <span className="label hidden sm:inline">Run</span>
          <span className="num hidden text-[12px] sm:inline" style={{ color: "var(--ink-2)" }}>
            run_2026_03_04_0912
          </span>
          <span
            className="hidden h-6 w-px sm:inline-block"
            style={{ background: "var(--line)" }}
            aria-hidden
          />
          <span className="text-[12.5px]" style={{ color: "var(--ink-2)" }}>
            Meera Balakrishnan
          </span>
          <span className="label">Analyst</span>
        </div>
      </header>

      <main className="flex-1">{children}</main>
    </div>
  );
}
