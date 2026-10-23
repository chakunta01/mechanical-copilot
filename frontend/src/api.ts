// Typed API client with JWT handling.

const API = "/api/v1";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: string;
  is_active: boolean;
}

export interface Citation {
  document_id: string;
  title: string;
  source_ref: string;
  version: string;
  chunk_id: string;
  score: number;
  snippet: string;
}

export interface PlanOperation {
  op_number: number;
  name: string;
  machine: string;
  tooling: string[];
  parameters: Record<string, string | number>;
  description: string;
  inspection_checkpoints: string[];
  citations: Citation[];
}

export interface PlanBody {
  plan_title: string;
  summary: string;
  operations: PlanOperation[];
  inspection_plan: {
    characteristic: string;
    method: string;
    frequency: string;
    acceptance_criteria: string;
  }[];
  assumptions: string[];
  risk_notes: string[];
}

export interface ProcessPlan {
  id: string;
  title: string;
  part_number: string;
  material: string;
  quantity: number;
  requirements: Record<string, unknown>;
  plan: PlanBody;
  status: string;
  version: number;
  validation: {
    ok: boolean;
    errors: { rule_id: string; severity: string; message: string; field: string }[];
    warnings: { rule_id: string; severity: string; message: string; field: string }[];
  };
  grounding: {
    citation_count: number;
    operations_with_citations: number;
    total_operations: number;
    unsupported_claims: string[];
  };
  rejected_reason: string;
  created_at: string;
  updated_at: string;
}

export interface Defect {
  defect_type: string;
  confidence: number;
  severity: string;
  location: string;
  bbox?: number[] | null;
  evidence: string;
  below_threshold?: boolean;
}

export interface Inspection {
  id: string;
  part_number: string;
  image_path: string;
  thumbnail_path: string;
  status: string;
  quality: {
    passed: boolean;
    checks: Record<string, { passed: boolean; detail: string }>;
    metrics: Record<string, number>;
  };
  result: {
    verdict?: string;
    confidence?: number;
    defects?: Defect[];
    explanation?: string;
    recommended_disposition?: string;
    references?: Citation[];
  };
  disposition: string;
  reviewed_by: string;
  created_at: string;
}

export interface DocumentRec {
  id: string;
  title: string;
  doc_type: string;
  source_ref: string;
  version: string;
  status: string;
  chunk_count: number;
  error: string;
  created_at: string;
}

