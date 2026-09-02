"use server";

import { revalidatePath } from "next/cache";

import { ApiError, decideCase } from "./api";

/**
 * Recording a decision.
 *
 * A Server Action rather than a browser fetch, so the token never leaves
 * the Next.js server. The API is the authority on every rule this
 * touches - role, materiality, reason code - and the shape below simply
 * carries whatever it says back to the panel.
 *
 * There is no optimistic update. A financial approval must reflect what
 * the server actually did, including a 403 from the material-amount rule.
 */

export interface DecisionState {
  status: "idle" | "ok" | "error";
  message: string | null;
}

const RESOLUTIONS = {
  approve: "approved",
  reject: "rejected",
  override: "overridden",
  dismiss: "dismissed",
} as const;

export async function submitDecision(
  _prev: DecisionState,
  form: FormData,
): Promise<DecisionState> {
  const caseId = String(form.get("caseId") ?? "");
  const action = String(form.get("action") ?? "") as keyof typeof RESOLUTIONS;
  const reasonCode = String(form.get("reasonCode") ?? "").trim();
  const note = String(form.get("note") ?? "").trim();

  const resolution = RESOLUTIONS[action];
  if (!caseId || !resolution) {
    return { status: "error", message: "Choose an action before submitting." };
  }

  try {
    const packet = await decideCase(caseId, {
      resolution,
      reasonCode: reasonCode || null,
      note,
    });
    if (packet === null) {
      return { status: "error", message: "That case no longer exists." };
    }
  } catch (error) {
    if (error instanceof ApiError) {
      return { status: "error", message: error.message };
    }
    throw error;
  }

  // The packet, the queue and the audit trail all changed.
  revalidatePath(`/exceptions/${caseId}`);
  revalidatePath("/exceptions");

  return {
    status: "ok",
    message: `Recorded as ${resolution}. The audit trail below now names you.`,
  };
}
