import { useCallback, useEffect, useRef, useState } from "react";

type Values = Record<string, string>;

/**
 * Filters that apply as they change. `set` debounces (for text fields), `setNow` applies at once
 * (for dropdowns and toggles), `flush` applies whatever is pending (Enter in a text field). The
 * draft follows `applied` whenever the URL changes underneath, unless an edit is still pending.
 */
export function useLiveFilters<Filters extends Values>(applied: Filters, apply: (next: Filters) => void, delay = 400) {
  const [draft, setDraft] = useState<Filters>(applied);
  const draftRef = useRef<Filters>(applied);
  const applyRef = useRef(apply);
  applyRef.current = apply;
  const pending = useRef<{ timer: ReturnType<typeof setTimeout>; next: Filters } | null>(null);

  useEffect(() => {
    if (pending.current) return;
    draftRef.current = applied;
    setDraft(applied);
  }, [applied]);

  useEffect(
    () => () => {
      if (pending.current) clearTimeout(pending.current.timer);
    },
    [],
  );

  const flush = useCallback(() => {
    if (!pending.current) return;
    clearTimeout(pending.current.timer);
    const { next } = pending.current;
    pending.current = null;
    applyRef.current(next);
  }, []);

  const update = useCallback(
    (patch: Partial<Filters>, immediate: boolean) => {
      const next = { ...draftRef.current, ...patch } as Filters;
      draftRef.current = next;
      setDraft(next);
      if (pending.current) clearTimeout(pending.current.timer);
      if (immediate) {
        pending.current = null;
        applyRef.current(next);
        return;
      }
      const timer = setTimeout(() => {
        pending.current = null;
        applyRef.current(next);
      }, delay);
      pending.current = { timer, next };
    },
    [delay],
  );

  return {
    draft,
    set: useCallback((patch: Partial<Filters>) => update(patch, false), [update]),
    setNow: useCallback((patch: Partial<Filters>) => update(patch, true), [update]),
    flush,
  };
}
