import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useParams } from "react-router-dom";
import { fetchPositionDetail, type PositionDetail, type PositionTrade, type ReturnsBlock } from "../api/client";
import AppShell from "../app/AppShell";
import { MarketValueChart, PriceTradesChart, type TradeMark } from "../charts/PositionCharts";
import { Pct, useAmounts } from "../components/cells";
import { formatNumber, signColor, toNumber } from "../components/format";
import SplitView from "../components/SplitView";
function formatDate(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric", timeZone: "UTC" });
}

function StatRow({ label, value, color }: { label: string; value: ReactNode; color?: string }) {
  return (
    <Stack direction="row" sx={{ justifyContent: "space-between", gap: 2, py: 0.25 }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" component="div" sx={{ fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap", color }}>
        {value}
      </Typography>
    </Stack>
  );
}

function StatGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        {title}
      </Typography>
      {children}
    </Box>
  );
}

function ReturnsStats({ block }: { block: ReturnsBlock }) {
  const amounts = useAmounts();
  const money = (value: string | null | undefined) => amounts.money(toNumber(value), block.currency, 2);
  const ret = toNumber(block.return_amount);
  return (
    <StatGroup title={`Returns in ${block.currency}`}>
      <StatRow label="Opening value" value={money(block.opening_value)} />
      <StatRow label="Total cost" value={money(block.total_cost)} />
      <StatRow label="Total revenue" value={money(block.total_revenue)} />
      <StatRow label="Value current position" value={block.value === null ? "no broker mark" : money(block.value)} />
      <StatRow label="Dividends" value={money(block.dividends)} />
      <StatRow label="Costs" value={money(block.costs)} />
      <StatRow label="Return" value={money(block.return_amount)} color={signColor(ret)} />
      <StatRow label="ROI %" value={<Pct value={toNumber(block.roi_pct)} />} />
      <StatRow label="Annualized days %" value={<Pct value={toNumber(block.annualized_days_pct)} />} />
      <StatRow label="Annualized months %" value={<Pct value={toNumber(block.annualized_months_pct)} />} />
    </StatGroup>
  );
}

function tradeText(trade: PositionTrade, formatQuantity: (value: number) => string) {
  const quantity = formatQuantity(Math.abs(toNumber(trade.quantity) ?? 0));
  if (trade.kind === "corporate_action") {
    const sign = (toNumber(trade.quantity) ?? 0) >= 0 ? "+" : "-";
    return `Corporate action: ${sign}${quantity} shares`;
  }
  const price = trade.price === null ? "" : ` at ${formatNumber(toNumber(trade.price), 2)} ${trade.currency}`;
  return `${trade.kind === "buy" ? "Bought" : "Sold"} ${quantity} shares${price}`;
}

function Timeline({ trades, baseCurrency }: { trades: PositionTrade[]; baseCurrency: string }) {
  const { amount, quantity } = useAmounts();
  const newestFirst = useMemo(() => [...trades].reverse(), [trades]);
  return (
    <StatGroup title="Timeline">
      <Box>
        {newestFirst.map((trade, index) => (
          <Stack key={`${trade.trade_date}:${index}`} direction="row" sx={{ gap: 1.5, position: "relative", pb: 1.5 }}>
            <Typography variant="caption" color="text.secondary" sx={{ width: 84, flexShrink: 0, textAlign: "right", pt: 0.25, whiteSpace: "nowrap" }}>
              {formatDate(trade.trade_date)}
            </Typography>
            <Box sx={{ position: "relative", width: 12, flexShrink: 0 }}>
              <Box
                sx={{
                  width: 10,
                  height: 10,
                  borderRadius: "50%",
                  mt: 0.5,
                  bgcolor: trade.kind === "buy" ? "success.main" : trade.kind === "sell" ? "error.main" : "text.disabled",
                }}
              />
              {index < newestFirst.length - 1 ? (
                <Box sx={{ position: "absolute", left: 4, top: 16, bottom: -12, width: 2, bgcolor: "divider" }} />
              ) : null}
            </Box>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="body2">{tradeText(trade, quantity)}</Typography>
              {trade.kind !== "corporate_action" ? (
                <Typography variant="caption" color="text.secondary" component="div">
                  {amount(Math.abs(toNumber(trade.amount_local) ?? 0), 2)} {trade.currency} · {amount(Math.abs(toNumber(trade.amount_base) ?? 0), 2)} {baseCurrency}
                </Typography>
              ) : null}
            </Box>
          </Stack>
        ))}
        {newestFirst.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No trades.
          </Typography>
        ) : null}
      </Box>
    </StatGroup>
  );
}

/** Price chart range: the holding itself, or one or five years of price context back from today. */
type Range = "lifetime" | "1y" | "5y";
const rangeYears: Record<Exclude<Range, "lifetime">, number> = { "1y": 1, "5y": 5 };

function yearsBefore(day: string, years: number) {
  const result = new Date(`${day}T00:00:00Z`);
  result.setUTCFullYear(result.getUTCFullYear() - years);
  return result.toISOString().slice(0, 10);
}

