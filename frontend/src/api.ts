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

const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const headers = init?.body instanceof FormData
      ? { ...(init?.headers || {}) }
      : { "Content-Type": "application/json", ...(init?.headers || {}) };
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init, headers,
    });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try { const body = await response.json(); detail = body.detail || detail; } catch { /* non-JSON response */ }
      throw new Error(`${response.status}: ${detail}`);
    }
    return response.json() as Promise<T>;
  } catch (error) {
    if (error instanceof TypeError) throw new Error("Backend is offline. Start the FastAPI server and try again.");
    throw error;
  }
}
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
