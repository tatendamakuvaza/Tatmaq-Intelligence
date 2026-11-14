"use client";

import { BarChart3 } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";

import { Alert, DatasetBadge, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatBytes, formatDateTime, formatInteger, titleCase } from "@/lib/format";
import type { CleaningIssue, ColumnInfo, Dataset, DatasetProfile } from "@/types/api";

const SEVERITY: Record<CleaningIssue["severity"], string> = { critical: "badge-danger", warning: "badge-warning", info: "badge-info" };
const ISSUE_LABELS: Record<string, string> = {
  missing_values: "Missing values", duplicate_rows: "Duplicate rows", invalid_numbers: "Unreadable numbers",
  invalid_dates: "Unreadable dates", inconsistent_date_formats: "Mixed date formats", ambiguous_dates: "Ambiguous dates",
  date_order_conflict: "Conflicting date order", inconsistent_categories: "Inconsistent spellings", outliers: "Unusual values",
  negative_values: "Negative values", future_dates: "Dates in the future", summary_rows: "Total lines",
  two_digit_years: "Two-digit years", empty_column: "Empty column", precision: "Very large numbers",
};
const STEP_LABELS: Record<string, string> = {
  exclude_summary_rows: "Set aside total lines", standardise_dates: "Standardised dates", convert_serial_dates: "Converted spreadsheet dates",
  normalise_numbers: "Normalised numbers", trim_whitespace: "Removed stray spaces", standardise_categories: "Merged spellings",
  null_tokens: "Read placeholders as missing",
};

function describe(column: ColumnInfo): string {
  const stats = column.details.stats;
  if (!stats) return "";
  if (stats.min !== undefined && stats.max !== undefined) {
    const format = (value: number | string) => (typeof value === "number" ? value.toLocaleString("en-US", { maximumFractionDigits: 2 }) : value);
    return `${format(stats.min)} to ${format(stats.max)}`;
  }
  return (stats.top_values ?? []).slice(0, 3).map((item) => item.value).join(", ");
}

