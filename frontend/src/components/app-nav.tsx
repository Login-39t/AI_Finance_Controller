"use client";

import type { Route } from "next";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { motion } from "framer-motion";

export interface NavItem {
  href: string;
  label: string;
}

export function AppNav({ items }: { items: readonly NavItem[] }) {
  const pathname = usePathname();

  return (
    <nav
      className="flex shrink-0 items-center justify-center gap-1 p-1 backdrop-blur-md"
      style={{
        background: "rgba(255, 255, 255, 0.03)",
        borderRadius: "var(--radius)",
        border: "1px solid var(--line-soft)",
      }}
      aria-label="Main navigation"
    >
      {items.map((item) => {
        const isActive =
          pathname === item.href ||
          (item.href !== "/" && pathname.startsWith(item.href + "/"));

        return (
          <Link
            key={item.href}
            href={item.href as Route}
            aria-current={isActive ? "page" : undefined}
            className={`relative whitespace-nowrap px-3.5 py-1 text-[13px] font-medium transition-colors duration-150 ${
              !isActive ? "hover:text-white hover:bg-[rgba(255,255,255,0.06)]" : ""
            }`}
            style={{
              color: isActive ? "#000000" : "var(--ink-2)",
              borderRadius: "calc(var(--radius) - 3px)",
            }}
          >
            {isActive && (
              <motion.div
                layoutId="active-nav-card"
                className="absolute inset-0 shadow-sm"
                style={{
                  background: "#ffffff",
                  borderRadius: "calc(var(--radius) - 3px)",
                }}
                transition={{
                  type: "spring",
                  stiffness: 420,
                  damping: 32,
                }}
              />
            )}
            <span className="relative z-10 select-none">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
