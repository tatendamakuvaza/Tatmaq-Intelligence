"use client";

import { Sparkles, UploadCloud } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";

import { Alert } from "@/components/ui";
import { SAMPLE_DATASET } from "@/lib/config";
import { uploadDataset } from "@/services/api";
import { useSession } from "@/services/session";

const ACCEPT = ".xlsx,.csv";

type Props = { maxUploadMb: number; onUploaded: (datasetId: string) => void; compact?: boolean };

export function UploadPanel({ maxUploadMb, onUploaded, compact = false }: Props) {
  const { workspace, can } = useSession();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [filename, setFilename] = useState("");
  const [error, setError] = useState<string | null>(null);
  const busy = progress !== null;

  async function send(file: Blob, name: string) {
    if (!workspace) return;
    setError(null);
    if (!/\.(xlsx|csv)$/i.test(name)) {
      return setError("Upload an Excel workbook (.xlsx) or a CSV file (.csv). Older .xls files: use Save As > Excel Workbook first.");
    }
    if (file.size > maxUploadMb * 1024 * 1024) return setError(`This file is larger than the ${maxUploadMb} MB limit.`);
    if (file.size === 0) return setError("This file is empty.");
    setFilename(name);
    setProgress(0);
    try {
      const result = await uploadDataset(file, name, workspace.id, setProgress);
      onUploaded(result.dataset_id);
    } catch (caught) {
      setError((caught as Error).message);
    }
    setProgress(null);
  }

  async function loadSample() {
    setError(null);
    setFilename(SAMPLE_DATASET.filename);
    setProgress(0);
    try {
      const response = await fetch(SAMPLE_DATASET.url);
      if (!response.ok) throw new Error("The sample dataset could not be loaded.");
      const blob = await response.blob();
      setProgress(null);
      await send(blob, SAMPLE_DATASET.filename);
    } catch (caught) {
      setError((caught as Error).message);
      setProgress(null);
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && !busy) void send(file, file.name);
  }

  if (!can("datasets:upload")) {
    return <Alert tone="info">Your role can view datasets but not upload them.</Alert>;
  }

  return (
    <div className="stack-sm">
      <div
        className="drop"
        data-active={dragging}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
      >
        {busy ? (
          <>
            <strong>Uploading {filename}</strong>
            <div className="progress" role="progressbar" aria-valuenow={Math.round((progress ?? 0) * 100)} aria-valuemin={0} aria-valuemax={100}>
              <div style={{ width: `${Math.round((progress ?? 0) * 100)}%` }} />
            </div>
            <span className="small muted">{Math.round((progress ?? 0) * 100)}%</span>
          </>
        ) : (
          <>
            <UploadCloud size={compact ? 24 : 30} />
            <div>
              <strong>Drop an Excel or CSV file here</strong>
              <div className="small muted">.xlsx or .csv, up to {maxUploadMb} MB. The file you upload is never modified.</div>
            </div>
            <div className="row" style={{ justifyContent: "center" }}>
              <button type="button" className="btn btn-primary" onClick={() => input.current?.click()}>
                Choose file
              </button>
              <button type="button" className="btn btn-secondary" onClick={() => void loadSample()}>
                <Sparkles size={15} /> Use sample data
              </button>
            </div>
          </>
        )}
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          aria-label="Choose a dataset file"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) void send(file, file.name);
            event.target.value = "";
          }}
        />
      </div>
      {error ? <Alert tone="error">{error}</Alert> : null}
    </div>
  );
}
