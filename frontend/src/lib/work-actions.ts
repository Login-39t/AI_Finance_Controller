"use server";

import { revalidatePath } from "next/cache";

import { ApiError, apiBaseUrl, getRun, type ImportRecord, type Run } from "./api";
import { accessToken } from "./session";

/**
 * Starting runs and uploading files, from the server.
 *
 * These used to be browser `fetch` calls straight to the API. That
 * stopped being possible the moment the API required a token: the
 * session lives in an httpOnly cookie on *this* origin, so the browser
 * both cannot read it and would not send it cross-origin. Routing the
 * calls through Server Actions keeps the token server-side, which is
 * where it should have been anyway.
 */

export interface ActionResult<T> {
  ok: boolean;
  data: T | null;
  error: string | null;
}

function failed<T>(error: string): ActionResult<T> {
  return { ok: false, data: null, error };
}

export async function startRun(): Promise<ActionResult<Run>> {
  const token = await accessToken();
  if (!token) return failed("your session expired; sign in again");

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/v1/reconciliation-runs`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    return failed(`cannot reach the API at ${apiBaseUrl}`);
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    return failed(body.detail ?? `could not start a run (${response.status})`);
  }
  return { ok: true, data: body as Run, error: null };
}

/** One poll of a run's status. The panel drives the cadence. */
export async function pollRun(runId: string): Promise<ActionResult<Run>> {
  try {
    const run = await getRun(runId);
    if (run === null) return failed("that run no longer exists");
    if (run.status === "completed" || run.status === "failed") {
      revalidatePath("/exceptions");
      revalidatePath("/runs");
    }
    return { ok: true, data: run, error: null };
  } catch (error) {
    if (error instanceof ApiError) return failed(error.message);
    throw error;
  }
}

export async function uploadImport(form: FormData): Promise<ActionResult<ImportRecord>> {
  const token = await accessToken();
  if (!token) return failed("your session expired; sign in again");

  // The idempotency key travels in the form because a header cannot be
  // attached to a Server Action call. It is lifted back out here so a
  // retried upload still cannot import the same file twice.
  const key = String(form.get("idempotencyKey") ?? "");
  form.delete("idempotencyKey");

  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl}/v1/imports`, {
      method: "POST",
      // No Content-Type: fetch sets the multipart boundary itself, and
      // setting it by hand produces a body the server cannot parse.
      headers: {
        Authorization: `Bearer ${token}`,
        ...(key ? { "Idempotency-Key": key } : {}),
      },
      body: form,
      cache: "no-store",
    });
  } catch {
    return failed(`cannot reach the API at ${apiBaseUrl}`);
  }

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    return failed(body.detail ?? `upload failed (${response.status})`);
  }

  revalidatePath("/imports");
  return { ok: true, data: body as ImportRecord, error: null };
}
