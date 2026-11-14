"use client";

import { Bot, Send, Sparkles } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";

import { Alert, Empty, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { newRequestId } from "@/lib/id";
import { api, ApiError } from "@/services/api";
import { useSession } from "@/services/session";
import type { AgentsOverview, ArenaAnswer, Job, JobResults } from "@/types/api";

const SUGGESTIONS = [
  "Explain these results in plain business language.",
  "What should management focus on next quarter?",
  "What are the biggest risks visible in this data?",
  "How could we improve gross profit margin?",
];

// What the deterministic agents already verified for the attached analysis.
type TatmaqAnswer = { jobId: string; headline: string | null; points: string[]; findings: string[] };
type Exchange = { id: string; question: string; tatmaq: TatmaqAnswer | null; arena: ArenaAnswer | null; arenaError: string | null };

export default function AssistantPage() {
  const { workspace, can } = useSession();
  const scope = workspace ? `?workspace_id=${workspace.id}` : "";
  const overview = useApi<AgentsOverview>("/agents");
  const jobs = useApi<Job[]>(`/analysis-jobs${scope ? `${scope}&` : "?"}limit=30`);
  const completed = useMemo(
    () => (jobs.data ?? []).filter((job) => job.status === "completed" || job.status === "partially_completed"),
    [jobs.data],
  );
  const [jobId, setJobId] = useState("");
  const selectedJob = completed.find((job) => job.id === jobId) ?? null;
  const results = useApi<JobResults>(selectedJob ? `/analysis-jobs/${selectedJob.id}/results` : null);

  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exchanges, setExchanges] = useState<Exchange[]>([]);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [exchanges, busy]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);

    // Snapshot the verified TATMAQ answer at the moment the question is asked.
    const summary = results.data?.summary ?? null;
    const tatmaq: TatmaqAnswer | null =
      selectedJob && summary
        ? {
            jobId: selectedJob.id,
            headline: summary.headline,
            points: summary.executive_summary.slice(0, 4),
            findings: (results.data?.findings ?? [])
              .filter((finding) => finding.approved && finding.statement)
              .slice(0, 3)
              .map((finding) => finding.statement as string),
          }
        : null;

    let arena: ArenaAnswer | null = null;
    let arenaError: string | null = null;
    try {
      arena = await api.post<ArenaAnswer>("/arena/ask", { question: text, job_id: selectedJob?.id ?? null });
    } catch (caught) {
      arenaError =
        caught instanceof ApiError && caught.code === "ai_not_configured"
          ? "Arena AI is not connected yet. Your administrator can connect it in the API settings; the TATMAQ agents keep working without it."
          : (caught as Error).message;
    }
    setExchanges((current) => [...current, { id: newRequestId(), question: text, tatmaq, arena, arenaError }]);
    setQuestion("");
    setBusy(false);
  }

  const ai = overview.data?.ai_model;
  const waitingForResults = !!selectedJob && results.loading;

  return (
    <>
      <PageHeader title="AI assistant">
        Ask once, get two perspectives: your TATMAQ agents answer from verified analysis of your own data, and Arena AI adds interpretation and broader business context.
      </PageHeader>

      {ai && !ai.enabled ? (
        <Alert tone="info">
          <strong>Arena AI is not connected yet.</strong> Your administrator can connect it in the API settings. Until then, attach a completed analysis below to see the verified answer from your TATMAQ agents.
        </Alert>
      ) : null}
      {error ? <Alert tone="error">{error}</Alert> : null}

      <form className="card card-pad stack" onSubmit={submit}>
        <label className="field">
          <span>Attach a completed analysis (optional)</span>
          <select className="select" value={jobId} onChange={(event) => setJobId(event.target.value)}>
            <option value="">No analysis — general business questions only</option>
            {completed.map((job) => (
              <option key={job.id} value={job.id}>
                {job.prompt.length > 80 ? `${job.prompt.slice(0, 80)}…` : job.prompt}
                {job.dataset ? ` — ${job.dataset.name}` : ""}
              </option>
            ))}
          </select>
          <small>
            With an analysis attached, both answers are grounded in its verified findings. Without one, Arena AI gives general guidance only.
          </small>
        </label>
        {selectedJob && results.error ? <Alert tone="error">{results.error.message}</Alert> : null}
        <label className="field">
          <span>Your question</span>
          <textarea
            className="textarea"
            value={question}
            maxLength={4000}
            placeholder="For example: What should we tell the board about this quarter's performance?"
            onChange={(event) => setQuestion(event.target.value)}
          />
        </label>
        <div className="chips" aria-label="Example questions">
          {SUGGESTIONS.map((suggestion) => (
            <button type="button" className="chip" key={suggestion} onClick={() => setQuestion(suggestion)}>
              {suggestion}
            </button>
          ))}
        </div>
        {!can("analysis:run") ? <Alert tone="info">Your role can view analyses but not ask the assistant.</Alert> : null}
        <div className="row">
          <button className="btn btn-primary" type="submit" disabled={busy || !question.trim() || !can("analysis:run") || waitingForResults}>
            <Send size={15} /> {busy ? "Asking…" : waitingForResults ? "Loading analysis…" : "Ask both"}
          </button>
          {exchanges.length ? (
            <button type="button" className="btn btn-ghost" onClick={() => setExchanges([])}>
              Clear conversation
            </button>
          ) : null}
        </div>
      </form>

      {exchanges.length === 0 && !busy ? (
        <div className="card">
          <Empty icon={<Sparkles size={34} />} title="Ask your first question">
            <span className="small">Attach one of your completed analyses for answers grounded in verified figures, or ask a general business question.</span>
          </Empty>
        </div>
      ) : (
        <div className="chat-log" aria-live="polite">
          {exchanges.map((exchange) => (
            <div className="stack-sm" key={exchange.id}>
              <div className="chat-bubble" data-role="user">
                <div className="chat-meta">You</div>
                <p className="chat-answer">{exchange.question}</p>
              </div>
              <div className="grid grid-2">
                <div className="chat-bubble" data-role="assistant">
                  <div className="chat-meta"><Bot size={14} /> TATMAQ agents · verified</div>
                  {exchange.tatmaq ? (
                    <div className="stack-sm">
                      {exchange.tatmaq.headline ? <strong>{exchange.tatmaq.headline}</strong> : null}
                      {exchange.tatmaq.points.length ? (
                        <ul className="bullets small">
                          {exchange.tatmaq.points.map((point) => <li key={point}>{point}</li>)}
                        </ul>
                      ) : null}
                      {exchange.tatmaq.findings.map((finding) => (
                        <p className="small muted" key={finding}>{finding}</p>
                      ))}
                      <Link className="small" href={`/analyst?job=${exchange.tatmaq.jobId}`}>Open the full analysis and its evidence</Link>
                    </div>
                  ) : (
                    <p className="small muted">
                      No completed analysis was attached to this question, so the agents have no verified figures to quote.{" "}
                      <Link href="/analyst">Run an analysis</Link> to get company-specific numbers.
                    </p>
                  )}
                </div>
                <div className="chat-bubble" data-role="assistant">
                  <div className="chat-meta">
                    <Sparkles size={14} /> Arena AI{exchange.arena?.model ? ` · ${exchange.arena.model}` : ""}
                  </div>
                  {exchange.arena ? (
                    <div className="stack-sm">
                      <p className="chat-answer">{exchange.arena.answer}</p>
                      {exchange.arena.caveats.length ? (
                        <ul className="bullets small muted">
                          {exchange.arena.caveats.map((caveat) => <li key={caveat}>{caveat}</li>)}
                        </ul>
                      ) : null}
                      <span className="tiny muted">
                        Interpretation and context. Company figures come from the verified TATMAQ analysis, not from the model.
                      </span>
                    </div>
                  ) : (
                    <Alert tone="warning">{exchange.arenaError ?? "Arena AI did not return an answer."}</Alert>
                  )}
                </div>
              </div>
            </div>
          ))}
          {busy ? (
            <div className="chat-bubble" data-role="assistant">
              <Loading label="The agents and Arena AI are answering" />
            </div>
          ) : null}
          <div ref={bottom} />
        </div>
      )}
    </>
  );
}
