// Types and calls for the playground backend (playground/backend/app.py).

export type Action =
  | "store" | "store_labeled" | "update" | "merge" | "supersede" | "reject" | "review" | "redact";
export type JudgeMode = "recorded" | "live" | "needs-live" | "rules";

export interface Signal {
  name: string;
  kind: "noul" | "choice" | "score" | "check";
  value: number | string | boolean | null;
  probabilities: Record<string, number> | null;
  confidence: number | null;
}

export interface Decision {
  id: string;
  text: string;
  action: Action;
  type: string;
  rule: string;
  rule_line: string;
  reason: string;
  labels: string[];
  error: string | null;
  warnings: string[];
  mode: JudgeMode;
  model: string | null;
  policy: string;
  policy_version: string;
  latency_ms: number;
  redacted_text: string | null;
  signals: Signal[];
  target: string | null;
  patch: { target_id: string; old_text: string; new_text: string; restore: boolean } | null;
  episode_id?: string | null;
}

export interface MemoryItem {
  id: string;
  text: string;
  type: string;
  labels: string[];
  previous_text: string | null;
  superseded_by: string | null;
  confidence: number | null;
  files: string[];
  source: string;
}

export interface Step { decision: Decision; memories: MemoryItem[]; archive: MemoryItem[] }
export type Thresholds = Record<string, number[]>;

export interface RuleInfo {
  id: string;
  name: string | null;
  when: string | null;
  then: Action;
  label: string | null;
  restore: boolean;
  line: number | null;
}

export interface PolicySummary {
  description: string;
  rules: RuleInfo[];
  signals: Record<string, string>;
  type_help: Record<string, string>;
}

export interface TemplateInfo extends PolicySummary { yaml: string; version: string; types: string[] }
export type TemplateName = "personal-memory" | "dev-sessions";

export interface Config {
  templates: Record<TemplateName, TemplateInfo>;
  demo: { role: string; content: string }[];
  live_available: boolean;
  limits: { message_chars: number; messages: number; daily_cap_usd: number };
}

export type Answers = Record<string, unknown>;

export interface RunResult {
  steps: Step[];
  ledger: string;
  new_answers: Answers;
  blocked: string | null;
  thresholds: Thresholds;
}

export interface Episode {
  id: string;
  request: string;
  outcome: string;
  type: string | null;
  noise: number;
  dropped: boolean;
  files_edited: string[];
  files_read: string[];
}

export interface SessionResult {
  episodes: Episode[];
  decisions: Decision[];
  files: { path: string; markdown: string; memory: MemoryItem }[];
  ledger: string;
  new_answers: Answers;
  blocked: string | null;
  thresholds: Thresholds;
}

export type Validation =
  | ({ ok: true; policy: string; version: string } & PolicySummary)
  | { ok: false; error: string; line: number | null };

export interface TestResult {
  total: number;
  passed: number;
  needs_live: number;
  failures: { input: string; reason: string }[];
}

export class ApiError extends Error {
  constructor(public detail: unknown) {
    super("request failed");
  }
  /** A readable message, with the YAML line when the backend gives one. */
  get readable(): string {
    const d = this.detail as { error?: string; line?: number } | string | undefined;
    if (typeof d === "string") return d;
    if (d && d.error) return d.line ? `Line ${d.line}: ${d.error}` : d.error;
    return "Something went wrong.";
  }
}

async function post<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new ApiError(data.detail);
  return data as T;
}

export const api = {
  config: async (): Promise<Config> => (await fetch("/api/config")).json(),
  run: (b: { template: TemplateName; policy_yaml: string | null; messages: { role: string; content: string }[]; live: boolean; answers: Answers }) =>
    post<RunResult>("/api/run", b),
  sessions: (b: { policy_yaml: string | null; live: boolean; answers: Answers }) =>
    post<SessionResult>("/api/sessions", b),
  validate: (template: TemplateName, policy_yaml: string) =>
    post<Validation>("/api/validate", { template, policy_yaml }),
  test: (template: TemplateName, policy_yaml: string) =>
    post<TestResult>("/api/test", { template, policy_yaml }),
  evalResults: async (): Promise<Record<string, unknown>> => (await fetch("/api/eval")).json(),
};

/** Count an anonymous event; never content. */
export function track(name: string): void {
  post("/api/event", { name }).catch(() => undefined);
}
