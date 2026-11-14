// The one place that talks to the TATMAQ API.

import { API_BASE, resolveApiUrl } from "@/lib/config";
import { auth } from "@/services/auth";
import type { Report } from "@/types/api";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

let organisationId: string | null = null;
let onUnauthorised: () => void = () => {};

export function setOrganisation(id: string | null): void {
  organisationId = id;
}

export function setUnauthorisedHandler(handler: () => void): void {
  onUnauthorised = handler;
}

type Options = { body?: unknown; headers?: Record<string, string>; signal?: AbortSignal };

async function request<T>(method: string, path: string, options: Options = {}): Promise<T> {
  const session = await auth.current();
  const headers: Record<string, string> = { ...options.headers };
  if (session) headers.Authorization = `Bearer ${session.token}`;
  if (organisationId) headers["X-Organisation-Id"] = organisationId;
  if (options.body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: options.signal,
      cache: "no-store",
    });
  } catch (error) {
    if ((error as Error).name === "AbortError") throw error;
    throw new ApiError("Could not reach the server. Check your connection and try again.", 0, "network_error");
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    if (response.status === 401) onUnauthorised();
    throw new ApiError(
      body?.error?.message ?? `The server returned an error (${response.status}).`,
      response.status,
      body?.error?.code ?? "error",
    );
  }
  return body as T;
}

export const api = {
  get: <T>(path: string, options?: Options) => request<T>("GET", path, options),
  post: <T>(path: string, body?: unknown, options?: Options) => request<T>("POST", path, { ...options, body: body ?? {} }),
  put: <T>(path: string, body?: unknown, options?: Options) => request<T>("PUT", path, { ...options, body: body ?? {} }),
};

type UploadTarget = {
  dataset_id: string;
  upload: { method: string; url: string; headers: Record<string, string> };
};

function sendFile(target: UploadTarget["upload"], file: Blob, onProgress: (fraction: number) => void): Promise<void> {
  // XMLHttpRequest rather than fetch: it is the only way to report upload progress.
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open(target.method, resolveApiUrl(target.url));
    Object.entries(target.headers).forEach(([name, value]) => xhr.setRequestHeader(name, value));
    xhr.upload.onprogress = (event) => event.lengthComputable && onProgress(event.loaded / event.total);
    xhr.onerror = () => reject(new ApiError("The upload was interrupted. Check your connection and try again.", 0, "network_error"));
    xhr.onload = () => {
      // 409 means this exact upload already arrived (a retry after a dropped response): carry on.
      if ((xhr.status >= 200 && xhr.status < 300) || xhr.status === 409) return resolve();
      let message = `The upload failed (${xhr.status}).`;
      try {
        message = JSON.parse(xhr.responseText)?.error?.message ?? message;
      } catch {
        /* keep the generic message */
      }
      reject(new ApiError(message, xhr.status, "upload_failed"));
    };
    xhr.send(file);
  });
}

/** The three-step upload: ask for a link, send the file to it, confirm. */
export async function uploadDataset(
  file: Blob,
  filename: string,
  workspaceId: string,
  onProgress: (fraction: number) => void = () => {},
): Promise<{ dataset_id: string; dataset_version_id: string }> {
  const target = await api.post<UploadTarget>("/datasets/upload-url", {
    workspace_id: workspaceId,
    filename,
    size_bytes: file.size,
  });
  await sendFile(target.upload, file, onProgress);
  return api.post(`/datasets/${target.dataset_id}/complete`);
}

type DownloadLink = { url: string; filename: string; content_type: string };

export async function reportLink(report: Report): Promise<DownloadLink> {
  const link = await api.get<DownloadLink>(`/reports/${report.id}/download`);
  return { ...link, url: resolveApiUrl(link.url) };
}

export async function downloadReport(report: Report): Promise<void> {
  const link = await reportLink(report);
  const anchor = document.createElement("a");
  anchor.href = link.url;
  anchor.download = link.filename;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
}

export async function reportHtml(report: Report): Promise<string> {
  const link = await reportLink(report);
  const response = await fetch(link.url);
  if (!response.ok) throw new ApiError("The report could not be loaded.", response.status, "report_unavailable");
  return response.text();
}
