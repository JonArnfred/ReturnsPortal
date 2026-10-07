import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

/**
 * "Hide amounts" mode: masks every figure that reveals the size of the holdings (currency amounts,
 * share quantities, units) while leaving prices, FX rates, unit prices and percentages visible, so
 * returns can be shown to others without showing how much money is invested.
 *
 * The choice is kept in a cookie so the server render already knows it and the page never flashes
 * the real figures before hydration; `server.mjs` copies the cookie into `initialData.hideAmounts`.
 */
export const HIDE_AMOUNTS_COOKIE = "rp_hide_amounts";

type PrivacyContextValue = {
  hidden: boolean;
  setHidden: (hidden: boolean) => void;
};

const PrivacyContext = createContext<PrivacyContextValue>({ hidden: false, setHidden: () => undefined });

export function PrivacyProvider({ initialHidden = false, children }: { initialHidden?: boolean; children: ReactNode }) {
  const [hidden, setHiddenState] = useState(initialHidden);
  const setHidden = useCallback((next: boolean) => {
    setHiddenState(next);
    if (typeof document !== "undefined") {
      document.cookie = `${HIDE_AMOUNTS_COOKIE}=${next ? "1" : "0"}; path=/; max-age=31536000; samesite=lax`;
    }
  }, []);
  const value = useMemo(() => ({ hidden, setHidden }), [hidden, setHidden]);
  return <PrivacyContext.Provider value={value}>{children}</PrivacyContext.Provider>;
}

export function usePrivacy(): PrivacyContextValue {
  return useContext(PrivacyContext);
}
