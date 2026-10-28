export interface Project {
  id: string;
  name: string;
  file_count: number;
  created_at: string;
}
export interface RuntimeHealth {
  status: string;
  ai: {
    available: boolean;
    model: string;
    models: string[];
    error?: string | null;
  };
  sandbox: { available: boolean; error?: string | null; image?: string };
}
export interface Evidence {
  id: string;
  kind: string;
  path?: string;
  line?: number;
  content: string;
  observed_at: string;
}
export interface Hypothesis {
  id: string;
  title: string;
  reasoning: string;
  confidence: number;
  supporting_evidence: string[];
  contradicting_evidence: string[];
  diagnostic_checks: unknown[];
  score?: number;
}
export interface TestResult {
  status: string;
  exit_code: number | null;
  stdout: string;
  stderr: string;
  duration_seconds: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  tests: { nodeid: string; outcome: string }[];
}
export interface InvestigationEvent {
  id: string | number;
  type: string;
  message: string;
  created_at: string;
  data?: Record<string, unknown>;
}
export interface InvestigationSummary {
  id: string;
  project_id: string;
  project_name: string;
  status: string;
  created_at: string;
  summary?: string | null;
}
export interface PatchEdit {
  path: string;
  content?: string;
  [key: string]: unknown;
}
export interface Diagnostic {
  tool: string;
  path: string;
  status: string;
  observation: string;
}
export interface Investigation extends InvestigationSummary {
  error?: string | null;
  evidence: Evidence[];
  hypotheses: Hypothesis[];
  patch: null | {
    edits: PatchEdit[];
    diff: string;
    explanation?: string;
    base_hashes?: Record<string, string>;
    status: string;
  };
  baseline: TestResult | null;
  verification: TestResult | null;
  diagnostics: Diagnostic[];
  events: InvestigationEvent[];
}

export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...options, headers });
  } catch {
    throw new Error(
      "Cannot reach the backend. Start the API on 127.0.0.1:8000 and try again.",
    );
  }
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail || body);
    } catch {
      /* Preserve status for a non-JSON error. */
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}
