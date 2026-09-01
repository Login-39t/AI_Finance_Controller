import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto flex min-h-[60dvh] max-w-[46ch] flex-col justify-center px-4">
      <h1 className="text-[19px] font-semibold" style={{ color: "var(--ink)" }}>
        No such case
      </h1>
      <p className="mt-1 text-[13px]" style={{ color: "var(--ink-2)" }}>
        This identifier does not match a case in the current run. It may belong to an earlier run,
        which keeps its own results.
      </p>
      <Link href="/exceptions" className="mt-4 text-[13px]" style={{ color: "var(--flag)" }}>
        Back to exceptions
      </Link>
    </div>
  );
}
