"use client";

import { FileText } from "lucide-react";
import Link from "next/link";

import { ReportButtons } from "@/components/ReportButtons";
import { Alert, Empty, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatDateTime } from "@/lib/format";
import type { Report } from "@/types/api";

export default function ReportsPage() {
  const reports = useApi<Report[]>("/reports");
  const byJob = new Map<string, Report[]>();
  reports.data?.forEach((report) => byJob.set(report.job_id, [...(byJob.get(report.job_id) ?? []), report]));

  return (
    <>
      <PageHeader title="Reports">Every completed analysis produces a PDF, an Excel workbook and an HTML report built from the same verified findings.</PageHeader>
      {reports.error ? <Alert tone="error">{reports.error.message}</Alert> : null}
      <section className="card">
        {reports.loading && !reports.data ? (
          <Loading />
        ) : byJob.size ? (
          [...byJob.entries()].map(([jobId, files]) => (
            <div key={jobId} className="report-row">
              <div>
                <Link href={`/analyst?job=${jobId}`} className="rowlink">
                  {files[0].title}
                </Link>
                <div className="small muted">
                  &ldquo;{files[0].prompt}&rdquo; &middot; {files[0].dataset_name} &middot; {formatDateTime(files[0].created_at)}
                </div>
              </div>
              <ReportButtons reports={files} size="sm" />
            </div>
          ))
        ) : (
          <Empty icon={<FileText size={34} />} title="No reports yet">
            <span>Reports appear here when an analysis finishes.</span>
            <Link href="/analyst" className="btn btn-primary">
              Ask the analyst
            </Link>
          </Empty>
        )}
      </section>
    </>
  );
}
