import type { Route } from "next";
import Link from "next/link";
import {
  ArrowRightIcon,
  ArrowsLeftRightIcon,
  CheckCircleIcon,
  DownloadSimpleIcon,
  GraphIcon,
  ListChecksIcon,
  LockKeyIcon,
  RobotIcon,
  ScalesIcon,
  ShieldCheckIcon,
  SlidersIcon,
} from "@phosphor-icons/react/dist/ssr";

import { Reveal } from "@/components/reveal";

const GITHUB = "https://github.com/Login-39t/AI_Finance_Controller";

/**
 * The public landing page, at `/`.
 *
 * The front door to a dense internal product: it uses the same tokens as
 * the app - one accent, 2px corners, Plex sans and mono - but gives itself
 * the room and the motion the console withholds. Everything animated here
 * is decoration over content that reads without it, and the global
 * reduced-motion rule switches it all off.
 */

const KEYFRAMES = `
@keyframes lg-flow  { to { stroke-dashoffset: -240; } }
@keyframes lg-pulse { 0%,100% { opacity: .5 } 50% { opacity: 1 } }
@keyframes lg-glow  { 0%,100% { opacity: .18 } 50% { opacity: .42 } }
@keyframes lg-float { 0%,100% { transform: translateY(0) } 50% { transform: translateY(-7px) } }
@media (prefers-reduced-motion: no-preference) {
  .lg-flow  { animation: lg-flow 3.2s linear infinite; }
  .lg-pulse { animation: lg-pulse 3s ease-in-out infinite; }
  .lg-glow  { animation: lg-glow 6s ease-in-out infinite; }
  .lg-float { animation: lg-float 7s ease-in-out infinite; }
}
`;

const METRICS: { value: string; label: string; good?: boolean }[] = [
  { value: "0.0000", label: "False-clear rate", good: true },
  { value: "1.0000", label: "Auto-resolution precision" },
  { value: "1.0000", label: "Match F1" },
  { value: "3,571", label: "Records reconciled in ~10ms" },
  { value: "11 / 11", label: "Anomaly types caught" },
  { value: "223", label: "Cleared without a human" },
];

const PIPELINE: { step: string; title: string; body: string }[] = [
  { step: "01", title: "Ingest & validate", body: "Every raw row is preserved and checksummed. Bad amounts are quarantined, never coerced into looking valid." },
  { step: "02", title: "Normalise", body: "Money to integer paise, timestamps to UTC, IDs and statuses to one controlled vocabulary." },
  { step: "03", title: "Match", body: "Six deterministic rules run first — exact IDs, component totals, settlement-batch arithmetic." },
  { step: "04", title: "Score & gate", body: "Six conditions, all of which must hold to auto-resolve. Model confidence is an input, never an override." },
  { step: "05", title: "Investigate", body: "Grounded AI drafts the explanation; every citation is verified against the case's own evidence." },
];

const FEATURES: { icon: React.ReactNode; title: string; body: string }[] = [
  { icon: <ArrowsLeftRightIcon size={18} weight="regular" />, title: "Deterministic matching", body: "Exact, fuzzy, batch and tolerance rules R1–R6 — precise where the evidence is strong." },
  { icon: <ScalesIcon size={18} weight="regular" />, title: "The amount bridge", body: "Gross − fees − tax = net, shown line by line and balanced to the paise before anything clears." },
  { icon: <ShieldCheckIcon size={18} weight="regular" />, title: "The auto-resolve gate", body: "Six conditions guard every automatic resolution. It holds the false-clear rate at zero." },
  { icon: <RobotIcon size={18} weight="regular" />, title: "Grounded AI", body: "The model classifies and explains — only from the packet, never inventing a number or a match." },
  { icon: <CheckCircleIcon size={18} weight="regular" />, title: "Citation verification", body: "Every evidence id the model cites must resolve to a record in the case, or the answer is rejected." },
  { icon: <ListChecksIcon size={18} weight="regular" />, title: "Immutable audit trail", body: "Who, what, when, why, and which rule or model version — recorded for every decision." },
  { icon: <LockKeyIcon size={18} weight="regular" />, title: "Role-based access", body: "Analyst, reviewer, controller, admin — and a material-amount threshold the API enforces." },
  { icon: <DownloadSimpleIcon size={18} weight="regular" />, title: "Held-out metrics & exports", body: "Precision and recall measured on data the tuning never saw. Results export as exact-value CSV." },
];