export default function PositionDetailPage() {
  const { positionId } = useParams();
  const [detail, setDetail] = useState<PositionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [range, setRange] = useState<Range>("lifetime");
  const { money, quantity } = useAmounts();

  useEffect(() => {
    const id = Number(positionId);
    if (!id) {
      setError("Invalid position address.");
      return;
    }
    let cancelled = false;
    setDetail(null);
    setError(null);
    fetchPositionDetail(id)
      .then((payload) => {
        if (!cancelled) setDetail(payload);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [positionId]);

  const series = useMemo(() => detail?.series ?? [], [detail]);
  const history = useMemo(() => detail?.price_history ?? [], [detail]);
  // "Reporting period" shows the holding itself; 1Y and 5Y show price context back from the latest close.
  const window = useMemo(() => {
    if (range === "lifetime") return { from: series[0]?.date ?? "", to: series[series.length - 1]?.date ?? "" };
    const last = history[history.length - 1]?.date ?? "";
    return { from: last ? yearsBefore(last, rangeYears[range]) : "", to: last };
  }, [range, series, history]);
  const prices = useMemo(
    () => history.filter((point) => point.date >= window.from && point.date <= window.to).map((point) => ({ date: point.date, close: Number(point.close) })),
    [history, window],
  );
  const values = useMemo(
    () => series.map((point) => ({ date: point.date, value: Number(point.market_value), quantity: Number(point.quantity) })),
    [series],
  );
  const marks = useMemo<TradeMark[]>(
    () =>
      (detail?.trades ?? [])
        .filter((trade) => trade.kind !== "corporate_action" && trade.adjusted_price !== null && trade.trade_date >= window.from && trade.trade_date <= window.to)
        .map((trade) => ({ date: trade.trade_date, price: Number(trade.adjusted_price), quantity: Number(trade.quantity), kind: trade.kind as "buy" | "sell" })),
    [detail, window],
  );

  const title = detail ? (detail.security_name ?? detail.full_ticker) : "Position";
  const currency = detail?.currency ?? detail?.base_currency ?? "";

  return (
    <AppShell title={title} parent={{ label: "Positions", path: "/investments/positions" }}>
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {detail === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "baseline", flexWrap: "wrap", mb: 1, minHeight: 32 }}>
        <Typography variant="h2" component="h1" sx={{ flexShrink: 0 }}>
          {title}
        </Typography>
        {detail ? (
          <>
            <Typography variant="body1" color="text.secondary">
              {detail.full_ticker} · {detail.portfolio_name}
            </Typography>
            <Chip size="small" variant="outlined" color={detail.status === "open" ? "success" : "default"} label={detail.status === "open" ? "Open" : `Closed ${detail.closed ? formatDate(detail.closed) : ""}`} />
            {detail.notes.map((note) => (
              <Chip key={note} size="small" variant="outlined" color="warning" label={note} />
            ))}
          </>
        ) : null}
      </Stack>
      {detail ? (
        <SplitView
          rightWidth={360}
          offsetTop={52}
          left={
            <Stack spacing={1.5} sx={{ flex: 1, minHeight: 0, overflowY: "auto", pr: 0.5 }}>
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Stack direction="row" sx={{ alignItems: "center", justifyContent: "space-between", mb: 0.5 }}>
                  <Typography variant="subtitle2">Price in {currency}</Typography>
                  <ToggleButtonGroup exclusive size="small" value={range} onChange={(_event, value: Range | null) => value && setRange(value)}>
                    <ToggleButton value="lifetime">Reporting period</ToggleButton>
                    <ToggleButton value="1y">1Y</ToggleButton>
                    <ToggleButton value="5y">5Y</ToggleButton>
                  </ToggleButtonGroup>
                </Stack>
                <PriceTradesChart prices={prices} trades={marks} currency={currency} height={300} />
              </Paper>
              <Paper variant="outlined" sx={{ p: 1.5 }}>
                <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
                  Market value in {currency} and shares held
                </Typography>
                <MarketValueChart points={values} currency={currency} height={300} />
              </Paper>
            </Stack>
          }
          right={
            <Paper variant="outlined" sx={{ flex: 1, minHeight: 0, overflowY: "auto", p: 1.5 }}>
              <StatGroup title="Share stats">
                <StatRow label="Total buys" value={formatNumber(detail.shares.buys)} />
                <StatRow label="Shares bought" value={quantity(toNumber(detail.shares.shares_bought))} />
                <StatRow label="Total sells" value={formatNumber(detail.shares.sells)} />
                <StatRow label="Shares sold" value={quantity(toNumber(detail.shares.shares_sold))} />
                <StatRow label="Current shares" value={quantity(toNumber(detail.shares.current))} />
                <StatRow label="Held" value={`${formatDate(detail.opened)} - ${detail.closed ? formatDate(detail.closed) : "today"}`} />
              </StatGroup>
              {detail.reporting_start_date ? (
                <StatGroup title={`Reporting since ${detail.reporting_start_date}`}>
                  <StatRow label="Original purchase cost" value={money(toNumber(detail.original_cost_local), currency, 2)} />
                </StatGroup>
              ) : null}
              <ReturnsStats block={detail.returns_local} />
              {detail.returns_base.currency !== detail.returns_local.currency ? <ReturnsStats block={detail.returns_base} /> : null}
              <Timeline trades={detail.trades} baseCurrency={detail.base_currency} />
            </Paper>
          }
        />
      ) : null}
    </AppShell>
  );
}
