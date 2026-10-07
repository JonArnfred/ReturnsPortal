import TrendingDownIcon from "@mui/icons-material/TrendingDown";
import TrendingUpIcon from "@mui/icons-material/TrendingUp";
import Box from "@mui/material/Box";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useMemo } from "react";
import { usePrivacy } from "../app/privacy";
import { formatNumber, formatPct, formatQuantity, signColor } from "./format";

/** What a masked figure looks like while "hide amounts" is on. */
export const AMOUNT_MASK = "•••••";

const isMissing = (value: number | null | undefined) => value === null || value === undefined || Number.isNaN(value);

/**
 * Formatters that honour the "hide amounts" toggle. Use them for every figure that reveals the
 * size of the holdings: currency amounts, share quantities, units. Prices, FX rates, unit prices
 * and percentages stay visible and keep using `format.ts` directly.
 */
export function useAmounts() {
  const { hidden } = usePrivacy();
  return useMemo(
    () => ({
      hidden,
      /** Currency amount; missing values still show as "-". */
      amount: (value: number | null | undefined, digits = 0) => (hidden && !isMissing(value) ? AMOUNT_MASK : formatNumber(value, digits)),
      /** Amount followed by its currency code. */
      money: (value: number | null | undefined, currency: string, digits = 0) =>
        isMissing(value) ? "-" : `${hidden ? AMOUNT_MASK : formatNumber(value, digits)} ${currency}`,
      /** Share quantity or unit count. */
      quantity: (value: number | null | undefined) => (hidden && !isMissing(value) ? AMOUNT_MASK : formatQuantity(value)),
    }),
    [hidden],
  );
}

/** Currency amount cell, masked while amounts are hidden; `colored` tints it by sign. */
export function Amount({
  value,
  currency,
  digits = 0,
  colored = false,
}: {
  value: number | null | undefined;
  currency?: string;
  digits?: number;
  colored?: boolean;
}) {
  const { amount } = useAmounts();
  return (
    <Box component="span" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums", color: colored ? signColor(value) : undefined }}>
      {amount(value, digits)}
      {currency && !isMissing(value) ? ` ${currency}` : ""}
    </Box>
  );
}

/** Share quantity cell (up to four decimals), masked while amounts are hidden. */
export function Quantity({ value }: { value: number | null | undefined }) {
  const { quantity } = useAmounts();
  return (
    <Box component="span" sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}>
      {quantity(value)}
    </Box>
  );
}

/** Base-currency amount on top, local-currency amount in grey below; both masked while amounts are hidden. */
export function DualMoney({
  base,
  baseCurrency,
  local,
  localCurrency,
  digits = 0,
}: {
  base: number | null | undefined;
  baseCurrency: string;
  local?: number | null;
  localCurrency?: string;
  digits?: number;
}) {
  const { amount } = useAmounts();
  const showLocal = local !== undefined && local !== null && localCurrency && localCurrency !== baseCurrency;
  return (
    <Box sx={{ whiteSpace: "nowrap", textAlign: "right" }}>
      <div>
        {amount(base, digits)} {baseCurrency}
      </div>
      {showLocal ? (
        <Typography component="div" variant="caption" sx={{ color: "text.secondary" }}>
          {amount(local, digits)} {localCurrency}
        </Typography>
      ) : null}
    </Box>
  );
}

/** A price or other public figure with a currency code. Never masked; use `Amount` for holdings. */
export function Money({ value, currency, digits = 0 }: { value: number | null | undefined; currency?: string; digits?: number }) {
  return (
    <Box component="span" sx={{ whiteSpace: "nowrap" }}>
      {formatNumber(value, digits)}
      {currency && !isMissing(value) ? ` ${currency}` : ""}
    </Box>
  );
}

export function Pct({ value, colored = true }: { value: number | null | undefined; colored?: boolean }) {
  return (
    <Box component="span" sx={{ color: colored ? signColor(value) : undefined, fontVariantNumeric: "tabular-nums" }}>
      {formatPct(value)}
    </Box>
  );
}

export function SecurityCell({ name, fullTicker }: { name: string; fullTicker: string }) {
  return (
    <Box sx={{ minWidth: 160 }}>
      <div>{name}</div>
      <Typography component="div" variant="caption" sx={{ color: "text.secondary" }}>
        {fullTicker}
      </Typography>
    </Box>
  );
}

export function PositionTypeCell({ type }: { type: "long" | "short" }) {
  const Icon = type === "long" ? TrendingUpIcon : TrendingDownIcon;
  return (
    <Tooltip title={type === "long" ? "Long" : "Short"}>
      <Icon sx={{ fontSize: 18, color: "text.secondary", display: "block", mx: "auto" }} />
    </Tooltip>
  );
}
