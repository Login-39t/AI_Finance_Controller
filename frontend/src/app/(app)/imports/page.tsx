import { Panel, EmptyState } from "@/components/primitives";

export default function ImportsPage() {
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      <Panel title="Imports" subtitle="Upload and validation">
        <EmptyState
          title="Not built yet"
          body="Ingestion lands with apps/api on day 1: upload, per-row validation, and a rejection report with a reason code for every rejected row."
        />
      </Panel>
    </div>
  );
}
