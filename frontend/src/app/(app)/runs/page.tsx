import { Panel, EmptyState } from "@/components/primitives";

export default function RunsPage() {
  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5">
      <Panel title="Runs" subtitle="Reconciliation history">
        <EmptyState
          title="Not built yet"
          body="Run orchestration lands on day 2: staged progress through R1 to R5, then exception detection and the auto-resolution gate."
        />
      </Panel>
    </div>
  );
}
