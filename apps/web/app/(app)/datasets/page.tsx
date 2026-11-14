"use client";

import { Database } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { UploadPanel } from "@/components/UploadPanel";
import { Alert, DatasetBadge, Empty, Loading, PageHeader } from "@/components/ui";
import { useApi } from "@/hooks/useApi";
import { formatBytes, formatDateTime, formatInteger } from "@/lib/format";
import { useSession } from "@/services/session";
import type { ClientConfig, Dataset } from "@/types/api";

export default function DatasetsPage() {
  const router = useRouter();
  const { workspace } = useSession();
  const config = useApi<ClientConfig>("/config");
  const datasets = useApi<Dataset[]>(workspace ? `/datasets?workspace_id=${workspace.id}` : null, (data) =>
    data?.some((dataset) => dataset.status === "processing") ? 1500 : null,
  );

  return (
    <>
      <PageHeader title="Datasets">Upload Excel or CSV files. Each upload is imported, profiled and cleaned automatically; the original file is kept unchanged.</PageHeader>
      <section className="card card-pad">
        <UploadPanel maxUploadMb={config.data?.max_upload_mb ?? 50} onUploaded={(id) => router.push(`/datasets/${id}`)} compact />
      </section>
      {datasets.error ? <Alert tone="error">{datasets.error.message}</Alert> : null}
      <section className="card">
        {datasets.loading && !datasets.data ? (
          <Loading />
        ) : datasets.data?.length ? (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Name</th>
                  <th>Status</th>
                  <th className="right">Records</th>
                  <th className="right hide-sm">Columns</th>
                  <th className="right hide-sm">Size</th>
                  <th>Uploaded</th>
                </tr>
              </thead>
              <tbody>
                {datasets.data.map((dataset) => (
                  <tr key={dataset.id}>
                    <td>
                      <Link className="rowlink" href={`/datasets/${dataset.id}`}>
                        {dataset.name}
                      </Link>
                      <div className="small muted">{dataset.source_filename}</div>
                    </td>
                    <td>
                      <DatasetBadge status={dataset.status} />
                    </td>
                    <td className="right">{formatInteger(dataset.latest_version?.row_count)}</td>
                    <td className="right hide-sm">{formatInteger(dataset.latest_version?.column_count)}</td>
                    <td className="right hide-sm">{formatBytes(dataset.latest_version?.size_bytes)}</td>
                    <td className="small muted" style={{ whiteSpace: "nowrap" }}>{formatDateTime(dataset.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <Empty icon={<Database size={34} />} title="No datasets yet">
            <span>Upload a file above, or use the sample data to see how it works.</span>
          </Empty>
        )}
      </section>
    </>
  );
}
