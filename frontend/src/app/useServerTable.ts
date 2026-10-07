import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import type { PageMeta } from "../api/client";

type Loaded<Row> = { rows: Row[]; meta: PageMeta | null; loading: boolean; error: string | null };

/**
 * Fetches a paged endpoint whenever the URL query changes. The URL is the state: page, per_page,
 * order_by, order and any filter parameters are forwarded as-is, with fixed parameters merged in.
 */
export function useServerTable<Row>(
  fetcher: (query: URLSearchParams) => Promise<{ data: Row[]; meta: PageMeta }>,
  fixed: Record<string, string>,
  defaults: Record<string, string>,
): Loaded<Row> {
  const [params] = useSearchParams();
  const query = new URLSearchParams(defaults);
  params.forEach((value, key) => query.set(key, value));
  for (const [key, value] of Object.entries(fixed)) query.set(key, value);
  const queryString = query.toString();
  const [state, setState] = useState<Loaded<Row>>({ rows: [], meta: null, loading: true, error: null });

  useEffect(() => {
    let cancelled = false;
    setState((previous) => ({ ...previous, loading: true }));
    fetcher(new URLSearchParams(queryString))
      .then((payload) => {
        if (!cancelled) setState({ rows: payload.data, meta: payload.meta, loading: false, error: null });
      })
      .catch((error: unknown) => {
        if (!cancelled) setState({ rows: [], meta: null, loading: false, error: error instanceof Error ? error.message : String(error) });
      });
    return () => {
      cancelled = true;
    };
  }, [fetcher, queryString]);

  return state;
}
