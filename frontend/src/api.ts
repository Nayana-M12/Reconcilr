export type Summary = {
  matches: number; open_exceptions: number; resolved_exceptions: number; pending_adjustments: number;
};
export type Exception = {
  id: string; type: string; status: string; severity: string; description: string;
  invoice_id: string | null; po_id: string | null; payment_id: string | null;
  evidence: { id: string; record_type: string; record_id: string; note: string }[];
};
export type Adjustment = {
  id: string; exception_id: string; proposed_amount: string; calculation: {
    record_ids: string[]; amounts: Record<string, string>; formula: string; result: string; note?: string | null;
  }; status: string; required_approvers: string[]; approval_steps: {
    id: string; role: string; decision: string; comment?: string | null; decided_at?: string | null;
  }[];
};
export type AuditEntry = {
  id: string; timestamp: string; actor: string; action: string; entity_type: string;
  entity_id: string; inputs: Record<string, unknown>; formula: string; output: Record<string, unknown>;
};
export type ImportResponse = {
  record_type: string; source_file: string; imported: number; rejected: number;
  duplicates: number; errors: Record<string, unknown>[]; ids: string[];
};
export type AuthUser = { username: string; role: string };
type LoginResponse = { access_token: string; token_type: string; role: string };

const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
let authToken = sessionStorage.getItem("reconcilr_token");

export const getAuthToken = () => authToken;
export const setAuthToken = (token: string) => {
  authToken = token;
  sessionStorage.setItem("reconcilr_token", token);
};
export const clearAuthToken = () => {
  authToken = null;
  sessionStorage.removeItem("reconcilr_token");
};
const decodeUser = (token: string | null): AuthUser | null => {
  if (!token) return null;
  try {
    const payload = token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/");
    const padded = payload.padEnd(Math.ceil(payload.length / 4) * 4, "=");
    const claims = JSON.parse(atob(padded)) as Partial<AuthUser>;
    return typeof claims.username === "string" && typeof claims.role === "string"
      ? { username: claims.username, role: claims.role }
      : null;
  } catch {
    return null;
  }
};
export const getAuthUser = () => decodeUser(authToken);

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options: { redirectOnUnauthorized?: boolean } = {},
): Promise<T> {
  try {
    const headers = new Headers(init?.headers);
    if (!(init?.body instanceof FormData) && !headers.has("Content-Type")) {
      headers.set("Content-Type", "application/json");
    }
    if (authToken && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${authToken}`);
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init, headers,
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try { const body = await response.json(); detail = body.detail || detail; } catch { /* non-JSON response */ }
      if (response.status === 401 && options.redirectOnUnauthorized !== false) {
        clearAuthToken();
        window.location.assign(`/login?message=${encodeURIComponent("Your session expired. Sign in again.")}`);
      }
      if (response.status === 403) throw new ApiError(403, "You do not have permission for this action.");
      throw new ApiError(response.status, `${response.status}: ${detail}`);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof TypeError) throw new Error("Backend is offline. Start the FastAPI server and try again.");
    throw error;
  }
}
export const login = async (username: string, password: string) => {
  const result = await request<LoginResponse>("/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  }, { redirectOnUnauthorized: false });
  setAuthToken(result.access_token);
  return getAuthUser();
};
export const getSummary = () => request<Summary>("/summary");
export const getHealth = () => request<{ status: string }>("/health");
export const importRecords = (recordType: string, file: File) => {
  const body = new FormData(); body.append("file", file);
  return request<ImportResponse>(`/imports/${encodeURIComponent(recordType)}`, { method: "POST", body });
};
export const getMatches = () => request<Record<string, unknown>[]>("/matching/results");
export const runMatching = () => request<Record<string, unknown>>("/matching/run", { method: "POST" });
export const runExceptions = () => request<Record<string, unknown>>("/exceptions/run", { method: "POST" });
export const proposeAdjustments = () => request<Adjustment[]>("/adjustments/propose", { method: "POST" });
export const getExceptions = (filters: Record<string, string>) => request<Exception[]>(`/exceptions?${new URLSearchParams(filters)}`);
export const getException = (id: string) => request<Exception>(`/exceptions/${id}`);
export const getAdjustments = () => request<Adjustment[]>("/adjustments");
export const getAdjustment = (id: string) => request<Adjustment>(`/adjustments/${id}`);
export const decideAdjustment = (id: string, body: { role: string; decision: "approved" | "rejected"; comment: string }) =>
  request<Adjustment>(`/adjustments/${id}/decision`, { method: "POST", body: JSON.stringify(body) });
export const getAudit = (entityType = "", limit = 100) =>
  request<AuditEntry[]>(`/audit?${new URLSearchParams({ ...(entityType ? { entity_type: entityType } : {}), limit: String(limit) })}`);
