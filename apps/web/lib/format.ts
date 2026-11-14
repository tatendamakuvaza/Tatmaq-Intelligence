// How figures are written in the app. Mirrors apps/api/app/analytics/formatting.py so
// the screen, the PDF and the Excel file show the same thing.

import type { JobStatus, ValueFormat } from "@/types/api";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

function grouped(value: number, places: number): string {
  return value.toLocaleString("en-US", { minimumFractionDigits: places, maximumFractionDigits: places });
}

export function formatMoney(value: number, currency: string | null): string {
  const body = grouped(Math.abs(value), 2);
  const prefix = currency ? `${currency} ` : "";
  return value < 0 ? `-${prefix}${body}` : `${prefix}${body}`;
}

export function formatValue(value: string | number | null | undefined, format: ValueFormat, currency: string | null = null): string {
  if (value === null || value === undefined || value === "") return "–";
  if (format === "text") return String(value);
  if (format === "month") {
    const [year, month] = String(value).split("-");
    return `${MONTHS[Number(month) - 1] ?? month} ${year}`;
  }
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  switch (format) {
    case "money":
      return formatMoney(number, currency);
    case "percent":
      return `${grouped(number, 2)}%`;
    case "integer":
      return grouped(Math.round(number), 0);
    case "number4":
      return grouped(number, 4);
    default:
      return grouped(number, 2);
  }
}

/** Short axis labels: 8500 -> 8.5k */
export function compact(value: number, format: ValueFormat): string {
  if (format === "percent") return `${Number(value.toFixed(1))}%`;
  const magnitude = Math.abs(value);
  if (magnitude >= 1_000_000) return `${Number((value / 1_000_000).toFixed(1))}M`;
  if (magnitude >= 1_000) return `${Number((value / 1_000).toFixed(1))}k`;
  return `${Number(value.toFixed(2))}`;
}

export function formatInteger(value: number | null | undefined): string {
  return value === null || value === undefined ? "–" : grouped(value, 0);
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "–";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "";
  if (ms < 1000) return `${Math.max(ms, 1)} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "–";
  const date = new Date(iso);
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
  return `${date.getDate()} ${MONTHS[date.getMonth()]} ${date.getFullYear()}, ${time}`;
}

export function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return formatDateTime(iso).split(",")[0];
}

export const JOB_STATUS_LABELS: Record<JobStatus, string> = {
  queued: "Queued",
  validating_dataset: "Validating dataset",
  planning: "Planning",
  executing_agents: "Agents working",
  quality_verification: "Verifying results",
  generating_report: "Writing report",
  completed: "Completed",
  partially_completed: "Partly completed",
  failed: "Failed",
  cancelled: "Cancelled",
};

export function titleCase(text: string): string {
  return text.replace(/_/g, " ").replace(/^\w/, (letter) => letter.toUpperCase());
}
