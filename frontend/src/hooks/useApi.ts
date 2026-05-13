import useSWR, { SWRConfiguration, SWRResponse } from "swr";

import { apiFetch } from "@/api/client";
import type { DashboardEndpoint, DashboardEndpointMap } from "@/types";

// Default refresh intervals (ms).  Individual pages can override by passing
// `refreshInterval` via the options arg.  The raw values come from Vite env
// vars so they can be tuned per environment without a rebuild.
const DEFAULT_REFRESH_MS = 0; // no polling by default — pages opt in
export const REFRESH_TODAY_MS = Number(
  import.meta.env.VITE_REFRESH_TODAY_MS ?? 5 * 60 * 1000,
);
export const REFRESH_STATUS_MS = Number(
  import.meta.env.VITE_REFRESH_STATUS_MS ?? 30 * 1000,
);

/**
 * Typed wrapper around useSWR that knows every dashboard endpoint shape.
 *
 * Example:
 *   const { data, error, isLoading } = useApi("/api/dashboard/today-picks");
 *   //      ^^^^ typed as TodayPicksResponse | undefined
 */
export function useApi<E extends DashboardEndpoint>(
  endpoint: E | null,
  options?: SWRConfiguration<DashboardEndpointMap[E]>,
): SWRResponse<DashboardEndpointMap[E]> {
  return useSWR<DashboardEndpointMap[E]>(
    endpoint,
    (key) => apiFetch<DashboardEndpointMap[E]>(key),
    {
      refreshInterval: DEFAULT_REFRESH_MS,
      revalidateOnFocus: true,
      shouldRetryOnError: true,
      ...options,
    },
  );
}

/** Escape hatch for non-dashboard endpoints (e.g. /api/tab/*). */
export function useApiRaw<T>(
  key: string | null,
  options?: SWRConfiguration<T>,
): SWRResponse<T> {
  return useSWR<T>(key, (k: string) => apiFetch<T>(k), options);
}
