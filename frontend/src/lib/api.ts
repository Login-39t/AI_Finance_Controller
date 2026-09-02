/**
 * The API client.
 *
 * Server Components call these directly, so the fetches run on the Next.js
 * server and the browser never receives the dataset - which is the whole
 * reason the queue can render thousands of rows without a memory ceiling
 * on a laptop.
 *
 * Two behaviours worth stating, because they shape every page:
 *
 * **404 is a state, not an error.** Before any run exists the API returns
 * 404 for the queue rather than an empty list, because "no run has
 * happened" and "nothing needs reconciling" are very different claims and
 * only one of them is reassuring. These helpers turn that into `null` so
 * a page can render the honest empty state.
 *
 * **`cache: "no-store"` everywhere.** Reconciliation state changes as runs
 * complete and decisions land. A cached queue would show an analyst work
 * that is already done.
 *
 * **Every call carries the session token.** The API refuses an anonymous
 * request on every domain endpoint, so the bearer is attached here rather
 * than at each call site - one place to get right, and a helper added
 * later cannot forget it.
 */

import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { accessToken } from "./session";
import type {
  AiInvestigation,
  CasePacket,
  ExceptionCase,
} from "./types";

const BASE =
  process.env.API_URL ??
  process.env.NEXT_PUBLIC_API_URL ??
  "http://127.0.0.1:8000";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string,
    message: string,
  ) {
    super(message);
  }
}

/**
 * The bearer for this request.
 *
 * Normally the session cookie. On the one render that follows a silent
 * refresh, middleware forwards the freshly minted token as a header,
 * because a cookie it just set is not yet readable here.
 */
async function bearer(): Promise<string | null> {
  const forwarded = (await headers()).get("x-lg-access");
  return forwarded ?? (await accessToken());
}

async function request<T>(path: string, init?: RequestInit): Promise<T | null> {
  const token = await bearer();

  let response: Response;
  try {
    response = await fetch(`${BASE}${path}`, {
      cache: "no-store",
      ...init,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(init?.headers ?? {}),
      },
    });
  } catch {
    // The API being down is a condition a page must render, not a crash.
    throw new ApiError(0, "API_UNREACHABLE", `cannot reach the API at ${BASE}`);
  }

  if (response.status === 404) return null;

  if (response.status === 401) {
    // Middleware already tried to refresh before this render. Reaching
    // here means the session is genuinely gone, so send the user to sign
    // in rather than rendering a page full of error cards.
    redirect("/login");
  }

  if (!response.ok) {
    let code = "HTTP_ERROR";
    let detail = response.statusText;
    try {
      const body = await response.json();
      code = body.code ?? code;
      detail = body.detail ?? detail;
    } catch {
      /* a non-JSON error body is still an error */
    }
    throw new ApiError(response.status, code, detail);
  }

  return (await response.json()) as T;
}

// --------------------------------------------------------------------------
// Runs
// --------------------------------------------------------------------------

export interface RunMetrics {
  recordsProcessed: number;
  groups: number;
  autoResolved: number;
  pendingReview: number;
  exceptions: number;
  grossProcessedMinor: string;
  unresolvedValueMinor: string;
  stageTimingsMs: Record<string, number>;
}

export interface Run {
  id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  rulesetVersion: string;
  currentStage: string | null;
  progressPct: number;
  createdAt: string;
  startedAt: string | null;
  completedAt: string | null;
  error: string | null;
  metrics: RunMetrics | null;
}

export const listRuns = () => request<Run[]>("/v1/reconciliation-runs");
export const getRun = (id: string) => request<Run>(`/v1/reconciliation-runs/${id}`);
export const latestRun = () => request<Run>("/v1/reconciliation-runs/latest");

// --------------------------------------------------------------------------
// Imports
// --------------------------------------------------------------------------

export interface ImportRejection {
  rowNumber: number;
  columnName: string | null;
  rawValue: string | null;
  errorCode: string;
  errorMessage: string;
}

export interface ImportRecord {
  id: string;
  dataset: string;
  filename: string;
  status: "pending" | "validating" | "completed" | "failed" | "duplicate";
  rowsTotal: number;
  rowsAccepted: number;
  rowsRejected: number;
  createdAt: string;
  completedAt: string | null;
  error: string | null;
  rejections?: ImportRejection[];
}

export interface DatasetInfo {
  dataset: string;
  sourceSystem: string;
  requiredColumns: string[];
}

export const listImports = () => request<ImportRecord[]>("/v1/imports");
export const getImport = (id: string) =>
  request<ImportRecord>(`/v1/imports/${id}`);
export const listDatasets = () =>
  request<{ datasets: DatasetInfo[] }>("/v1/imports/datasets");

// --------------------------------------------------------------------------
// Exceptions
// --------------------------------------------------------------------------

export interface CasePage {
  items: ExceptionCase[];
  nextCursor: string | null;
  total: number;
}

export interface QueueFilters {
  runId?: string;
  caseType?: string;
  severity?: string;
  minAmountMinor?: number;
  cursor?: string;
  limit?: number;
}

export function listExceptions(filters: QueueFilters = {}) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  const query = params.toString();
  return request<CasePage>(`/v1/exceptions${query ? `?${query}` : ""}`);
}

export const getCase = (id: string) => request<CasePacket>(`/v1/exceptions/${id}`);

export const requestInvestigation = (id: string) =>
  request<AiInvestigation>(`/v1/exceptions/${id}/investigate`, { method: "POST" });

export interface DecisionBody {
  resolution: "approved" | "rejected" | "overridden" | "dismissed";
  reasonCode?: string | null;
  note?: string;
}

export const decideCase = (id: string, body: DecisionBody) =>
  request<CasePacket>(`/v1/exceptions/${id}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

// --------------------------------------------------------------------------
// Health
// --------------------------------------------------------------------------

export interface Readiness {
  status: "ready" | "degraded";
  checks: {
    database: { reachable: boolean; error?: string; serverVersion?: string };
    ai: { enabled: boolean; model: string | null };
  };
}

export async function readiness(): Promise<Readiness | null> {
  try {
    // /readyz answers 503 when degraded, which is information rather than
    // a failure - so it is read directly instead of through `request`.
    const response = await fetch(`${BASE}/readyz`, { cache: "no-store" });
    return (await response.json()) as Readiness;
  } catch {
    return null;
  }
}

export const apiBaseUrl = BASE;
