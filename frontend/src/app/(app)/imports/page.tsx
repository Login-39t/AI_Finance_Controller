import { ApiError, listDatasets, listImports } from "@/lib/api";
import { EmptyState, Panel } from "@/components/primitives";
import { ImportPanel } from "@/components/import-panel";

/**
 * Ingestion: the five source types, what has been uploaded, and what each
 * upload rejected.
 *
 * The empty state names the five sources explicitly rather than showing a
 * blank table, so it is obvious what is still missing.
 */
export default async function ImportsPage() {
  let datasets = null;
  let imports = null;
  let failure: string | null = null;

  try {
    [datasets, imports] = await Promise.all([listDatasets(), listImports()]);
  } catch (error) {
    // Only ApiError is handled. `redirect()` signals by *throwing*, so
    // a bare catch swallows the bounce to sign-in and renders an
    // expired session as an unreachable API. Re-throwing anything
    // unrecognised also stops a real bug hiding behind this message.
    if (!(error instanceof ApiError)) throw error;
    failure = `${error.code}: ${error.message}`;
  }

  if (failure || !datasets) {
    return (
      <div className="mx-auto max-w-[1400px] px-4 py-5">
        <Panel title="Imports">
          <EmptyState
            title="The API is not reachable"
            body={`${failure ?? "unknown error"}. Start it with "make api" and reload.`}
          />
        </Panel>
      </div>
    );
  }

  const uploaded = new Set((imports ?? []).map((i) => i.dataset));

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      <h1 className="text-[19px] font-semibold tracking-tight" style={{ color: "var(--ink)" }}>
        Imports
      </h1>
      <p className="mt-0.5 mb-5 text-[12.5px]" style={{ color: "var(--ink-3)" }}>
        Source type is declared, never guessed from the file. A mislabelled upload errors
        rather than parsing as the wrong source.
      </p>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[340px_minmax(0,1fr)]">
        <ImportPanel datasets={datasets.datasets} />

        <div className="flex flex-col gap-4">
          <Panel
            title="Source coverage"
            subtitle={`${uploaded.size} of ${datasets.datasets.length} uploaded`}
          >
            <ul>
              {datasets.datasets.map((d, i) => (
                <li
                  key={d.dataset}
                  className="flex items-center justify-between px-4 py-2"
                  style={{ borderTop: i === 0 ? "none" : "1px solid var(--line-soft)" }}
                >
                  <span className="num text-[12.5px]" style={{ color: "var(--ink)" }}>
                    {d.dataset}
                  </span>
                  <span
                    className="text-[11.5px]"
                    style={{ color: uploaded.has(d.dataset) ? "var(--ok)" : "var(--ink-3)" }}
                  >
                    {uploaded.has(d.dataset) ? "uploaded" : "not yet imported"}
                  </span>
                </li>
              ))}
            </ul>
          </Panel>

          <Panel title="Upload history" subtitle={`${(imports ?? []).length} file(s)`}>
            {(imports ?? []).length === 0 ? (
              <EmptyState
                title="Nothing imported yet"
                body="Upload the five source exports. Generate a realistic set with the gen-data target."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full min-w-[560px] border-collapse">
                  <thead>
                    <tr className="border-b" style={{ borderColor: "var(--line)" }}>
                      <th className="label px-4 py-2 text-left" scope="col">File</th>
                      <th className="label py-2 pr-4 text-left" scope="col">Dataset</th>
                      <th className="label py-2 pr-4 text-right" scope="col">Accepted</th>
                      <th className="label py-2 pr-4 text-right" scope="col">Rejected</th>
                      <th className="label py-2 pr-4 text-left" scope="col">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(imports ?? []).map((record) => (
                      <tr
                        key={record.id}
                        className="border-b"
                        style={{ borderColor: "var(--line-soft)" }}
                      >
                        <td
                          className="num px-4 py-[7px] text-[12px]"
                          style={{ color: "var(--ink)" }}
                        >
                          {record.filename}
                        </td>
                        <td
                          className="num py-[7px] pr-4 text-[12px]"
                          style={{ color: "var(--ink-2)" }}
                        >
                          {record.dataset}
                        </td>
                        <td
                          className="num py-[7px] pr-4 text-right text-[12px]"
                          style={{ color: "var(--ok)" }}
                        >
                          {record.rowsAccepted}
                        </td>
                        <td
                          className="num py-[7px] pr-4 text-right text-[12px]"
                          style={{
                            color: record.rowsRejected ? "var(--flag)" : "var(--ink-3)",
                          }}
                        >
                          {record.rowsRejected}
                        </td>
                        <td
                          className="py-[7px] pr-4 text-[12px]"
                          style={{ color: "var(--ink-2)" }}
                        >
                          {record.status}
                          {record.error ? ` — ${record.error}` : ""}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}