export default function DatasetPage() {
  const { id } = useParams<{ id: string }>();
  const dataset = useApi<Dataset>(`/datasets/${id}`, (data) => (data && ["processing", "pending_upload"].includes(data.status) ? 1200 : null));
  const status = dataset.data?.status;
  const profile = useApi<DatasetProfile>(status === "ready" ? `/datasets/${id}/profile` : null);

  if (dataset.error && !dataset.data) return <Alert tone="error">{dataset.error.message}</Alert>;
  if (!dataset.data) return <Loading label="Loading dataset" />;
  const data = dataset.data;
  const version = data.latest_version;
  const cleaning = profile.data?.cleaning;
  const file = profile.data?.profile.file;
  const preview = profile.data?.profile.preview;
  const issues = [...(cleaning?.issues ?? [])].sort((a, b) => "critical warning info".indexOf(a.severity) - "critical warning info".indexOf(b.severity) || b.count - a.count);

  return (
    <>
      <PageHeader
        title={data.name}
        back={{ href: "/datasets", label: "All datasets" }}
        actions={
          status === "ready" ? (
            <Link href={`/analyst?dataset=${data.id}`} className="btn btn-primary">
              <BarChart3 size={16} /> Analyse this dataset
            </Link>
          ) : null
        }
      >
        {data.source_filename} &middot; uploaded {formatDateTime(data.created_at)}
      </PageHeader>

      {status === "processing" || status === "pending_upload" ? (
        <div className="card">
          <Loading label={status === "processing" ? "The Data Acquisition and Data Cleaning agents are importing this file..." : "Waiting for the file to arrive..."} />
        </div>
      ) : null}
      {status === "failed" ? (
        <Alert tone="error">
          <strong>This file could not be imported.</strong> {data.error_message} Nothing from it is available for analysis.
        </Alert>
      ) : null}
      {profile.error ? <Alert tone="error">{profile.error.message}</Alert> : null}

      {status === "ready" && version ? (
        <>
          <div className="grid grid-4">
            <div className="card stat">
              <div className="label">Records</div>
              <div className="value">{formatInteger(version.row_count)}</div>
              <div className="hint">{cleaning && cleaning.rows_in !== cleaning.rows_out ? `${formatInteger(cleaning.rows_in)} lines in the file` : "rows of data"}</div>
            </div>
            <div className="card stat">
              <div className="label">Columns</div>
              <div className="value">{formatInteger(version.column_count)}</div>
              <div className="hint">{file?.sheet ? `worksheet "${file.sheet}"` : file?.delimiter ? `${file.delimiter}-separated` : ""}</div>
            </div>
            <div className="card stat">
              <div className="label">Duplicates flagged</div>
              <div className="value">{formatInteger(cleaning?.duplicates?.rows ?? 0)}</div>
              <div className="hint">kept in the data for review</div>
            </div>
            <div className="card stat">
              <div className="label">Status</div>
              <div className="value" style={{ fontSize: 18, paddingTop: 6 }}><DatasetBadge status={data.status} /></div>
              <div className="hint">version {version.version_number} &middot; {formatBytes(version.size_bytes)}</div>
            </div>
          </div>

          {profile.loading ? <div className="card"><Loading label="Loading profile" /></div> : null}
          {profile.data ? (
            <>
              <section className="card">
                <div className="card-head">
                  <div>
                    <h2>Column dictionary</h2>
                    <p>What the Data Acquisition Agent recognised in each column. Roles drive which analyses are possible.</p>
                  </div>
                </div>
                <div className="table-wrap">
                  <table className="table table-compact">
                    <thead>
                      <tr>
                        <th>Column</th>
                        <th>Type</th>
                        <th>Recognised as</th>
                        <th className="right">Missing</th>
                        <th className="right">Distinct</th>
                        <th>Range or common values</th>
                      </tr>
                    </thead>
                    <tbody>
                      {profile.data.columns.map((column) => (
                        <tr key={column.name}>
                          <td><strong>{column.name}</strong></td>
                          <td>{titleCase(column.data_type ?? "")}</td>
                          <td>
                            {column.role && !["text", "measure", "dimension", "empty", "date_other"].includes(column.role) ? (
                              <span className="badge badge-blue">{titleCase(column.role)}</span>
                            ) : (
                              <span className="muted">{titleCase(column.role === "date_other" ? "other date" : (column.role ?? ""))}</span>
                            )}
                          </td>
                          <td className="right">{formatInteger(column.null_count)}</td>
                          <td className="right">{formatInteger(column.distinct_count)}</td>
                          <td className="small muted">{describe(column)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>

              <div className="grid grid-2">
                <section className="card">
                  <div className="card-head">
                    <div>
                      <h2>Data quality findings</h2>
                      <p>Flagged for your attention. Nothing was deleted and no missing value was filled in.</p>
                    </div>
                  </div>
                  {issues.length ? (
                    <ul className="findings">
                      {issues.map((issue, index) => (
                        <li className="finding" key={index}>
                          <div className="finding-head">
                            <strong>{ISSUE_LABELS[issue.code] ?? titleCase(issue.code)}</strong>
                            <span className={`badge ${SEVERITY[issue.severity]}`}>{titleCase(issue.severity)}</span>
                            <span className="tiny muted num">{formatInteger(issue.count)} {issue.count === 1 ? "row" : "rows"}</span>
                          </div>
                          <p className="small">{issue.message}</p>
                          {issue.rows.length ? <p className="tiny muted">Source rows: {issue.rows.join(", ")}{issue.count > issue.rows.length ? ", ..." : ""}</p> : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="card-pad muted">No problems were found.</p>
                  )}
                </section>

                <section className="card">
                  <div className="card-head">
                    <div>
                      <h2>Cleaning log</h2>
                      <p>Every change made to the working copy. Your uploaded file is untouched.</p>
                    </div>
                  </div>
                  {cleaning?.log?.length ? (
                    <ul className="findings">
                      {cleaning.log.map((entry, index) => {
                        const example = entry.examples.find((item) => "before" in item && "after" in item && item.after !== null);
                        return (
                          <li className="finding" key={index}>
                            <div className="finding-head">
                              <strong>{STEP_LABELS[entry.step] ?? titleCase(entry.step)}</strong>
                              {entry.column ? <span className="badge">{entry.column}</span> : null}
                              <span className="tiny muted num">{formatInteger(entry.rows_affected)} {entry.rows_affected === 1 ? "value" : "values"}</span>
                            </div>
                            <p className="small">{entry.description}</p>
                            {example ? (
                              <p className="tiny muted mono">
                                {String(example.before)} &rarr; {String(example.after)}
                              </p>
                            ) : null}
                          </li>
                        );
                      })}
                    </ul>
                  ) : (
                    <p className="card-pad muted">No changes were needed.</p>
                  )}
                </section>
              </div>

              {preview ? (
                <section className="card">
                  <div className="card-head">
                    <div>
                      <h2>First rows, as uploaded</h2>
                      <p>{(profile.data.profile.processing_log ?? []).join(" ")}</p>
                    </div>
                  </div>
                  <div className="table-wrap">
                    <table className="table table-compact">
                      <thead>
                        <tr>{preview.columns.map((column) => <th key={column}>{column}</th>)}</tr>
                      </thead>
                      <tbody>
                        {preview.rows.map((row, index) => (
                          <tr key={index}>{row.map((cell, position) => <td key={position} className={cell === null ? "muted" : ""}>{cell ?? "(blank)"}</td>)}</tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              ) : null}

              <p className="tiny muted mono">File fingerprint (SHA-256): {version.sha256_hash}</p>
            </>
          ) : null}
        </>
      ) : null}
    </>
  );
}
