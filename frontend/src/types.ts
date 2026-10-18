export type Project = {
  id: string;
  name: string;
  kind: string;
  suggested_task?: string;
};
export type TestResult = {
  attempt: number;
  exit_code: number;
  passed: number;
  failed: number;
  errors: number;
  skipped: number;
  output: string;
};
export type Run = {
  id: string;
  project_id: string;
  task: string;
  status: string;
  attempt: number;
  tool_calls: number;
  input_tokens: number;
  output_tokens: number;
  elapsed_seconds: number;
  changed_files: string[];
  diff: string;
  tests: TestResult[];
  error: string | null;
  plan?: string[];
};
export type AgentEvent = {
  id: number;
  kind: string;
  message: string;
  created_at: string;
  data: Record<string, unknown>;
};
export type Health = { provider: string; runner: string; role: string };
export const terminal = new Set([
  "awaiting_review",
  "approved",
  "rejected",
  "failed_tests",
  "cancelled",
  "timeout",
  "model_error",
  "sandbox_error",
  "policy_blocked",
  "interrupted",
  "budget_exhausted",
]);
