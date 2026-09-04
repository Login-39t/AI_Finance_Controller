import type { ReactNode } from "react";
import { formatMinor, type MinorUnits } from "@/lib/money";
import type { CaseStatus, Severity } from "@/lib/types";
import { STATUS_LABEL } from "@/lib/types";

/**
 * `Money` is the only component that renders a paise value. Everything
 * else passes the string through untouched. That is what keeps the
 * frontend structurally unable to do arithmetic on money.
 */
export function Money({
  minor,
  currency = "INR",
  symbol = true,
  signed = false,
  className = "",
}: {
  minor: MinorUnits;
  currency?: string;
  symbol?: boolean;
  signed?: boolean;
  className?: string;
}) {
  return (
    <span className={`num ${className}`}>{formatMinor(minor, currency, { symbol, signed })}</span>
  );
}

const SEVERITY_STYLE: Record<Severity, { dot: string; label: string }> = {
  critical: { dot: "var(--danger)", label: "Critical" },
  high: { dot: "var(--warn)", label: "High" },
  medium: { dot: "var(--ink-3)", label: "Medium" },
  low: { dot: "var(--line)", label: "Low" },
};

/**
 * A severity dot is real semantic state, which is the one case where a
 * coloured dot earns its place. It is never decoration here.
 */
export function SeverityMark({ severity, withLabel = false }: { severity: Severity; withLabel?: boolean }) {
  const s = SEVERITY_STYLE[severity];
  const isCritical = severity === "critical";
  return (
    <span className="inline-flex items-center gap-1.5" title={`${s.label} severity`}>
      <span
        aria-hidden
        className="inline-block h-[7px] w-[7px] shrink-0"
        style={{
          background: s.dot,
          borderRadius: "2px",
          boxShadow: isCritical ? "0 0 8px rgba(239, 68, 68, 0.7)" : undefined,
        }}
      />
      <span className="sr-only">{s.label} severity</span>
      {withLabel && (
        <span
          style={{
            color: isCritical ? "var(--danger)" : "var(--ink-2)",
            fontWeight: isCritical ? 600 : 400,
          }}
        >
          {s.label}
        </span>
      )}
    </span>
  );
}

const STATUS_TONE: Record<CaseStatus, { fg: string; bg: string }> = {
  open: { fg: "var(--ink-2)", bg: "var(--idle-wash)" },
  investigating: { fg: "var(--warn)", bg: "var(--warn-wash)" },
  pending_approval: { fg: "var(--flag)", bg: "var(--flag-wash)" },
  resolved: { fg: "var(--ok)", bg: "var(--ok-wash)" },
  dismissed: { fg: "var(--ink-3)", bg: "var(--idle-wash)" },
  unresolved: { fg: "var(--ink-2)", bg: "var(--idle-wash)" },
};

/**
 * `unresolved` is styled neutrally on purpose. Abstention is a correct
 * outcome, not a failure, and the UI must not shame the analyst for it.
 */
export function StatusPill({ status }: { status: CaseStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span
      className="inline-block whitespace-nowrap px-1.5 py-[1px] text-[11px] font-medium backdrop-blur-sm"
      style={{ color: tone.fg, background: tone.bg, borderRadius: "var(--radius)" }}
    >
      {STATUS_LABEL[status]}
    </span>
  );
}

/** Confidence band, with the number always visible next to the label. */
export function ConfidenceBadge({ value }: { value: number | null | undefined }) {
  if (value == null) {
    return <span className="num text-[11px]" style={{ color: "var(--ink-3)" }}>——</span>;
  }
  const band = value >= 0.95 ? "high" : value >= 0.75 ? "medium" : "low";
  const fg = band === "high" ? "var(--ok)" : band === "medium" ? "var(--warn)" : "var(--ink-2)";
  return (
    <span
      className="num inline-block text-[11px] font-medium"
      style={{ color: fg }}
      title={`${band} confidence band`}
    >
      {value.toFixed(2)}
    </span>
  );
}

/** A hairline-separated field. Cards are avoided; hairlines carry structure. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-2">
      <span className="label">{label}</span>
      <span style={{ color: "var(--ink)" }}>{children}</span>
    </div>
  );
}

export function Panel({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      className="border backdrop-blur-md"
      style={{
        background: "var(--surface)",
        borderColor: "var(--line)",
        borderRadius: "var(--radius)",
        boxShadow: "0 8px 32px 0 rgba(0, 0, 0, 0.37), inset 0 1px 0 0 rgba(255, 255, 255, 0.08)",
        overflow: "hidden",
      }}
    >
      <header
        className="flex flex-wrap items-baseline justify-between gap-2 border-b px-4 py-2.5"
        style={{ borderColor: "var(--line)", background: "rgba(255, 255, 255, 0.015)" }}
      >
        <div className="flex items-baseline gap-3">
          <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
            {title}
          </h2>
          {subtitle && (
            <span className="text-[12px]" style={{ color: "var(--ink-3)" }}>
              {subtitle}
            </span>
          )}
        </div>
        {actions}
      </header>
      {children}
    </section>
  );
}

export function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="px-4 py-8 text-center">
      <p className="text-[13px] font-medium" style={{ color: "var(--ink-2)" }}>
        {title}
      </p>
      <p className="mx-auto mt-1 max-w-[46ch] text-[12px]" style={{ color: "var(--ink-3)" }}>
        {body}
      </p>
    </div>
  );
}
