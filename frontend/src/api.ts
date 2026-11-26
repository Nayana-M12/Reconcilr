export type UserRole = "admin" | "analyst" | "approver" | "auditor";

export type AuthUser = {
  id: string;
  username: string;
  role: UserRole;
};

export type LoginResponse = {
  access_token: string;
  token_type: string;
  user: AuthUser;
};

export type Summary = {
  matches: number;
  open_exceptions: number;
  resolved_exceptions: number;
  pending_adjustments: number;
};

export type Exception = {
  id: string;
  type: string;
  status: string;
  severity: string;
  description: string;
  invoice_id: string | null;
  po_id: string | null;
  payment_id: string | null;
  evidence: { id: string; record_type: string; record_id: string; note: string }[];
};

export type Adjustment = {
  id: string;
  exception_id: string;
  proposed_amount: string;
  calculation: {
    record_ids: string[];
    amounts: Record<string, string>;
    formula: string;
    result: string;
    note?: string | null;
  };
  status: string;
  required_approvers: string[];
  approval_steps: {
    id: string;
    role: string;
    decision: string;
    comment?: string | null;
    decided_at?: string | null;
  }[];
};

export type AuditEntry = {
  id: string;
  timestamp: string;
  actor: string;
  action: string;
  entity_type: string;
  entity_id: string;
  inputs: Record<string, unknown>;
  formula: string;
  output: Record<string, unknown>;
};

export type ImportResponse = {
  record_type: string;
  source_file: string;
  imported: number;
  rejected: number;
  duplicates: number;
  errors: Record<string, unknown>[];
  ids: string[];
};

export type ImportPreviewResponse = {
  filename: string;
  record_type: string;
  columns: string[];
  total_rows: number;
  preview_rows: Record<string, string>[];
  required_fields: string[];
  optional_fields: string[];
  suggested_mapping: Record<string, string>;
  missing_required_fields: string[];
};

export type MappedImportResponse = {
  record_type: string;
  source_file: string;
  imported: number;
  duplicates: number;
  rejected: number;
  rejected_rows: { row: number; reason: string }[];
  ids: string[];
};

export type FieldProvenance = {
  value: string;
  page: number;
  snippet: string;
  confidence: number;
};

export type DocumentImportResponse = {
  imported: {
    filename: string;
    record_type: string;
    record_id: string;
    fields_found: Record<string, string>;
    provenance: Record<string, FieldProvenance>;
  }[];
  duplicates: {
    filename: string;
    document_type: string;
    fields_found: Record<string, string>;
    provenance: Record<string, FieldProvenance>;
    detail: string;
  }[];
  needs_review: {
    filename: string;
    document_type: string | null;
    fields_found: Record<string, string>;
    fields_missing: string[];
    provenance: Record<string, FieldProvenance>;
    errors?: Record<string, unknown>[];
  }[];
  unsupported: {
    filename: string;
    code: string;
    message: string;
  }[];
};

export type AgentClaim = {
  text: string;
  record_ids: string[];
  tool_call_refs: string[];
};

export type AgentRun = {
  id: string;
  exception_id: string;
  verdict: string;
  explanation: string;
  claims: AgentClaim[];
  tool_calls: { ref?: string; name?: string; arguments?: Record<string, unknown>; result?: unknown }[];
  source: string;
  verification_status: string;
  errors: string[];
  status: string;
  created_at: string;
};

export type EvaluationReport = {
  matching: {
    precision: number;
    recall: number;
    expected_count: number;
    actual_count: number;
    false_positives: Record<string, unknown>[];
    false_negatives: Record<string, unknown>[];
  };
  duplicates: {
    detection_rate: number;
    false_positives: number;
  };
  exceptions: {
    by_type: Record<
      string,
      { expected: number; detected: number; precision: number; recall: number }
    >;
  };
  similarity: Record<
    string,
    { precision: number; recall: number; expected_count: number; actual_count: number }
  >;
  hallucination_rate: number;
  unresolved_correctness: number;
  extraction_accuracy: number | null;
  extraction_by_field?: Record<string, { correct: number; total: number; accuracy: number }>;
  extraction_status: string;
};

export class ApiError extends Error {
  status: number;
  detail: string;
  isOffline: boolean;

  constructor(message: string, status: number, detail: string, isOffline = false) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.isOffline = isOffline;
  }
}

const TOKEN_KEY = "reconcilr_auth_token";
const USER_KEY = "reconcilr_auth_user";

let memoryToken: string | null = null;
let memoryUser: AuthUser | null = null;
const unauthorizedListeners = new Set<(reason: string) => void>();

function loadSession() {
  if (memoryToken !== null) return;
  try {
    memoryToken = sessionStorage.getItem(TOKEN_KEY);
    const rawUser = sessionStorage.getItem(USER_KEY);
    memoryUser = rawUser ? (JSON.parse(rawUser) as AuthUser) : null;
  } catch {
    memoryToken = null;
    memoryUser = null;
  }
}

export function getAuthToken(): string | null {
  loadSession();
  return memoryToken;
}

