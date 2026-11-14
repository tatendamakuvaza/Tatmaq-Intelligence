"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { api, ApiError } from "@/services/api";

type Result<T> = { data: T | undefined; error: ApiError | null; loading: boolean; reload: () => void };
type Loaded<T> = { path: string | null; data: T | undefined; error: ApiError | null };

/**
 * Loads a resource and, optionally, keeps it fresh.
 *
 * `refreshMs` may be a number, or a function of the latest data that returns the next
 * delay (or null to stop): that is how a job is polled until it finishes and no longer.
 *
 * What was loaded is stored together with the path it was loaded from, so data for a
 * previous resource is never shown under a new one, while a reload of the same
 * resource keeps the current data on screen until the fresh copy arrives.
 */
export function useApi<T>(path: string | null, refreshMs?: number | ((data: T | undefined) => number | null)): Result<T> {
  const [loaded, setLoaded] = useState<Loaded<T>>({ path: null, data: undefined, error: null });
  const [version, setVersion] = useState(0);
  const refresh = useRef(refreshMs);
  useEffect(() => {
    refresh.current = refreshMs;
  });

  useEffect(() => {
    if (path === null) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();

    const load = async () => {
      let latest: T | undefined;
      try {
        latest = await api.get<T>(path, { signal: controller.signal });
        if (cancelled) return;
        setLoaded({ path, data: latest, error: null });
      } catch (caught) {
        if (cancelled || (caught as Error).name === "AbortError") return;
        const error = caught instanceof ApiError ? caught : new ApiError((caught as Error).message, 0, "error");
        setLoaded((previous) => ({ path, data: previous.path === path ? previous.data : undefined, error }));
      }
      const next = typeof refresh.current === "function" ? refresh.current(latest) : refresh.current;
      if (!cancelled && next) timer = setTimeout(() => void load(), next);
    };

    void load();
    return () => {
      cancelled = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [path, version]);

  const reload = useCallback(() => setVersion((current) => current + 1), []);
  const current = loaded.path === path;
  return {
    data: current ? loaded.data : undefined,
    error: current ? loaded.error : null,
    loading: path !== null && !current,
    reload,
  };
}
