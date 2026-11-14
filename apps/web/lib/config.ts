// Build-time configuration. Everything here is public: it ships to the browser.

const apiOrigin = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/$/, "");

/** Base for API calls: the API's own origin if configured, otherwise this site's /api proxy. */
export const API_BASE = `${apiOrigin || "/api"}/v1`;

/** Turns a path the API returned (for local file links) into something the browser can fetch. */
export function resolveApiUrl(url: string): string {
  return url.startsWith("/") ? `${apiOrigin || "/api"}${url}` : url;
}

export const SUPABASE_URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
export const SUPABASE_PUBLISHABLE_KEY = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY ?? "";

/** Supabase Auth is used when it is configured; otherwise the API's own built-in sign-in. */
export const AUTH_MODE: "supabase" | "builtin" = SUPABASE_URL && SUPABASE_PUBLISHABLE_KEY ? "supabase" : "builtin";

export const SAMPLE_DATASET = { url: "/samples/sample-sales.xlsx", filename: "sample-sales.xlsx" };