export function getAuthUser(): AuthUser | null {
  loadSession();
  return memoryUser;
}

export function setAuthSession(token: string, user: AuthUser): void {
  memoryToken = token;
  memoryUser = user;
  try {
    sessionStorage.setItem(TOKEN_KEY, token);
    sessionStorage.setItem(USER_KEY, JSON.stringify(user));
  } catch {
    /* ignore storage quota errors; memory session still works */
  }
}

export function clearAuthSession(): void {
  memoryToken = null;
  memoryUser = null;
  try {
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(USER_KEY);
  } catch {
    /* ignore storage errors */
  }
}

export function onUnauthorized(listener: (reason: string) => void): () => void {
  unauthorizedListeners.add(listener);
  return () => {
    unauthorizedListeners.delete(listener);
  };
}

const BASE_URL = import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";

export async function request<T>(
  path: string,
  init?: RequestInit,
  options?: { skipAuthRedirect?: boolean },
): Promise<T> {
  const token = getAuthToken();
  const baseHeaders: Record<string, string> =
    init?.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  if (token) {
    baseHeaders.Authorization = `Bearer ${token}`;
  }
  const mergedHeaders = { ...baseHeaders, ...(init?.headers as Record<string, string> | undefined) };

  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, {
      cache: "no-store",
      ...init,
      headers: mergedHeaders,
    });
  } catch {
    throw new ApiError(
      "Backend is offline. Start the FastAPI server and try again.",
      0,
      "Backend is offline",
      true,
    );
  }

  if (!response.ok) {
    let detail = `Request failed (${response.status})`;
    try {
      const body = await response.json();
      if (body && typeof body.detail === "string") detail = body.detail;
    } catch {
      /* non-JSON response */
    }
    if (response.status === 401 && !options?.skipAuthRedirect) {
      clearAuthSession();
      unauthorizedListeners.forEach((listener) =>
        listener("Your session expired. Sign in again."),
      );
      throw new ApiError("Your session expired. Sign in again.", 401, detail);
    }
    if (response.status === 403) {
      const message =
        detail && detail !== "Request failed (403)"
          ? detail
          : "You do not have permission for this action.";
      throw new ApiError(message, 403, message);
    }
    throw new ApiError(`${response.status}: ${detail}`, response.status, detail);
  }

  return response.json() as Promise<T>;
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const res = await request<LoginResponse>(
    "/auth/login",
    {
      method: "POST",
      body: JSON.stringify({ username, password }),
    },
    { skipAuthRedirect: true },
  );
  setAuthSession(res.access_token, res.user);
  return res;
}

export const getMe = () => request<AuthUser>("/auth/me");
export const getSummary = () => request<Summary>("/summary");
export const getHealth = () => request<{ status: string }>("/health");

export const importRecords = (recordType: string, file: File) => {
  const body = new FormData();
  body.append("file", file);
  return request<ImportResponse>(`/imports/${encodeURIComponent(recordType)}`, {
    method: "POST",
    body,
  });
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
  body: { decision: "approved" | "rejected"; comment: string },
) =>
  request<Adjustment>(`/adjustments/${id}/decision`, {
    method: "POST",
    body: JSON.stringify(body),
  });

export const getAudit = (entityType = "", limit = 100) =>
  request<AuditEntry[]>(
    `/audit?${new URLSearchParams({
      ...(entityType ? { entity_type: entityType } : {}),
      limit: String(limit),
    })}`,
  );

export const previewImport = (file: File, recordType: string) => {
  const body = new FormData();
  body.append("file", file);
  body.append("record_type", recordType);
  return request<ImportPreviewResponse>("/import/preview", { method: "POST", body });
};

export const importMapped = (
  file: File,
  recordType: string,
  mapping: Record<string, string>,
  dateFormat: string,
) => {
  const body = new FormData();
  body.append("file", file);
  body.append("record_type", recordType);
  body.append("mapping", JSON.stringify(mapping));
  body.append("date_format", dateFormat);
  return request<MappedImportResponse>("/import/mapped", { method: "POST", body });
};

export const importDocuments = (files: File[]) => {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  return request<DocumentImportResponse>("/import/document", { method: "POST", body });
};

export const investigateAgent = (exceptionId?: string) =>
  request<AgentRun[]>("/agent/investigate", {
    method: "POST",
    body: JSON.stringify(exceptionId ? { exception_id: exceptionId } : {}),
  });

export const getAgentRuns = () => request<AgentRun[]>("/agent/runs");

export const acceptAgentRun = (runId: string, note = "") =>
  request<AgentRun>(`/agent/runs/${encodeURIComponent(runId)}/accept`, {
    method: "POST",
    body: JSON.stringify({ note: note || null }),
  });

export const overrideAgentRun = (runId: string, note = "") =>
  request<AgentRun>(`/agent/runs/${encodeURIComponent(runId)}/override`, {
    method: "POST",
    body: JSON.stringify({ note: note || null }),
  });

export const getEvaluationReport = () => request<EvaluationReport>("/evaluation/report");
