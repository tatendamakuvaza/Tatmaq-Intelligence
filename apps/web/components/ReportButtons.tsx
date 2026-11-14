"use client";

import { Download, Eye, FileSpreadsheet, FileText, Globe, X } from "lucide-react";
import { useState } from "react";

import { Alert } from "@/components/ui";
import { formatBytes } from "@/lib/format";
import { downloadReport, reportHtml } from "@/services/api";
import type { Report } from "@/types/api";

const FORMATS: Record<string, { label: string; icon: typeof FileText; order: number }> = {
  pdf: { label: "PDF", icon: FileText, order: 0 },
  xlsx: { label: "Excel", icon: FileSpreadsheet, order: 1 },
  html: { label: "HTML", icon: Globe, order: 2 },
};

export function ReportButtons({ reports, size = "md" }: { reports: Report[]; size?: "sm" | "md" }) {
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ title: string; html: string } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const ordered = [...reports].sort((a, b) => (FORMATS[a.format]?.order ?? 9) - (FORMATS[b.format]?.order ?? 9));
  const html = ordered.find((report) => report.format === "html");
  const button = `btn btn-secondary${size === "sm" ? " btn-sm" : ""}`;

  async function run(key: string, action: () => Promise<void>) {
    setBusy(key);
    setError(null);
    try {
      await action();
    } catch (caught) {
      setError((caught as Error).message);
    }
    setBusy(null);
  }

  return (
    <>
      <div className="row">
        {html ? (
          <button
            type="button"
            className={size === "sm" ? "btn btn-primary btn-sm" : "btn btn-primary"}
            disabled={busy !== null}
            onClick={() => void run("view", async () => setPreview({ title: html.title ?? "Report", html: await reportHtml(html) }))}
          >
            <Eye size={15} /> {busy === "view" ? "Opening..." : "View report"}
          </button>
        ) : null}
        {ordered.map((report) => {
          const format = FORMATS[report.format] ?? { label: report.format.toUpperCase(), icon: Download };
          const Icon = format.icon;
          return (
            <button key={report.id} type="button" className={button} disabled={busy !== null} title={`${report.filename ?? ""} (${formatBytes(report.size_bytes)})`} onClick={() => void run(report.id, () => downloadReport(report))}>
              <Icon size={15} /> {format.label}
            </button>
          );
        })}
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
      {preview ? (
        <div className="modal-back" role="dialog" aria-modal="true" aria-label={preview.title} onClick={(event) => event.target === event.currentTarget && setPreview(null)}>
          <div className="modal">
            <div className="card-head">
              <h2>{preview.title}</h2>
              <button type="button" className="btn btn-ghost btn-sm" onClick={() => setPreview(null)}>
                <X size={16} /> Close
              </button>
            </div>
            {/* sandbox with no permissions: the report is displayed, but nothing in it can run or navigate */}
            <iframe title={preview.title} sandbox="" srcDoc={preview.html} />
          </div>
        </div>
      ) : null}
    </>
  );
}
