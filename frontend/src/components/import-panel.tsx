"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { SpinnerGapIcon, UploadSimpleIcon } from "@phosphor-icons/react/dist/ssr";

// `import type` only - a value import from api.ts would drag
// next/headers into this client bundle and fail the build.
import type { DatasetInfo, ImportRecord } from "@/lib/api";
import { uploadImport } from "@/lib/work-actions";

/**
 * Upload one source file.
 *
 * The dataset is *declared*, never sniffed from the file's contents. A
 * mislabelled upload must error rather than parse as the wrong source and
 * produce confidently wrong canonical records.
 *
 * Rejections are rendered in full, grouped by reason. One bad column
 * usually explains hundreds of rows, and showing the count per code is
 * what turns "412 rejected" into a fix.
 */
export function ImportPanel({ datasets }: { datasets: DatasetInfo[] }) {
  const router = useRouter();
  const [dataset, setDataset] = useState(datasets[0]?.dataset ?? "");
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<ImportRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = datasets.find((d) => d.dataset === dataset);

  async function upload() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);

    const body = new FormData();
    body.set("dataset", dataset);
    body.set("file", file);
    // A generated key so a retried request cannot import twice.
    body.set("idempotencyKey", crypto.randomUUID());

    const outcome = await uploadImport(body);
    if (!outcome.ok || !outcome.data) {
      setError(outcome.error ?? "upload failed");
    } else {
      setResult(outcome.data);
      router.refresh();
    }
    setBusy(false);
  }

  const byCode = new Map<string, number>();
  for (const r of result?.rejections ?? []) {
    byCode.set(r.errorCode, (byCode.get(r.errorCode) ?? 0) + 1);
  }

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
      <header className="border-b px-4 py-2.5" style={{ borderColor: "var(--line)", background: "rgba(255, 255, 255, 0.015)" }}>
        <h2 className="text-[13px] font-semibold" style={{ color: "var(--ink)" }}>
          Upload a source file
        </h2>
      </header>

      <div className="flex flex-col gap-3 px-4 py-3">
        <div className="flex flex-col gap-1">
          <label htmlFor="dataset" className="label">
            Source type, required
          </label>
          <select
            id="dataset"
            value={dataset}
            onChange={(e) => setDataset(e.target.value)}
            className="w-full border px-3 py-2 text-[12.5px] cursor-pointer"
            style={{
              borderRadius: "var(--radius)",
              borderColor: "var(--line)",
              background: "var(--surface-2)",
              color: "var(--ink)",
              backdropFilter: "blur(12px)",
            }}
          >
            {datasets.map((d) => (
              <option key={d.dataset} value={d.dataset} style={{ background: "#0f121a", color: "var(--ink)" }}>
                {d.dataset}
              </option>
            ))}
          </select>
          {selected && (
            <p className="num text-[11px]" style={{ color: "var(--ink-3)" }}>
              requires: {selected.requiredColumns.join(", ")}
            </p>
          )}
        </div>

        <div className="flex flex-col gap-1">
          <label htmlFor="file" className="label">
            CSV file
          </label>
          <input
            id="file"
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="w-full border px-2 py-1.5 text-[12.5px]"
            style={{
              borderRadius: "var(--radius)",
              borderColor: "var(--line)",
              background: "var(--surface-2)",
              color: "var(--ink)",
            }}
          />
        </div>

        <button
          type="button"
          onClick={upload}
          disabled={!file || busy}
          className="flex items-center justify-center gap-2 whitespace-nowrap px-3 py-2.5 text-[12.5px] font-medium transition-all duration-150 active:translate-y-px"
          style={{
            borderRadius: "var(--radius)",
            background: !file || busy ? "var(--surface-2)" : "var(--flag)",
            color: !file || busy ? "var(--ink-3)" : "#ffffff",
            cursor: !file || busy ? "not-allowed" : "pointer",
            boxShadow: !file || busy ? "none" : "0 4px 14px rgba(0, 112, 243, 0.35)",
          }}
        >
          {busy ? (
            <SpinnerGapIcon size={13} weight="bold" className="animate-spin" />
          ) : (
            <UploadSimpleIcon size={13} weight="bold" />
          )}
          {busy ? "Uploading" : "Upload"}
        </button>

        {error && (
          <p
            className="border-l-2 py-1.5 pl-3 text-[12px] rounded-r-[var(--radius)]"
            style={{
              borderColor: "var(--danger)",
              background: "var(--danger-wash)",
              color: "var(--danger)",
            }}
          >
            {error}
          </p>
        )}

        {result && (
          <div
            className="border-l-2 py-1.5 pl-3 rounded-r-[var(--radius)]"
            style={{
              borderColor:
                result.status === "completed"
                  ? "var(--ok)"
                  : result.status === "duplicate"
                    ? "var(--warn)"
                    : "var(--danger)",
              background:
                result.status === "completed"
                  ? "var(--ok-wash)"
                  : result.status === "duplicate"
                    ? "var(--warn-wash)"
                    : "var(--danger-wash)",
            }}
          >
            <p className="text-[12.5px] font-medium" style={{ color: "var(--ink)" }}>
              {result.filename} — {result.status}
            </p>
            {result.error ? (
              <p className="mt-0.5 text-[12px]" style={{ color: "var(--danger)" }}>
                {result.error}
              </p>
            ) : (
              <p className="num mt-0.5 text-[12px]" style={{ color: "var(--ink-2)" }}>
                {result.rowsAccepted} accepted · {result.rowsRejected} rejected ·{" "}
                {result.rowsTotal} total
              </p>
            )}

            {byCode.size > 0 && (
              <dl className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
                {[...byCode.entries()].map(([code, count]) => (
                  <div key={code} className="flex items-baseline gap-1.5">
                    <dt className="num text-[11px]" style={{ color: "var(--danger)" }}>
                      {code}
                    </dt>
                    <dd className="num text-[11.5px]" style={{ color: "var(--ink-2)" }}>
                      {count}
                    </dd>
                  </div>
                ))}
              </dl>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
