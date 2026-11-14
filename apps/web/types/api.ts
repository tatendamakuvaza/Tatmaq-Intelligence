// Shapes returned by the TATMAQ API (apps/api/app/schemas). Kept by hand for now;
// the JSON Schemas in packages/contracts are the language-neutral source.

export type Organisation = {
  id: string;
  name: string;
  slug: string;
  role: string;
  permissions: string[];
  default_currency: string;
  timezone: string;
  date_order: string;
};

export type Workspace = { id: string; name: string; created_at: string };
export type Member = { user_id: string; full_name: string | null; email: string | null; role: string; status: string };
export type Profile = { id: string; full_name: string | null; email: string | null };

export type DatasetStatus = "pending_upload" | "processing" | "ready" | "failed";

export type DatasetVersion = {
  id: string;
  version_number: number;
  status: "processing" | "ready" | "failed";
  row_count: number | null;
  column_count: number | null;
  size_bytes: number | null;
  sha256_hash: string | null;
  error_message: string | null;
  created_at: string;
};

export type Dataset = {
  id: string;
  workspace_id: string;
  name: string;
  source_filename: string | null;
  file_type: string | null;
  status: DatasetStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  latest_version: DatasetVersion | null;
  versions?: DatasetVersion[];
};

export type ColumnInfo = {
  name: string;
  position: number;
  data_type: string | null;
  role: string | null;
  null_count: number | null;
  distinct_count: number | null;
  details: {
    examples?: string[];
    notes?: string[];
    stats?: { min?: number | string; max?: number | string; mean?: number; top_values?: { value: string; count: number }[] };
  };
};

export type CleaningIssue = {
  code: string;
  severity: "info" | "warning" | "critical";
  column: string | null;
  count: number;
  message: string;
  rows: number[];
};

export type CleaningLogEntry = {
  step: string;
  column: string | null;
  rows_affected: number;
  description: string;
  examples: Record<string, unknown>[];
};

export type DatasetProfile = {
  dataset_id: string;
  dataset_name: string;
  version: DatasetVersion;
  profile: {
    file?: { type?: string; sheet?: string; sheets?: string[]; header_row?: number | null; encoding?: string; delimiter?: string };
    rows?: number;
    rows_in_file?: number;
    columns?: number;
    roles?: Record<string, string>;
    preview?: { columns: string[]; rows: (string | null)[][] };
    processing_log?: string[];
    warnings?: string[];
  };
  columns: ColumnInfo[];
  cleaning: {
    rows_in?: number;
    rows_out?: number;
    log?: CleaningLogEntry[];
    issues?: CleaningIssue[];
    duplicates?: { rows: number; revenue: string | null };
  };
};

export type JobStatus =
  | "queued"
  | "validating_dataset"
  | "planning"
  | "executing_agents"
  | "quality_verification"
  | "generating_report"
  | "completed"
  | "partially_completed"
  | "failed"
  | "cancelled";

export type Job = {
  id: string;
  workspace_id: string;
  job_type: string;
  analysis_type: string;
  prompt: string;
  status: JobStatus;
  is_finished: boolean;
  cancel_requested: boolean;
  error_message: string | null;
  attempts: number;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  dataset: { id: string; name: string; version_id: string; version_number: number } | null;
  headline: string | null;
};

export type AgentTask = {
  id: string;
  sequence: number;
  agent_key: string;
  agent_name: string;
  role: string;
  action: string | null;
  status: "pending" | "running" | "completed" | "failed" | "skipped" | "cancelled";
  started_at: string | null;
  completed_at: string | null;
  duration_ms: number | null;
  attempts: number;
  summary: string | null;
  warnings: string[];
  model_name: string | null;
  tokens_input: number;
  tokens_output: number;
  error_message: string | null;
};

export type ValueFormat = "money" | "percent" | "integer" | "number" | "number4" | "month" | "text";

export type Kpi = { key: string; label: string; value: string | number | null; format: ValueFormat; evidence_ref: string; note: string | null };

export type ChartSeries = { name: string; type?: "bar" | "line"; format: ValueFormat; axis?: "right"; values: (number | null)[] };

