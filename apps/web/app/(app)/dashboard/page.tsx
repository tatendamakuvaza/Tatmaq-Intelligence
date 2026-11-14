"use client";

import { ArrowRight, BarChart3, Database, FileText, Table2 } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { UploadPanel } from "@/components/UploadPanel";
import { Alert, Empty, JobBadge, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatBytes, formatInteger, timeAgo } from "@/lib/format";
import { useSession } from "@/services/session";
import type { Dataset, Job, Usage } from "@/types/api";

export default function DashboardPage() {
  const router = useRouter();
  const { profile, organisation, workspace } = useSession();
  const scope = workspace ? `?workspace_id=${workspace.id}` : "";
  const usage = useApi<Usage>("/usage");
  const datasets = useApi<Dataset[]>(`/datasets${scope}`);
  const jobs = useApi<Job[]>(`/analysis-jobs${scope ? `${scope}&` : "?"}limit=6`, (data) => (data?.some((job) => !job.is_finished) ? 2000 : null));
  const firstName = profile?.full_name?.split(" ")[0];
  const ready = datasets.data?.filter((dataset) => dataset.status === "ready") ?? [];
  const error = usage.error ?? datasets.error ?? jobs.error;

  return (
    <>
      <PageHeader
        title={firstName ? `Good to see you, ${firstName}` : "Dashboard"}
        actions={
          ready.length ? (
            <Link href="/analyst" className="btn btn-primary">
              <BarChart3 size={16} /> Ask the analyst
            </Link>
          ) : null
        }
      >
        {organisation?.name} &middot; {workspace?.name}
      </PageHeader>
      {error ? <Alert tone="error">{error.message}</Alert> : null}

      <div className="grid grid-4">
        <div className="card stat">
          <div className="stat-icon"><Database size={19} /></div>
          <div className="label">Datasets</div>
          <div className="value">{formatInteger(usage.data?.totals.datasets)}</div>
          <div className="hint">{formatBytes(usage.data?.totals.storage_bytes)} stored</div>
        </div>
        <div className="card stat">
          <div className="stat-icon"><BarChart3 size={19} /></div>
          <div className="label">Analyses this month</div>
          <div className="value">
            {formatInteger(usage.data?.analyses.used)}
            <span className="muted" style={{ fontSize: 15, fontWeight: 500 }}> / {formatInteger(usage.data?.analyses.limit)}</span>
          </div>
          <div className="hint">Failed and cancelled runs are not counted</div>
        </div>
        <div className="card stat">
          <div className="stat-icon"><Table2 size={19} /></div>
          <div className="label">Rows analysed</div>
          <div className="value">{formatInteger(usage.data?.this_month.rows_analysed ?? 0)}</div>
          <div className="hint">this month</div>
        </div>
        <div className="card stat">
          <div className="stat-icon"><FileText size={19} /></div>
          <div className="label">Reports</div>
          <div className="value">{formatInteger(usage.data?.totals.reports)}</div>
          <div className="hint">PDF, Excel and HTML files</div>
        </div>
      </div>

      {datasets.data && datasets.data.length === 0 ? (
        <section className="card card-pad stack">
          <div style={{ textAlign: "center" }}>
            <h2>Start with your first analysis</h2>
            <p className="muted small" style={{ marginTop: 4 }}>
              No file to hand? Use the sample: a year of sales for a fictional wholesaler, with realistic data problems.
            </p>
          </div>
          <div className="steps3">
            <div>
              <h3>Upload a dataset</h3>
              <p className="small muted">An Excel or CSV export of sales, invoices or any table with headings.</p>
            </div>
            <div>
              <h3>Ask a question</h3>
              <p className="small muted">For example: &ldquo;Which products are most profitable?&rdquo;</p>
            </div>
            <div>
              <h3>Download the report</h3>
              <p className="small muted">Watch the agents work, check the evidence, then take the PDF or Excel file.</p>
            </div>
          </div>
          <UploadPanel maxUploadMb={usage.data?.limits.max_upload_mb ?? 50} onUploaded={(id) => router.push(`/datasets/${id}`)} />
        </section>
      ) : null}

      <section className="card">
        <div className="card-head">
          <h2>Recent analyses</h2>
          <Link href="/analyst" className="small">
            Open analyst <ArrowRight size={13} style={{ verticalAlign: -2 }} />
          </Link>
        </div>
        {jobs.loading && !jobs.data ? (
          <Loading />
        ) : jobs.data?.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Request</th>
                  <th className="hide-sm">Dataset</th>
                  <th>Status</th>
                  <th className="hide-xs">When</th>
                </tr>
              </thead>
              <tbody>
                {jobs.data.map((job) => (
                  <tr key={job.id}>
                    <td>
                      <Link className="rowlink" href={`/analyst?job=${job.id}`}>
                        {job.prompt}
                      </Link>
                      {job.headline ? <div className="small muted">{job.headline}</div> : null}
                    </td>
                    <td className="small hide-sm">{job.dataset?.name ?? "–"}</td>
                    <td>
                      <JobBadge status={job.status} />
                    </td>
                    <td className="small muted hide-xs" style={{ whiteSpace: "nowrap" }}>{timeAgo(job.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={<FileText size={34} />} title="No analyses yet">
            <span>Upload a dataset, then ask the analyst a question about it.</span>
          </Empty>
        )}
      </section>
    </>
  );
}
