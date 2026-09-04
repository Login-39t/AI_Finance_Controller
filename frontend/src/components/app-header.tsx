"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { GraphIcon } from "@phosphor-icons/react/dist/ssr";

import { UserMenu } from "@/components/user-menu";
import { AppNav, type NavItem } from "@/components/app-nav";
import type { Role } from "@/lib/types";

/**
 * The app bar, pinned to the top and reactive to scroll.
 *
 * It never leaves the top edge - `sticky top-0` with a high z-index, so it
 * sits above every panel below it. What changes is only its surface: at
 * the very top it sits flat against the page, sharing the page background
 * with no seam; the moment the content scrolls beneath it, it lifts into a
 * translucent, blurred glass with a hairline and a soft shadow, so the
 * rows sliding under it read as *under* it rather than merged with it.
 *
 * The scroll state is the only reason this is a client component. It is a
 * single boolean toggled by a passive listener, and every visual change is
 * a CSS transition, so the animation costs nothing per frame.
 */
export function AppHeader({
  navItems,
  runId,
  user,
}: {
  navItems: readonly NavItem[];
  runId: string | null;
  user: { fullName: string; role: Role } | null;
}) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    // A small threshold, not zero: a one-pixel rubber-band on trackpads
    // should not flip the bar. rAF-coalesced so a fast scroll fires the
    // state change once per frame at most.
    let frame = 0;
    const onScroll = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        setScrolled(window.scrollY > 6);
      });
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame) cancelAnimationFrame(frame);
    };
  }, []);

  return (
    <header
      className="sticky top-0 z-40 flex h-14 shrink-0 items-center justify-between gap-4 px-4 sm:gap-6"
      style={{
        // Flat and opaque at the top (blends into the page), translucent
        // glass once lifted. Both transition together for the blend.
        background: scrolled ? "var(--surface)" : "var(--bg)",
        backdropFilter: scrolled ? "blur(16px) saturate(140%)" : "blur(0px)",
        WebkitBackdropFilter: scrolled ? "blur(16px) saturate(140%)" : "blur(0px)",
        borderBottom: `1px solid ${scrolled ? "var(--line)" : "transparent"}`,
        boxShadow: scrolled ? "0 10px 30px -12px rgba(0, 0, 0, 0.55)" : "none",
        transition:
          "background 300ms ease, backdrop-filter 300ms ease, " +
          "box-shadow 300ms ease, border-color 300ms ease",
      }}
    >
      <div className="flex flex-1 items-center justify-start">
        <Link href="/overview" className="flex shrink-0 items-center gap-2 whitespace-nowrap">
          <GraphIcon size={17} weight="duotone" style={{ color: "var(--flag)" }} />
          <span
            className="text-[13.5px] font-semibold tracking-tight"
            style={{ color: "var(--ink)" }}
          >
            TallyProof
          </span>
        </Link>
      </div>

      <AppNav items={navItems} />

      <div className="flex flex-1 min-w-0 items-center justify-end gap-4 whitespace-nowrap">
        {runId && (
          <>
            <span className="label hidden lg:inline">Run</span>
            <span
              className="num hidden truncate text-[12px] lg:inline"
              style={{ color: "var(--ink-2)" }}
              title={runId}
            >
              {runId}
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
  );
}