export class ApiError extends Error {
  code: string;
  status: number;
  constructor(message: string, code: string, status: number) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

function token(): string | null {
  return localStorage.getItem("copilot.access");
}

async function refreshTokens(): Promise<boolean> {
  const refresh = localStorage.getItem("copilot.refresh");
  if (!refresh) return false;
  const r = await fetch(`${API}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!r.ok) return false;
  const pair: TokenPair = await r.json();
  localStorage.setItem("copilot.access", pair.access_token);
  localStorage.setItem("copilot.refresh", pair.refresh_token);
  return true;
}

async function request<T>(method: string, path: string, body?: unknown, isForm = false): Promise<T> {
  const headers: Record<string, string> = {};
  const t = token();
  if (t) headers["Authorization"] = `Bearer ${t}`;
  let payload: BodyInit | undefined;
  if (body !== undefined) {
    if (isForm) {
      payload = body as BodyInit;
    } else {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(body);
    }
  }

  let r = await fetch(`${API}${path}`, { method, headers, body: payload });
  if (r.status === 401 && token() && !path.startsWith("/auth/")) {
    const ok = await refreshTokens();
    if (ok) {
      headers["Authorization"] = `Bearer ${token()}`;
      r = await fetch(`${API}${path}`, { method, headers, body: payload });
    }
  }

  if (r.status === 204) return undefined as T;
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const err = (data as { error?: { code: string; message: string } }).error;
    throw new ApiError(err?.message ?? `Request failed (${r.status})`, err?.code ?? "unknown", r.status);
  }
  return data as T;
}

export const api = {
  // auth
  register: (email: string, password: string, fullName: string) =>
    request<TokenPair>("POST", "/auth/register", { email, password, full_name: fullName }),
  login: (email: string, password: string) => request<TokenPair>("POST", "/auth/login", { email, password }),
  me: () => request<User>("GET", "/auth/me"),

  // documents
  createDocument: (payload: { title: string; doc_type: string; source_ref: string; version: string; content: string }) =>
    request<DocumentRec>("POST", "/documents", payload),
  uploadDocument: async (file: File, docType: string, sourceRef: string) => {
    const form = new FormData();
    form.append("file", file);
    const t = token();
    const r = await fetch(
      `/api/v1/documents/upload?title=&doc_type=${docType}&source_ref=${encodeURIComponent(sourceRef)}`,
      { method: "POST", headers: t ? { Authorization: `Bearer ${t}` } : {}, body: form },
    );
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new ApiError(data?.error?.message ?? "Upload failed", "upload", r.status);
    }
    return (await r.json()) as DocumentRec;
  },
  listDocuments: (q = "") => request<{ items: DocumentRec[]; total: number }>("GET", `/documents?q=${encodeURIComponent(q)}`),
  deleteDocument: (id: string) => request<void>("DELETE", `/documents/${id}`),
  search: (query: string) => request<{ query: string; chunks: Citation[] }>("POST", "/documents/search", { query }),

  // plans
  generatePlan: (requirements: Record<string, unknown>, title?: string) =>
    request<ProcessPlan>("POST", "/plans/generate", { requirements, title }),
  listPlans: (status = "", pn = "") =>
    request<{ items: ProcessPlan[]; total: number }>(
      "GET",
      `/plans?status=${encodeURIComponent(status)}&part_number=${encodeURIComponent(pn)}`,
    ),
  getPlan: (id: string) => request<ProcessPlan>("GET", `/plans/${id}`),
  decidePlan: (id: string, action: string, comment = "", revisedPlan?: PlanBody) =>
    request<ProcessPlan>("POST", `/plans/${id}/decision`, { action, comment, revised_plan: revisedPlan }),
  duplicatePlan: (id: string) => request<ProcessPlan>("POST", `/plans/${id}/duplicate`),
  planApprovals: (id: string) =>
    request<{ items: { id: string; action: string; actor_name: string; comment: string; created_at: string }[] }>(
      "GET",
      `/plans/${id}/approvals`,
    ),

  // inspections
  analyzeImage: async (file: File, partNumber: string) => {
    const form = new FormData();
    form.append("file", file);
    const t = token();
    const r = await fetch(`/api/v1/inspections/analyze?part_number=${encodeURIComponent(partNumber)}`, {
      method: "POST",
      headers: t ? { Authorization: `Bearer ${t}` } : {},
      body: form,
    });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      throw new ApiError(data?.error?.message ?? "Analysis failed", "analysis", r.status);
    }
    return (await r.json()) as Inspection;
  },
  listInspections: (pn = "") =>
    request<{ items: Inspection[]; total: number }>("GET", `/inspections?part_number=${encodeURIComponent(pn)}`),
  getInspection: (id: string) => request<Inspection>("GET", `/inspections/${id}`),
  setDisposition: (id: string, disposition: string, notes: string) =>
    request<Inspection>("POST", `/inspections/${id}/disposition`, { disposition, notes }),

  // feedback / qa / dashboard
  sendFeedback: (payload: { target_type: string; target_id: string; rating: number; category: string; notes: string }) =>
    request<unknown>("POST", "/feedback", payload),
  qaAsk: (question: string, threadId: string | null) =>
    request<{
      thread_id: string;
      answer: string;
      citations: Citation[];
      confidence: number;
      refused: boolean;
      refusal_reason: string;
      mode: "grounded" | "general";
    }>(
      "POST",
      "/qa/ask",
      { question, thread_id: threadId },
    ),
  dashboard: () =>
    request<{
      total_plans: number;
      plans_by_status: Record<string, number>;
      total_inspections: number;
      defect_rate: number;
      avg_plan_rating: number;
      total_documents: number;
      total_feedback: number;
      recent_approvals: { id: string; action: string; actor_name: string; created_at: string }[];
    }>("GET", "/dashboard"),
};