export type Chart = {
  key: string;
  title: string;
  orientation: "vertical" | "horizontal";
  categories: string[];
  series: ChartSeries[];
  evidence_ref: string;
  note: string | null;
};

export type ResultTable = {
  key: string;
  title: string;
  evidence_ref: string;
  note: string | null;
  columns: { key: string; label: string; format: ValueFormat }[];
  rows: Record<string, string | number | null>[];
};

export type Segment = {
  key: string;
  label: string;
  currency: string | null;
  rows: number;
  kpis: Kpi[];
  charts: Chart[];
  tables: ResultTable[];
  notes: string[];
};

export type Check = { name: string; passed: boolean; detail: string };

export type ResultSummary = {
  title: string;
  objective: string;
  headline: string | null;
  executive_summary: string[];
  next_steps: string[];
  narrative_source: string | null;
  segments: Segment[];
  warnings: string[];
  assumptions: string[];
  unmet_requests: string[];
  verification: { passed: boolean; checks: Check[] };
  plan: { planner: "rules" | "ai"; operations: { type: string; title: string }[] };
  dataset: { name: string; version: number; rows: number; sha256: string };
};

export type Evidence = {
  ref?: string;
  operation?: string;
  formula?: string;
  columns?: string[];
  filters?: string[];
  rows_total?: number | null;
  rows_used?: number | null;
  rows_excluded?: number | null;
  exclusions?: Record<string, number>;
  dataset_sha256?: string;
  segment?: string | null;
};

export type Finding = {
  id: string;
  sequence: number;
  key: string | null;
  kind: "kpi" | "insight" | "statistic" | "quality" | "limitation" | null;
  title: string | null;
  statement: string | null;
  agent_key: string | null;
  evidence_ref: string | null;
  evidence: Evidence;
  approved: boolean;
};

export type Report = {
  id: string;
  job_id: string;
  format: "pdf" | "xlsx" | "html" | string;
  title: string | null;
  filename: string | null;
  size_bytes: number | null;
  created_at: string;
  prompt: string | null;
  dataset_name: string | null;
};

export type JobResults = { job: Job; summary: ResultSummary | null; findings: Finding[]; reports: Report[] };

export type AgentDescriptor = {
  key: string;
  number: number;
  name: string;
  role: string;
  summary: string;
  responsibilities: string[];
  restrictions: string[];
  tools: string[];
  uses_ai_model: boolean;
};

export type AgentRun = {
  agent_key: string;
  agent_name: string;
  job_id: string;
  status: string;
  started_at: string;
  duration_ms: number | null;
  model_name: string | null;
  tokens_input: number;
  tokens_output: number;
};

export type AgentsOverview = {
  ai_model: { enabled: boolean; provider: string; model: string | null };
  agents: AgentDescriptor[];
  recent_runs: AgentRun[];
};

export type Usage = {
  period_start: string;
  analyses: { used: number; limit: number };
  this_month: Record<string, number>;
  totals: { datasets: number; reports: number; storage_bytes: number };
  limits: { max_upload_mb: number; max_analysis_rows: number; max_active_jobs: number };
};

export type ClientConfig = {
  version: string;
  auth_mode: "dev" | "builtin" | "supabase";
  signups_open: boolean;
  max_upload_mb: number;
  file_types: string[];
  ai_enabled: boolean;
  ai_provider: "none" | "openai_compatible" | "anthropic" | "arena";
};

export type ReportStyle = "executive" | "balanced" | "detailed";

// Durable guidance the agents read when planning and wording reports. It never
// takes part in calculations: verified figures always come from the agents' code.
export type LearningProfile = {
  business_context: string;
  glossary: string;
  analysis_preferences: string;
  report_style: ReportStyle;
  lessons: string[];
  updated_at: string | null;
};

export type ArenaAnswer = {
  answer: string;
  caveats: string[];
  provider: string;
  model: string | null;
  used_job_id: string | null;
  tokens_input: number;
  tokens_output: number;
};

export type JobFeedback = { recorded: boolean; lesson_saved: boolean };
