import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { deletePreference, fetchPreferences, savePreference } from "../api/client";

type Values = Record<string, string>;

/** One fetch per browser session; every page reads from this cache. */
let cache: Promise<Map<string, Values>> | null = null;

function loadAll(): Promise<Map<string, Values>> {
  cache ??= fetchPreferences()
    .then((payload) => new Map(payload.data.map((row) => [row.key, row.value])))
    .catch(() => {
      cache = null; // try again next time
      return new Map<string, Values>();
    });
  return cache;
}

/**
 * Saved default filters for a page. The URL stays the source of truth for the applied filters;
 * this hook only fills it in when the page opens without any filter parameter, and offers to save
 * or clear the stored default. `builtin` is what applies when nothing is saved.
 */
export function useFilterDefaults<Filters extends Values>(page: string, builtin: Filters) {
  const key = `filters:${page}`;
  const [params, setParams] = useSearchParams();
  const [saved, setSaved] = useState<Filters | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const appliedOnOpen = useRef(false);
  // The saved default fills the URL once, when the page opens: read the URL and the built-in filters
  // as they are then, so later URL changes (the user's own filtering) never re-run it.
  const opening = useRef({ builtin, params, setParams });

  useEffect(() => {
    let cancelled = false;
    void loadAll().then((all) => {
      if (cancelled) return;
      const { builtin, params, setParams } = opening.current;
      const filterKeys = Object.keys(builtin) as (keyof Filters & string)[];
      const stored = all.get(key);
      const merged = stored ? ({ ...builtin, ...stored } as Filters) : null;
      setSaved(merged);
      if (merged && !appliedOnOpen.current && !filterKeys.some((name) => params.has(name))) {
        appliedOnOpen.current = true;
        const next = new URLSearchParams(params);
        for (const name of filterKeys) {
          if (merged[name] && merged[name] !== builtin[name]) next.set(name, merged[name]);
        }
        if (next.toString() !== params.toString()) setParams(next, { replace: true });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [key]);

  const save = useCallback(
    async (filters: Filters) => {
      setBusy(true);
      setError(null);
      try {
        const row = await savePreference(key, filters);
        const merged = { ...builtin, ...row.value } as Filters;
        setSaved(merged);
        (await loadAll()).set(key, row.value);
      } catch (reason) {
        setError(`Could not save the default: ${reason instanceof Error ? reason.message : String(reason)}`);
      } finally {
        setBusy(false);
      }
    },
    [key, builtin],
  );

  const clear = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await deletePreference(key);
      setSaved(null);
      (await loadAll()).delete(key);
    } catch (reason) {
      setError(`Could not clear the default: ${reason instanceof Error ? reason.message : String(reason)}`);
    } finally {
      setBusy(false);
    }
  }, [key]);

  return { defaults: saved ?? builtin, saved, busy, error, save, clear };
}
