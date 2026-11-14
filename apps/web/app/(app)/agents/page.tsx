"use client";

import { Check, GraduationCap, Lock, ShieldCheck, Sparkles } from "lucide-react";
import Link from "next/link";

import { Alert, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatDateTime, formatDuration, formatInteger, titleCase } from "@/lib/format";
import type { AgentsOverview } from "@/types/api";

export default function AgentsPage() {
  const overview = useApi<AgentsOverview>("/agents");
  if (overview.error && !overview.data) return <Alert tone="error">{overview.error.message}</Alert>;
  if (!overview.data) return <Loading label="Loading agents" />;
  const { agents, ai_model: ai, recent_runs: runs } = overview.data;

  return (
    <>
      <PageHeader title="Agents">Five agents share the work. Each can use only the tools listed on its card, and each hands structured, validated output to the next.</PageHeader>
      <Alert tone={ai.enabled ? "success" : "info"}>
        {ai.enabled ? (
          <>
            <strong>{ai.provider === "arena" ? "Arena AI connected" : "AI model connected"}: {ai.model}.</strong> It helps the Chief understand requests, the Report agent word its summary, and the AI assistant answer questions. It never calculates: every figure comes from the Statistical Analysis Agent&apos;s code.
          </>
        ) : (
          <>
            <strong>No AI model is connected.</strong> Planning uses built-in rules and reports use fixed templates, so everything works without one. Connecting a model (AI_PROVIDER in the server settings) lets requests be phrased more freely; it will still never calculate a figure.
          </>
        )}
      </Alert>

      <section className="card card-pad">
        <div className="row" style={{ alignItems: "flex-start" }}>
          <div className="stat-icon" style={{ marginBottom: 0 }}><GraduationCap size={19} /></div>
          <div className="grow">
            <h2>The agents learn your business</h2>
            <p className="small muted" style={{ marginTop: 4 }}>
              Your business context, glossary, analysis preferences and lessons from feedback are applied when the Chief plans an analysis and the Report agent writes its summary. Guidance never changes a calculated figure.
            </p>
          </div>
          <div className="row">
            <Link href="/settings" className="btn btn-secondary btn-sm">Teach the agents</Link>
            <Link href="/assistant" className="btn btn-primary btn-sm"><Sparkles size={14} /> Ask the assistant</Link>
          </div>
        </div>
      </section>

      <div className="grid grid-2">
        {agents.map((agent) => (
          <article className="card agent-card" key={agent.key}>
            <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
              <div className="agent-no">{String(agent.number).padStart(2, "0")}</div>
              <div className="grow">
                <h2>{agent.name}</h2>
                <div className="row" style={{ marginTop: 4 }}>
                  <span className="badge">{agent.role}</span>
                  {agent.uses_ai_model ? <span className="badge badge-violet">May use the AI model</span> : <span className="badge badge-blue">Deterministic code only</span>}
                </div>
              </div>
            </div>
            <p className="small">{agent.summary}</p>
            <ul className="ticks">
              {agent.responsibilities.map((item) => (
                <li key={item}><Check size={14} /><span>{item}</span></li>
              ))}
            </ul>
            <ul className="locks">
              {agent.restrictions.map((item) => (
                <li key={item}><Lock size={13} /><span>{item}</span></li>
              ))}
            </ul>
            <div className="row tiny muted">
              Tools: {agent.tools.map((tool) => <span className="tool" key={tool}>{tool}</span>)}
            </div>
          </article>
        ))}
        <article className="card agent-card">
          <div className="row" style={{ alignItems: "flex-start", flexWrap: "nowrap" }}>
            <div className="agent-no agent-no-alt"><ShieldCheck size={18} /></div>
            <div className="grow">
              <h2>Quality Verification</h2>
              <div className="row" style={{ marginTop: 4 }}>
                <span className="badge">Checkpoint</span>
                <span className="badge badge-blue">Deterministic code only</span>
              </div>
            </div>
          </div>
          <p className="small">Not an agent: a fixed set of reconciliation checks that every result must pass between calculation and reporting.</p>
          <ul className="ticks">
            {["Parts add up to totals, exactly", "Profit equals sales less cost of sales", "Totals agree with a second, independent calculation", "Every row is used or accounted for", "Every finding cites its evidence"].map((item) => (
              <li key={item}><Check size={14} /><span>{item}</span></li>
            ))}
          </ul>
          <ul className="locks">
            <li><Lock size={13} /><span>Results that fail are recomputed once, then the analysis fails: they are never reported</span></li>
          </ul>
        </article>
      </div>

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Recent agent activity</h2>
            <p>The execution history kept for every step of every analysis.</p>
          </div>
        </div>
        {runs.length ? (
          <div className="table-wrap">
            <table className="table table-compact">
              <thead>
                <tr>
                  <th>Agent</th>
                  <th>Status</th>
                  <th className="right">Duration</th>
                  <th className="hide-sm">AI model</th>
                  <th className="right hide-sm">AI tokens</th>
                  <th>When</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {runs.map((run, index) => (
                  <tr key={index}>
                    <td>{run.agent_name}</td>
                    <td><span className={`badge ${run.status === "completed" ? "badge-done" : run.status === "failed" ? "badge-danger" : "badge-progress"}`}>{titleCase(run.status)}</span></td>
                    <td className="right">{formatDuration(run.duration_ms)}</td>
                    <td className="small muted hide-sm">{run.model_name ?? "none"}</td>
                    <td className="right hide-sm">{run.tokens_input + run.tokens_output ? formatInteger(run.tokens_input + run.tokens_output) : "–"}</td>
                    <td className="small muted" style={{ whiteSpace: "nowrap" }}>{formatDateTime(run.started_at)}</td>
                    <td><Link className="small" href={`/analyst?job=${run.job_id}`}>View</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="card-pad muted">No agent has run yet.</p>
        )}
      </section>
    </>
  );
}
