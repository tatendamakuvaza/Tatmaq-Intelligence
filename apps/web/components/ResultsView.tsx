"use client";

import { ChevronRight, ShieldCheck } from "lucide-react";
import { useState } from "react";

import { ChartView } from "@/components/Charts";
import { FeedbackCard } from "@/components/FeedbackCard";
import { ReportButtons } from "@/components/ReportButtons";
import { Alert } from "@/components/ui";
import { formatInteger, formatValue } from "@/lib/format";
import type { Finding, JobResults, ResultTable, Segment } from "@/types/api";

const KIND: Record<string, [string, string]> = {
  kpi: ["Key figure", "badge-blue"],
  insight: ["Insight", "badge-violet"],
  statistic: ["Statistical result", "badge-info"],
  quality: ["Data quality", "badge-warning"],
  limitation: ["Limitation", "badge-warning"],
};
const NUMERIC = new Set(["money", "percent", "integer", "number", "number4"]);

function Table({ table, currency }: { table: ResultTable; currency: string | null }) {
  return (
    <details className="card details">
      <summary>
        <span>
          {table.title} <span className="tiny muted">[{table.evidence_ref}]</span>
        </span>
        <span className="row tiny muted">
          {table.rows.length} rows <ChevronRight size={16} className="chev" />
        </span>
      </summary>
      <div className="table-wrap">
        <table className="table table-compact">
          <thead>
            <tr>
              {table.columns.map((column) => (
                <th key={column.key} className={NUMERIC.has(column.format) ? "right" : ""}>
                  {column.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row, index) => (
              <tr key={index}>
                {table.columns.map((column) => (
                  <td key={column.key} className={NUMERIC.has(column.format) ? "right" : ""}>
                    {formatValue(row[column.key], column.format, currency)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {table.note ? <p className="small muted" style={{ padding: "8px 20px 12px" }}>{table.note}</p> : null}
    </details>
  );
}

function SegmentView({ segment, showLabel }: { segment: Segment; showLabel: boolean }) {
  return (
    <section className="stack">
      {showLabel ? (
        <h2>
          {segment.label} <span className="small muted">({formatInteger(segment.rows)} records)</span>
        </h2>
      ) : null}
      {segment.kpis.length ? (
        <div className="kpis">
          {segment.kpis.map((kpi) => (
            <div className="kpi" key={kpi.key}>
              <div className="label">{kpi.label}</div>
              <div className="value">{formatValue(kpi.value, kpi.format, segment.currency)}</div>
              {kpi.note ? <div className="note">{kpi.note}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
      {segment.charts.length ? (
        <div className={`grid ${segment.charts.length > 1 ? "grid-2" : ""}`}>
          {segment.charts.map((chart) => (
            <div className="card" key={chart.key} style={segment.charts.length % 2 === 1 && chart === segment.charts[segment.charts.length - 1] && segment.charts.length > 1 ? { gridColumn: "1 / -1" } : undefined}>
              <div className="card-head">
                <h3>{chart.title}</h3>
                <span className="tiny muted">[{chart.evidence_ref}]</span>
              </div>
              <div style={{ padding: "14px 14px 10px" }}>
                <ChartView chart={chart} currency={segment.currency} />
                {chart.note ? <p className="small muted" style={{ marginTop: 6 }}>{chart.note}</p> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      {segment.tables.map((table) => (
        <Table key={table.key} table={table} currency={segment.currency} />
      ))}
    </section>
  );
}

function FindingRow({ finding, segmentLabel }: { finding: Finding; segmentLabel: string | null }) {
  const [open, setOpen] = useState(false);
  const [label, tone] = KIND[finding.kind ?? ""] ?? ["Finding", ""];
  const evidence = finding.evidence;
  const exclusions = Object.entries(evidence.exclusions ?? {});
  return (
    <li className="finding">
      <div className="finding-head">
        <strong>{finding.title}</strong>
        <span className={`badge ${tone}`}>{label}</span>
        {segmentLabel ? <span className="badge">{segmentLabel}</span> : null}
      </div>
      <p>{finding.statement}</p>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
        <ChevronRight size={14} style={{ transform: open ? "rotate(90deg)" : undefined }} />
        How this was calculated [{finding.evidence_ref}]
      </button>
      {open ? (
        <dl className="evidence">
          <dt>Method</dt>
          <dd>{evidence.formula}</dd>
          {evidence.columns?.length ? (
            <>
              <dt>Columns used</dt>
              <dd>{evidence.columns.join(", ")}</dd>
            </>
          ) : null}
          {evidence.filters?.length ? (
            <>
              <dt>Filter</dt>
              <dd>{evidence.filters.join("; ")}</dd>
            </>
          ) : null}
          {evidence.rows_total != null && evidence.rows_used != null ? (
            <>
              <dt>Rows</dt>
              <dd>
                {formatInteger(evidence.rows_used)} of {formatInteger(evidence.rows_total)} used
                {exclusions.length ? ` (left out: ${exclusions.map(([reason, count]) => `${formatInteger(count)} with ${reason}`).join(", ")})` : ""}
              </dd>
            </>
          ) : null}
          <dt>Source</dt>
          <dd className="mono">dataset fingerprint {evidence.dataset_sha256?.slice(0, 16)}...</dd>
        </dl>
      ) : null}
    </li>
  );
}

export function ResultsView({ results }: { results: JobResults }) {
  const summary = results.summary;
  if (!summary) return null;
  const multiple = summary.segments.length > 1;
  const labels = Object.fromEntries(summary.segments.map((segment) => [segment.key, segment.label]));
  const checks = summary.verification.checks;
  const notes = [...summary.unmet_requests, ...summary.warnings.filter((warning) => !summary.unmet_requests.includes(warning))];

  return (
    <div className="stack">
      <section className="card card-pad stack">
        <div className="spread">
          <div>
            <div className="eyebrow">{summary.title}</div>
            <p className="headline" style={{ marginTop: 4 }}>{summary.headline}</p>
          </div>
        </div>
        {results.reports.length ? <ReportButtons reports={results.reports} /> : null}
        {summary.unmet_requests.length ? (
          <Alert tone="warning">
            <strong>Part of the request could not be met.</strong> {summary.unmet_requests.join(" ")}
          </Alert>
        ) : null}
        <div>
          <h3 style={{ marginBottom: 8 }}>Executive summary</h3>
          <ul className="bullets">
            {summary.executive_summary.map((point) => (
              <li key={point}>{point}</li>
            ))}
          </ul>
        </div>
        {summary.next_steps.length ? (
          <div>
            <h3 style={{ marginBottom: 8 }}>Suggested next steps</h3>
            <ul className="bullets">
              {summary.next_steps.map((step) => (
                <li key={step}>{step}</li>
              ))}
            </ul>
          </div>
        ) : null}
        <div className="row small muted" style={{ flexWrap: "nowrap", alignItems: "flex-start" }}>
          <ShieldCheck size={16} color="var(--blue-600)" style={{ flex: "none", marginTop: 2 }} />
          <span>
            {checks.filter((check) => check.passed).length} of {checks.length} reconciliation checks passed before these results were released.
            {summary.narrative_source ? ` ${summary.narrative_source}` : ""}
          </span>
        </div>
      </section>

      {summary.segments.map((segment) => (
        <SegmentView key={segment.key} segment={segment} showLabel={multiple} />
      ))}

      <section className="card">
        <div className="card-head">
          <div>
            <h2>Findings</h2>
            <p>Every finding links to the calculation and the rows it came from.</p>
          </div>
          <span className="badge">{results.findings.length}</span>
        </div>
        <ul className="findings">
          {results.findings.map((finding) => (
            <FindingRow key={finding.id} finding={finding} segmentLabel={multiple ? (labels[finding.evidence.segment ?? ""] ?? null) : null} />
          ))}
        </ul>
      </section>

      {notes.length || summary.assumptions.length ? (
        <section className="card card-pad stack">
          {notes.length ? (
            <div>
              <h2 style={{ marginBottom: 8 }}>Data notes and limitations</h2>
              <ul className="bullets small">
                {notes.map((note) => (
                  <li key={note}>{note}</li>
                ))}
              </ul>
            </div>
          ) : null}
          {summary.assumptions.length ? (
            <div>
              <h2 style={{ marginBottom: 8 }}>Assumptions</h2>
              <ul className="bullets small">
                {summary.assumptions.map((assumption) => (
                  <li key={assumption}>{assumption}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>
      ) : null}

      <details className="card details">
        <summary>
          <span>Verification checks</span>
          <span className="row tiny muted">
            {checks.filter((check) => check.passed).length}/{checks.length} passed <ChevronRight size={16} className="chev" />
          </span>
        </summary>
        <div className="table-wrap">
          <table className="table table-compact">
            <thead>
              <tr>
                <th>Check</th>
                <th>Result</th>
                <th>Detail</th>
              </tr>
            </thead>
            <tbody>
              {checks.map((check) => (
                <tr key={check.name}>
                  <td>{check.name}</td>
                  <td>
                    <span className={`badge ${check.passed ? "badge-done" : "badge-danger"}`}>{check.passed ? "Passed" : "Failed"}</span>
                  </td>
                  <td className="muted num">{check.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      <FeedbackCard jobId={results.job.id} />
    </div>
  );
}
