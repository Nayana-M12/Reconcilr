export type Summary = {
  matches: number; open_exceptions: number; resolved_exceptions: number; pending_adjustments: number;
};
export type Exception = {
  id: string; type: string; status: string; severity: string; description: string;
  invoice_id: string | null; po_id: string | null; payment_id: string | null;
  evidence: { id: string; record_type: string; record_id: string; note: string }[];
  related: {
    invoice: { invoice_number: string; vendor_name: string; amount: string; currency: string } | null;
    purchase_order: { po_number: string; amount: string; currency: string } | null;
    payment: { amount: string; currency: string; payment_date: string } | null;
  };
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
export type ExtractionResult = {
  filename: string;
  method: string;
  fields: {
    invoice_number?: string; po_number?: string; vendor_name?: string;
    invoice_date?: string; due_date?: string; payment_date?: string;
    invoice_amount?: string; tax_amount?: string; payment_amount?: string;
    reference?: string; description?: string;
  };
  confidence: number;
  warnings: string[];
};
export type Insights = {
  volume: { total_transactions: number; invoices: number; purchase_orders: number; payments: number };
  matching: { total_matches: number; matched_invoices: number; unmatched_invoices: number; by_tier: Record<string, number>; match_rate_pct: number };
  exceptions: { total: number; open: number; resolved: number; high_risk_open: number; by_type: Record<string, number>; recurring_types: { type: string; count: number }[] };
  ai: { agent_runs: number; agent_explained: number; agent_pending_review: number; ai_suggestions: number; ai_suggestions_accepted: number };
  adjustments: { pending: number; approved: number; rejected: number };
  recent_investigations: { exception_id: string; verdict: string; status: string; created_at: string | null }[];
};
export type AgentRun = {
  id: string; exception_id: string; verdict: string; explanation: string;
  claims: Record<string, unknown>[]; tool_calls: Record<string, unknown>[];
  source: string; verification_status: string; errors: string[]; status: string; created_at: string;
};
export type DocumentCategoryRecord = {
  id: string;
  document_id?: string | null;
  invoice_number?: string | null;
  po_number?: string | null;
  payment_reference?: string | null;
  invoice_reference?: string | null;
  vendor_name: string;
  invoice_date?: string | null;
  due_date?: string | null;
  order_date?: string | null;
  delivery_date?: string | null;
  payment_date?: string | null;
  total_amount?: string | null;
  payment_amount?: string | null;
  amount?: string | number | null;
  tax_amount?: string | null;
  payment_status?: string | null;
  status?: string | null;
  payment_method?: string | null;
  item_description?: string | null;
  description?: string | null;
  quantity?: string | null;
  unit_price?: string | null;
  currency: string;
  source_file: string;
  user_id?: string | null;
};

export type CategoryResponse = {
  category: string;
  files: string[];
  source_files: string[];
  total_records: number;
  total_count: number;
  records: DocumentCategoryRecord[];
  stats: Record<string, any>;
};

export type AISuggestionItem = {
  id: string;
  kind: string;
  action?: string;
  is_actionable?: boolean;
  record_ids: string[];
  score: number;
  reason: string;
  source: string;
  status: string;
  created_at?: string | null;
  user_id?: string | null;
  invoice_number?: string;
  po_number?: string;
  vendor_name?: string;
  amount?: string;
  invoice_amount?: string;
  po_amount?: string;
  difference?: string;
  days_overdue?: number;
  due_date?: string;
  reference?: string;
  left_name?: string;
  right_name?: string;
  [key: string]: any;
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
    const response = await fetch(`${BASE_URL}${path}`, { ...init, headers });
    if (!response.ok) {
      let detail = `Request failed (${response.status})`;
      try { const body = await response.json(); detail = body.detail || detail; } catch { /* non-JSON */ }
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

export const register = async (username: string, password: string, role = "analyst") => {
  const result = await request<LoginResponse>("/register", {
    method: "POST",
    body: JSON.stringify({ username, password, role }),
  }, { redirectOnUnauthorized: false });
  setAuthToken(result.access_token);
  return getAuthUser();
};

export const logout = async () => {
  try {
    await request("/logout", { method: "POST" });
  } finally {
    clearAuthToken();
  }
};

export const getCategoryDocuments = (category: string, fileFilter?: string) =>
  request<CategoryResponse>(
    `/documents/categories/${encodeURIComponent(category)}${
      fileFilter ? `?file_filter=${encodeURIComponent(fileFilter)}` : ""
    }`
  );

export const uploadCategoryDocument = (file: File, category?: string) => {
  const body = new FormData();
  body.append("file", file);
  if (category) body.append("category", category);
  return request<{ status: string; message: string; document_id?: string; imported_count?: number }>(
    "/documents/upload",
    { method: "POST", body }
  );
};

export const getSuggestions = (status?: string) =>
  request<AISuggestionItem[]>(`/ai/suggestions${status ? `?status=${encodeURIComponent(status)}` : ""}`);

export const generateSuggestions = () =>
  request<AISuggestionItem[]>("/ai/generate", { method: "POST" });

export const acceptSuggestion = (id: string, note?: string) =>
  request<AISuggestionItem>(`/ai/suggestions/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });

export const rejectSuggestion = (id: string, note?: string) =>
  request<AISuggestionItem>(`/ai/suggestions/${id}/reject`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });

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
export const getExceptions = (filters: Record<string, string>) =>
  request<Exception[]>(`/exceptions?${new URLSearchParams(filters)}`);
export const getException = (id: string) => request<Exception>(`/exceptions/${id}`);
export const getAdjustments = () => request<Adjustment[]>("/adjustments");
export const getAdjustment = (id: string) => request<Adjustment>(`/adjustments/${id}`);
export const decideAdjustment = (
  id: string,
  body: { role: string; decision: "approved" | "rejected"; comment: string },
) => request<Adjustment>(`/adjustments/${id}/decision`, { method: "POST", body: JSON.stringify(body) });
export const getAudit = (entityType = "", limit = 100) =>
  request<AuditEntry[]>(`/audit?${new URLSearchParams({
    ...(entityType ? { entity_type: entityType } : {}),
    limit: String(limit),
  })}`);
export const extractDocument = (file: File) => {
  const body = new FormData(); body.append("file", file);
  return request<ExtractionResult>("/extract", { method: "POST", body });
};
export const getInsights = () => request<Insights>("/insights");
export const getAgentRuns = () => request<AgentRun[]>("/agent/runs");
export const investigateException = (exception_id: string | null) =>
  request<AgentRun[]>("/agent/investigate", {
    method: "POST",
    body: JSON.stringify({ exception_id }),
  });
export const acceptRun = (id: string, note?: string) =>
  request<AgentRun>(`/agent/runs/${id}/accept`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });
export const overrideRun = (id: string, note?: string) =>
  request<AgentRun>(`/agent/runs/${id}/override`, {
    method: "POST",
    body: JSON.stringify({ note: note ?? null }),
  });
