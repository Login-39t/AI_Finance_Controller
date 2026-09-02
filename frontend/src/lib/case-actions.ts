"use server";

import { revalidatePath } from "next/cache";

import { ApiError, decideCase, requestInvestigation } from "./api";

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

/**
 * Requesting an AI investigation.
 *
 * A Server Action, for the same reason as the decision: the API token
 * stays on the Next.js server. The investigation is assistance, never a
 * decision - so a non-valid result (the grounding verifier rejected the
 * model's answer) is reported plainly rather than hidden, and nothing is
 * recorded as a finding. Either way the panel re-renders from the server,
 * which is the authority on what was actually stored.
 */

export interface InvestigateState {
  status: "idle" | "ok" | "rejected" | "error";
  message: string | null;
}

export async function runInvestigation(
  _prev: InvestigateState,
  form: FormData,
): Promise<InvestigateState> {
  const caseId = String(form.get("caseId") ?? "");
  if (!caseId) {
    return { status: "error", message: "Missing case id." };
  }

  try {
    const investigation = await requestInvestigation(caseId);
    if (investigation === null) {
      return { status: "error", message: "That case no longer exists." };
    }
    // The packet now carries the investigation; re-render from the server.
    revalidatePath(`/exceptions/${caseId}`);

    if (investigation.validationStatus !== "valid") {
      return {
        status: "rejected",
        message:
          "The model answered, but the grounding check rejected it. " +
          "Nothing was recorded as a finding - see the panel for why.",
      };
    }
    return {
      status: "ok",
      message: "Investigation complete. Every hypothesis below cites the evidence it rests on.",
    };
  } catch (error) {
    if (error instanceof ApiError) {
      // e.g. AI disabled, or no provider configured.
      return { status: "error", message: error.message };
    }
    throw error;
  }
}
