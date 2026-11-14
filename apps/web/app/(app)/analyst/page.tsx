"use client";

import { Ban, Play, RotateCcw } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState, type FormEvent } from "react";

import { AgentPipeline } from "@/components/AgentPipeline";
import { ResultsView } from "@/components/ResultsView";
import { Alert, Empty, JobBadge, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatInteger, timeAgo } from "@/lib/format";
import { newRequestId } from "@/lib/id";
import { api } from "@/services/api";
import { useSession } from "@/services/session";
import type { AgentTask, Dataset, Job, JobResults } from "@/types/api";

const SUGGESTIONS = [
  "Analyse my sales records and identify my most profitable products.",
  "Analyse sales performance for the past 12 months.",
  "Why did our gross profit margin change over the period?",
  "Which branches sell the most?",
  "Are there any unusual transactions?",
  "Check the quality of this data.",
];

const TYPES = [
  ["automatic", "Automatic (decide from my question)"],
  ["sales", "Sales performance"],
  ["profitability", "Profitability"],
  ["statistical", "Statistical summary"],
  ["data_quality", "Data quality"],
] as const;

function JobPanel({ jobId, onRunAgain }: { jobId: string; onRunAgain: (job: Job) => void }) {
  const activity = useApi<{ job: Job; tasks: AgentTask[] }>(`/analysis-jobs/${jobId}/agents`, (data) => (data && data.job.is_finished ? null : 1000));
  const job = activity.data?.job;
  const finished = job?.is_finished ?? false;
  const results = useApi<JobResults>(finished && job && job.status !== "cancelled" ? `/analysis-jobs/${jobId}/results` : null);
  const [cancelError, setCancelError] = useState<string | null>(null);

  if (activity.error && !activity.data) return <Alert tone="error">{activity.error.message}</Alert>;
  if (!job) return <div className="card"><Loading label="Loading analysis" /></div>;

  async function cancel() {
    setCancelError(null);
    try {
      await api.post(`/analysis-jobs/${jobId}/cancel`);
      activity.reload();
    } catch (caught) {
      setCancelError((caught as Error).message);
    }
  }

  return (
    <div className="stack">
      <section className="card">
        <div className="card-head">
          <div className="grow">
            <h2>{job.prompt}</h2>
            <p>
              {job.dataset ? `${job.dataset.name} (version ${job.dataset.version_number})` : "No dataset"} &middot; submitted {timeAgo(job.created_at)}
            </p>
          </div>
          <div className="row">
            <JobBadge status={job.status} />
            {!finished ? (
              <button type="button" className="btn btn-danger btn-sm" onClick={() => void cancel()} disabled={job.cancel_requested}>
                <Ban size={14} /> {job.cancel_requested ? "Cancelling..." : "Cancel"}
              </button>
            ) : (
              <button type="button" className="btn btn-secondary btn-sm" onClick={() => onRunAgain(job)}>
                <RotateCcw size={14} /> Ask again
              </button>
            )}
          </div>
        </div>
        <AgentPipeline tasks={activity.data?.tasks ?? []} active={!finished} />
      </section>
      {cancelError ? <Alert tone="error">{cancelError}</Alert> : null}
      {job.status === "failed" ? (
        <Alert tone="error">
          <strong>This analysis could not be completed.</strong> {job.error_message}
        </Alert>
      ) : null}
      {job.status === "cancelled" ? <Alert tone="info">This analysis was cancelled. Nothing was published from it.</Alert> : null}
      {results.error ? <Alert tone="error">{results.error.message}</Alert> : null}
      {finished && results.loading ? <div className="card"><Loading label="Loading results" /></div> : null}
      {results.data ? <ResultsView results={results.data} /> : null}
    </div>
  );
}

