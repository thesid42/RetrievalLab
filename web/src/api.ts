import { createSampleRun, sampleDashboard } from "./sampleData";
import { normalizeDashboard, normalizeRun, type BackendDashboard, type BackendRun } from "./contracts";
import type { DashboardData, RetrievalRun } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");
const DEMO_MODE = import.meta.env.VITE_DEMO_MODE === "true";
const REQUEST_TIMEOUT_MS = Math.max(15_000, Number(import.meta.env.VITE_API_TIMEOUT_MS ?? "90000") || 90_000);

/**
 * Access keys are intentionally session-scoped. A VITE_* value is bundled into
 * every browser build, so it must never be used for API authentication.
 */
function sessionApiKey(): string {
  try {
    return globalThis.sessionStorage?.getItem("retrievallab_api_key") ?? "";
  } catch {
    return "";
  }
}

export const isDemoMode = DEMO_MODE;

export function setSessionApiKey(value: string): void {
  try {
    if (value) globalThis.sessionStorage?.setItem("retrievallab_api_key", value);
    else globalThis.sessionStorage?.removeItem("retrievallab_api_key");
  } catch {
    // Storage can be disabled by a browser privacy mode. The API remains usable
    // when the backend does not require an access key.
  }
}

export function hasSessionApiKey(): boolean {
  return Boolean(sessionApiKey());
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  const timeoutId = globalThis.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const callerSignal = init?.signal;
  const abortFromCaller = () => controller.abort();

  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        "Content-Type": "application/json",
        ...(sessionApiKey() ? { "X-API-Key": sessionApiKey() } : {}),
        ...init?.headers,
      },
    });
    const bodyText = await response.text();
    let body: unknown = null;
    if (bodyText) {
      try { body = JSON.parse(bodyText); } catch { body = bodyText; }
    }
    if (!response.ok) {
      const detail = typeof body === "object" && body !== null && "detail" in body
        ? String((body as { detail?: unknown }).detail ?? "")
        : typeof body === "string" ? body : "";
      throw new Error(detail || `API returned ${response.status}`);
    }
    return body as T;
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`The API did not respond within ${REQUEST_TIMEOUT_MS / 1000} seconds.`);
    }
    if (error instanceof TypeError) {
      throw new Error("Unable to reach the RetrievalLab API. Check that the backend is running.");
    }
    throw error;
  } finally {
    globalThis.clearTimeout(timeoutId);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

export type BackendHealth = {
  status: string;
  service?: string;
  environment?: string;
  demo_mode?: boolean;
};

export async function getHealth(): Promise<BackendHealth> {
  return request<BackendHealth>("/api/v1/health");
}

export async function runRetrieval(query: string): Promise<{ data: RetrievalRun; source: "api" | "demo" }> {
  if (DEMO_MODE) {
    await new Promise((resolve) => setTimeout(resolve, 900));
    return { data: createSampleRun(query), source: "demo" };
  }
  const data = await request<BackendRun>("/api/v1/retrieval/run", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
  return { data: normalizeRun(data), source: "api" };
}

export async function getDashboard(): Promise<{ data: DashboardData; source: "api" | "demo" }> {
  if (DEMO_MODE) {
    return { data: sampleDashboard, source: "demo" };
  }
  const data = await request<BackendDashboard>("/api/v1/dashboard");
  return { data: normalizeDashboard(data), source: "api" };
}
