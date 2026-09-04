"use client";

import { useEffect, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { ArrowRightIcon, GraphIcon } from "@phosphor-icons/react/dist/ssr";

/**
 * The landing page's top bar - pinned and scroll-reactive, the same way
 * the app shell's bar is (see AppHeader). It sits flat over the hero at the
 * very top, sharing the page background with no seam, then lifts into
 * translucent blurred glass with a hairline and a soft shadow the moment
 * the page scrolls beneath it. Client-only for the single scroll boolean;
 * every visual change is a CSS transition.
 */
export function LandingNav({ github }: { github: string }) {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
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
      className="sticky top-0 z-40"
      style={{
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
      <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-2 px-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2">
          <GraphIcon size={19} weight="duotone" style={{ color: "var(--flag)" }} />
          <span className="text-[14px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            TallyProof
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-1 sm:gap-2">
          <a
            href={github}
            target="_blank"
            rel="noreferrer"
            className="hidden px-2.5 py-1.5 text-[12.5px] transition-colors sm:inline"
            style={{ color: "var(--ink-2)" }}
          >
            GitHub
          </a>
          <Link
            href={"/login" as Route}
            className="px-2.5 py-1.5 text-[12.5px] transition-colors"
            style={{ color: "var(--ink-2)" }}
          >
            Sign in
          </Link>
          <Link
            href={"/register" as Route}
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12.5px] font-medium transition-transform active:translate-y-px"
            style={{ borderRadius: "var(--radius)", background: "var(--flag)", color: "#fff" }}
          >
            Get started <ArrowRightIcon size={13} weight="bold" />
          </Link>
        </nav>
      </div>
    </header>
  );
}