function NavBar() {
  return (
    <header
      className="sticky top-0 z-30 border-b backdrop-blur"
      style={{ background: "color-mix(in srgb, var(--bg) 82%, transparent)", borderColor: "var(--line)" }}
    >
      <div className="mx-auto flex h-14 max-w-[1120px] items-center gap-2 px-5 sm:px-8">
        <Link href="/" className="flex items-center gap-2">
          <GraphIcon size={19} weight="duotone" style={{ color: "var(--flag)" }} />
          <span className="text-[14px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            TallyProof
          </span>
        </Link>
        <nav className="ml-auto flex items-center gap-1 sm:gap-2">
          <a href={GITHUB} target="_blank" rel="noreferrer"
            className="hidden px-2.5 py-1.5 text-[12.5px] transition-colors sm:inline"
            style={{ color: "var(--ink-2)" }}>
            GitHub
          </a>
          <Link href="/login" className="px-2.5 py-1.5 text-[12.5px] transition-colors"
            style={{ color: "var(--ink-2)" }}>
            Sign in
          </Link>
          <Link href="/register"
            className="flex items-center gap-1.5 px-3 py-1.5 text-[12.5px] font-medium transition-transform active:translate-y-px"
            style={{ borderRadius: "var(--radius)", background: "var(--flag)", color: "#fff" }}>
            Get started <ArrowRightIcon size={13} weight="bold" />
          </Link>
        </nav>
      </div>
    </header>
  );
}

function HeroGraph() {
  // The mark, animated: five sources, one settlement at the centre, coral
  // dashes flowing along the links that reconcile them.
  const line = (d: string, delay = 0) => (
    <path d={d} fill="none" stroke="var(--flag)" strokeWidth="1.4"
      strokeDasharray="6 10" className="lg-flow" style={{ animationDelay: `${delay}s` }} />
  );
  const node = (x: number, y: number, label: string, delay = 0) => (
    <g className="lg-pulse" style={{ animationDelay: `${delay}s` }}>
      <rect x={x - 6} y={y - 6} width="12" height="12" rx="2"
        fill="var(--surface)" stroke="var(--flag)" strokeWidth="1.4" />
      <text x={x} y={y + 22} textAnchor="middle"
        style={{ fontFamily: "var(--font-mono)", fontSize: 8.5, letterSpacing: "0.06em", fill: "var(--ink-3)" }}>
        {label}
      </text>
    </g>
  );
  return (
    <svg viewBox="0 0 460 340" className="h-auto w-full" role="img"
      aria-label="A graph linking payments, invoices, settlements, bank credits and ledger entries.">
      <defs>
        <radialGradient id="lg-hero-glow" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="var(--flag)" stopOpacity="0.9" />
          <stop offset="100%" stopColor="var(--flag)" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="240" cy="160" r="150" fill="url(#lg-hero-glow)" className="lg-glow" />
      {/* faint base links */}
      <g stroke="var(--line)" strokeWidth="1.2" fill="none">
        <path d="M70 70 L230 160" /><path d="M70 270 L230 160" />
        <path d="M230 160 L400 80" /><path d="M230 160 L400 250" />
      </g>
      {/* flowing links */}
      {line("M70 70 L230 160", 0)}
      {line("M70 270 L230 160", 0.6)}
      {line("M230 160 L400 80", 1.1)}
      {line("M230 160 L400 250", 1.6)}
      {node(70, 70, "PAYMENT", 0)}
      {node(70, 270, "INVOICE", 0.8)}
      {node(230, 160, "SETTLEMENT", 0.3)}
      {node(400, 80, "BANK", 1.2)}
      {node(400, 250, "LEDGER", 1.7)}
    </svg>
  );
}

function Cta({ href, children, primary = false, external = false }: {
  href: string; children: React.ReactNode; primary?: boolean; external?: boolean;
}) {
  const cls = "inline-flex items-center justify-center gap-1.5 px-4 py-2.5 text-[13px] font-medium transition-transform active:translate-y-px";
  const style = primary
    ? { borderRadius: "var(--radius)", background: "var(--flag)", color: "#fff" }
    : { borderRadius: "var(--radius)", background: "transparent", color: "var(--ink)", border: "1px solid var(--line)" };
  const inner = <>{children}<ArrowRightIcon size={14} weight="bold" /></>;
  return external ? (
    <a href={href} target="_blank" rel="noreferrer" className={cls} style={style}>{inner}</a>
  ) : (
    <Link href={href as Route} className={cls} style={style}>{inner}</Link>
  );
}

function SectionEyebrow({ children }: { children: React.ReactNode }) {
  return (
    <span className="label" style={{ color: "var(--flag)" }}>{children}</span>
  );
}

