import { AlertTriangle, ArrowLeft, CheckCircle2, Info, XCircle } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { JOB_STATUS_LABELS } from "@/lib/format";
import type { DatasetStatus, JobStatus } from "@/types/api";

const JOB_TONE: Record<JobStatus, string> = {
  queued: "badge-info", validating_dataset: "badge-progress", planning: "badge-progress", executing_agents: "badge-progress",
  quality_verification: "badge-progress", generating_report: "badge-progress", completed: "badge-done",
  partially_completed: "badge-warning", failed: "badge-danger", cancelled: "",
};

export function JobBadge({ status }: { status: JobStatus }) {
  return <span className={`badge ${JOB_TONE[status]}`}>{JOB_STATUS_LABELS[status]}</span>;
}

const DATASET: Record<DatasetStatus, [string, string]> = {
  pending_upload: ["Waiting for file", "badge-info"],
  processing: ["Processing", "badge-progress"],
  ready: ["Ready", "badge-done"],
  failed: ["Failed", "badge-danger"],
};

export function DatasetBadge({ status }: { status: DatasetStatus }) {
  const [label, tone] = DATASET[status];
  return <span className={`badge ${tone}`}>{label}</span>;
}

type Tone = "error" | "warning" | "info" | "success";
const ICONS = { error: XCircle, warning: AlertTriangle, info: Info, success: CheckCircle2 };

export function Alert({ tone = "info", children }: { tone?: Tone; children: ReactNode }) {
  const Icon = ICONS[tone];
  return (
    <div className={`alert alert-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={16} />
      <div className="grow">{children}</div>
    </div>
  );
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon}
      <strong>{title}</strong>
      {children}
    </div>
  );
}

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <div className="empty" role="status">
      <div className="spinner" />
      <span>{label}</span>
    </div>
  );
}

type PageHeaderProps = { title: string; children?: ReactNode; actions?: ReactNode; back?: { href: string; label: string } };

// The blue band at the top of every page. The block that follows it sits across its lower edge.
export function PageHeader({ title, children, actions, back }: PageHeaderProps) {
  return (
    <header className="page-header">
      <div className="page-title">
        {back ? (
          <Link href={back.href} className="page-back">
            <ArrowLeft size={14} /> {back.label}
          </Link>
        ) : null}
        <h1>{title}</h1>
        {children ? <p>{children}</p> : null}
      </div>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