function Analyst() {
  const router = useRouter();
  const params = useSearchParams();
  const jobId = params.get("job");
  const presetDataset = params.get("dataset");
  const { workspace, can } = useSession();
  const scope = workspace ? `?workspace_id=${workspace.id}` : "";
  const datasets = useApi<Dataset[]>(`/datasets${scope}`);
  const history = useApi<Job[]>(`/analysis-jobs${scope ? `${scope}&` : "?"}limit=8`, (data) => (data?.some((job) => !job.is_finished) ? 2500 : null));
  const ready = useMemo(() => datasets.data?.filter((dataset) => dataset.status === "ready" && dataset.latest_version) ?? [], [datasets.data]);

  // The selection is derived, not stored: the user's choice if it is still valid,
  // else the dataset named in the link that brought them here, else the newest one.
  const [chosen, setDatasetId] = useState<string | null>(null);
  const available = (id: string | null) => (id && ready.some((dataset) => dataset.id === id) ? id : null);
  const datasetId = available(chosen) ?? available(presetDataset) ?? ready[0]?.id ?? "";
  const [prompt, setPrompt] = useState("");
  const [type, setType] = useState<string>("automatic");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const dataset = ready.find((candidate) => candidate.id === datasetId);
    if (!dataset?.latest_version || !workspace) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await api.post<{ job_id: string }>(
        "/analysis-jobs",
        { workspace_id: workspace.id, dataset_version_id: dataset.latest_version.id, prompt: prompt.trim(), analysis_type: type },
        // One key per click: a retry after a dropped connection cannot start (or bill) a second analysis.
        { headers: { "Idempotency-Key": newRequestId() } },
      );
      history.reload();
      router.push(`/analyst?job=${accepted.job_id}`);
    } catch (caught) {
      setError((caught as Error).message);
    }
    setBusy(false);
  }

  const selected = ready.find((dataset) => dataset.id === datasetId);

  return (
    <>
      <PageHeader title="Analyst">Ask a question about a dataset. The agents plan the work, calculate, verify the results and write the report.</PageHeader>
      {/* data-job lets the stylesheet put an open analysis above the form on narrow screens */}
      <div className="split" data-job={jobId ? "open" : undefined}>
        <div className="stack">
          <form className="card card-pad stack" onSubmit={submit}>
            {datasets.loading && !datasets.data ? (
              <Loading />
            ) : ready.length === 0 ? (
              <Empty title="No dataset is ready yet">
                <span className="small">Upload a file first; it becomes available here once it has been imported.</span>
                <Link href="/datasets" className="btn btn-primary">
                  Go to datasets
                </Link>
              </Empty>
            ) : (
              <>
                <label className="field">
                  <span>Dataset</span>
                  <select className="select" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
                    {ready.map((dataset) => (
                      <option key={dataset.id} value={dataset.id}>
                        {dataset.name}
                      </option>
                    ))}
                  </select>
                  {selected?.latest_version ? (
                    <small>
                      {formatInteger(selected.latest_version.row_count)} records, {selected.latest_version.column_count} columns &middot;{" "}
                      <Link href={`/datasets/${selected.id}`}>view profile</Link>
                    </small>
                  ) : null}
                </label>
                <label className="field">
                  <span>What would you like to know?</span>
                  <textarea className="textarea" value={prompt} maxLength={4000} placeholder="Describe the analysis you need in plain language." onChange={(event) => setPrompt(event.target.value)} />
                </label>
                <div className="chips" aria-label="Example questions">
                  {SUGGESTIONS.map((suggestion) => (
                    <button type="button" className="chip" key={suggestion} onClick={() => setPrompt(suggestion)}>
                      {suggestion}
                    </button>
                  ))}
                </div>
                <label className="field">
                  <span>Analysis type</span>
                  <select className="select" value={type} onChange={(event) => setType(event.target.value)}>
                    {TYPES.map(([value, label]) => (
                      <option key={value} value={value}>
                        {label}
                      </option>
                    ))}
                  </select>
                </label>
                {error ? <Alert tone="error">{error}</Alert> : null}
                {!can("analysis:run") ? <Alert tone="info">Your role can view analyses but not start them.</Alert> : null}
                <button className="btn btn-primary btn-block" type="submit" disabled={busy || !prompt.trim() || !can("analysis:run")}>
                  <Play size={15} /> {busy ? "Submitting..." : "Run analysis"}
                </button>
              </>
            )}
          </form>

          {history.data?.length ? (
            <section className="card">
              <div className="card-head">
                <h2>History</h2>
              </div>
              <div className="history">
                {history.data.map((job) => (
                  <Link key={job.id} href={`/analyst?job=${job.id}`} aria-current={job.id === jobId ? "true" : undefined}>
                    <span>{job.prompt}</span>
                    <JobBadge status={job.status} />
                  </Link>
                ))}
              </div>
            </section>
          ) : null}
        </div>

        <div>
          {jobId ? (
            <JobPanel key={jobId} jobId={jobId} onRunAgain={(job) => { setPrompt(job.prompt); router.push("/analyst"); }} />
          ) : (
            <div className="card">
              <Empty title="Your analysis will appear here">
                <span className="small">Choose a dataset, ask a question, and watch each agent report what it did.</span>
              </Empty>
            </div>
          )}
        </div>
      </div>
    </>
  );
}

export default function AnalystPage() {
  // useSearchParams needs a Suspense boundary so the page can be prerendered.
  return (
    <Suspense fallback={<Loading />}>
      <Analyst />
    </Suspense>
  );
}