export default function LandingPage() {
  return (
    <div style={{ background: "var(--bg)", color: "var(--ink)", overflowX: "hidden" }}>
      <style>{KEYFRAMES}</style>
      <NavBar />

      {/* ---- Hero ---- */}
      <section className="relative mx-auto max-w-[1120px] px-5 pb-16 pt-14 sm:px-8 sm:pt-20 lg:pb-24">
        <div className="grid items-center gap-12 lg:grid-cols-[1.05fr_0.95fr]">
          <Reveal>
            <h1 className="max-w-[16ch] text-[clamp(2.2rem,5.5vw,3.6rem)] font-semibold leading-[1.05] tracking-tight"
              style={{ color: "var(--ink)" }}>
              Reconciliation that{" "}
              <span style={{ color: "var(--flag)" }}>shows its work.</span>
            </h1>
            <p className="mt-5 max-w-[52ch] text-[14.5px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
              TallyProof connects payments, settlements, bank statements, invoices and
              ledgers — matches them deterministically, explains every discrepancy with
              grounded evidence, and routes only genuine uncertainty to a human.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Cta href="/login" primary>Try the live demo</Cta>
              <Cta href="/register">Create an account</Cta>
            </div>
            <p className="mt-6 flex flex-wrap items-center gap-x-5 gap-y-1 text-[11.5px]" style={{ color: "var(--ink-3)" }}>
              <span className="flex items-center gap-1.5">
                <span className="lg-pulse inline-block h-1.5 w-1.5" style={{ background: "var(--ok)", borderRadius: 1 }} />
                Live on Render + Vercel
              </span>
              <span>·</span>
              <span>Grounded AI, citation-verified</span>
              <span>·</span>
              <span>No float in the money path</span>
            </p>
          </Reveal>

          <Reveal delay={120} className="lg-float">
            <div className="mx-auto w-full max-w-[440px]">
              <HeroGraph />
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---- The claim ---- */}
      <section className="border-y" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
        <div className="mx-auto max-w-[1120px] px-5 py-14 sm:px-8">
          <Reveal className="grid items-center gap-8 md:grid-cols-[1.4fr_1fr]">
            <div>
              <SectionEyebrow>The claim worth leading with</SectionEyebrow>
              <p className="mt-4 text-[clamp(1.25rem,2.6vw,1.75rem)] font-medium leading-snug" style={{ color: "var(--ink)" }}>
                Most reconciliation tools optimise for match rate. This one optimises for{" "}
                <span style={{ color: "var(--flag)" }}>false-clear rate</span> — the number
                of problems it wrongly declares fine.
              </p>
              <p className="mt-3 text-[13.5px]" style={{ color: "var(--ink-2)" }}>
                The target is zero, measured on a held-out partition the tuning never saw.
                Two pieces of deterministic code carry that promise: the auto-resolve gate,
                and the grounding verifier.
              </p>
            </div>
            <div className="flex flex-col items-start gap-1 border-l-2 pl-6" style={{ borderColor: "var(--ok)" }}>
              <span className="num text-[clamp(2.6rem,7vw,3.8rem)] font-semibold leading-none" style={{ color: "var(--ok)" }}>
                0.0000
              </span>
              <span className="label">False-clear rate · held-out</span>
            </div>
          </Reveal>
        </div>
      </section>

      {/* ---- Pipeline ---- */}
      <section className="mx-auto max-w-[1120px] px-5 py-16 sm:px-8 sm:py-20">
        <Reveal>
          <SectionEyebrow>How it works</SectionEyebrow>
          <h2 className="mt-3 text-[clamp(1.5rem,3.4vw,2.1rem)] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Deterministic first. AI only where it helps.
          </h2>
        </Reveal>
        <div className="mt-10 grid gap-3 md:grid-cols-5">
          {PIPELINE.map((p, i) => (
            <Reveal key={p.step} delay={i * 90}
              className="flex h-full flex-col border p-4"
              style={{ background: "var(--surface)", borderColor: "var(--line)", borderRadius: "var(--radius)" }}>
              <span className="num text-[12px]" style={{ color: "var(--flag)" }}>{p.step}</span>
              <span className="mt-2 text-[13.5px] font-semibold" style={{ color: "var(--ink)" }}>{p.title}</span>
              <span className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--ink-2)" }}>{p.body}</span>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---- Two pillars ---- */}
      <section className="border-t" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
        <div className="mx-auto grid max-w-[1120px] gap-px sm:grid-cols-2" style={{ background: "var(--line)" }}>
          <Reveal className="p-8 sm:p-12" style={{ background: "var(--bg)" }}>
            <ScalesIcon size={26} weight="duotone" style={{ color: "var(--flag)" }} />
            <h3 className="mt-4 text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
              Deterministic code owns every number.
            </h3>
            <p className="mt-2.5 max-w-[42ch] text-[13px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
              Integer paise, never floating-point money. The amount bridge shows
              gross minus fees minus tax and balances to the paise. The auto-resolve
              gate is six conditions that must all hold — and the model&apos;s
              confidence is an input to it, never an override.
            </p>
          </Reveal>
          <Reveal delay={100} className="p-8 sm:p-12" style={{ background: "var(--bg)" }}>
            <RobotIcon size={26} weight="duotone" style={{ color: "var(--flag)" }} />
            <h3 className="mt-4 text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
              AI explains — it never decides.
            </h3>
            <p className="mt-2.5 max-w-[42ch] text-[13px] leading-relaxed" style={{ color: "var(--ink-2)" }}>
              The model is handed only the case&apos;s evidence packet and asked for
              structured JSON. A grounding verifier then checks every citation against
              the case and every figure against what the engine computed. An invented
              reference is rejected, not shown.
            </p>
          </Reveal>
        </div>
      </section>

      {/* ---- Metrics ---- */}
      <section className="mx-auto max-w-[1120px] px-5 py-16 sm:px-8 sm:py-20">
        <Reveal>
          <SectionEyebrow>Measured, not asserted</SectionEyebrow>
          <h2 className="mt-3 text-[clamp(1.5rem,3.4vw,2.1rem)] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            Held-out evaluation against ground truth.
          </h2>
        </Reveal>
        <div className="mt-10 grid grid-cols-2 gap-px sm:grid-cols-3" style={{ background: "var(--line)" }}>
          {METRICS.map((m, i) => (
            <Reveal key={m.label} delay={i * 70} className="p-6" style={{ background: "var(--surface)" }}>
              <div className="num text-[clamp(1.7rem,4vw,2.4rem)] font-semibold leading-none"
                style={{ color: m.good ? "var(--ok)" : "var(--ink)" }}>
                {m.value}
              </div>
              <div className="label mt-2">{m.label}</div>
            </Reveal>
          ))}
        </div>
      </section>

      {/* ---- Features ---- */}
      <section className="border-t" style={{ borderColor: "var(--line)", background: "var(--surface)" }}>
        <div className="mx-auto max-w-[1120px] px-5 py-16 sm:px-8 sm:py-20">
          <Reveal>
            <SectionEyebrow>What&apos;s inside</SectionEyebrow>
            <h2 className="mt-3 text-[clamp(1.5rem,3.4vw,2.1rem)] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
              An auditable engine, not a black box.
            </h2>
          </Reveal>
          <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {FEATURES.map((f, i) => (
              <Reveal key={f.title} delay={(i % 4) * 80}
                className="group h-full border p-5 transition-colors"
                style={{ background: "var(--bg)", borderColor: "var(--line)", borderRadius: "var(--radius)" }}>
                <span style={{ color: "var(--flag)" }}>{f.icon}</span>
                <h3 className="mt-3 text-[13.5px] font-semibold" style={{ color: "var(--ink)" }}>{f.title}</h3>
                <p className="mt-1.5 text-[12px] leading-relaxed" style={{ color: "var(--ink-2)" }}>{f.body}</p>
              </Reveal>
            ))}
          </div>
        </div>
      </section>

      {/* ---- Final CTA ---- */}
      <section className="mx-auto max-w-[1120px] px-5 py-20 sm:px-8">
        <Reveal className="flex flex-col items-center border px-6 py-14 text-center"
          style={{ background: "var(--surface)", borderColor: "var(--flag-line)", borderRadius: "var(--radius)" }}>
          <SlidersIcon size={26} weight="duotone" style={{ color: "var(--flag)" }} />
          <h2 className="mt-4 max-w-[20ch] text-[clamp(1.6rem,4vw,2.4rem)] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
            See a close reconcile itself.
          </h2>
          <p className="mt-3 max-w-[46ch] text-[13.5px]" style={{ color: "var(--ink-2)" }}>
            Sign in to the live console — import the data, run a reconciliation, open a
            case, and watch the grounded AI investigate it, citations verified.
          </p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <Cta href="/login" primary>Open the console</Cta>
            <Cta href={GITHUB} external>View the source</Cta>
          </div>
        </Reveal>
      </section>

      {/* ---- Footer ---- */}
      <footer className="border-t" style={{ borderColor: "var(--line)" }}>
        <div className="mx-auto flex max-w-[1120px] flex-col items-center justify-between gap-3 px-5 py-8 text-[11.5px] sm:flex-row sm:px-8"
          style={{ color: "var(--ink-3)" }}>
          <div className="flex items-center gap-2">
            <GraphIcon size={15} weight="duotone" style={{ color: "var(--flag)" }} />
            <span>TallyProof — trusted because it can show its work.</span>
          </div>
          <div className="flex items-center gap-4">
            <a href={GITHUB} target="_blank" rel="noreferrer">GitHub</a>
            <Link href="/login">Sign in</Link>
            <Link href="/register">Create account</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
