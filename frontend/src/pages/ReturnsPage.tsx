import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchPortfolioDays, fetchPortfolios, rebuildPnl, type PortfolioCard, type PortfolioDay, type SeriesSummary } from "../api/client";
import AppShell, { BREADCRUMB_HEIGHT, TOP_BAR_HEIGHT } from "../app/AppShell";
import { useLiveFilters } from "../app/useLiveFilters";
import TimeSeriesChart from "../charts/TimeSeriesChart";
import { NEGATIVE_COLOR } from "../charts/theme";
import { Amount, Pct, useAmounts } from "../components/cells";
import DataTable, { sortRows, useTableParams, type Column } from "../components/DataTable";
import { formatNumber, toNumber, withCurrency } from "../components/format";
type Row = PortfolioDay & {
  nav_n: number;
  cash_additions_n: number;
  returns_n: number;
  positions_n: number;
  cash_n: number;
  flow_n: number;
  pnl_n: number;
  units_n: number;
  unit_price_n: number;
  daily_return_n: number | null;
  cumulative_n: number;
  drawdown_n: number;
  broker_n: number | null;
  difference_n: number | null;
};

// Amount headers name the portfolio's base currency; the Total view is in the reporting currency.
const columnsFor = (currency: string): Column<Row>[] => [
  { key: "date", header: "Date", sortKey: "day", noWrap: true, render: (row) => row.day },
  { key: "portfolio", header: "Portfolio", render: (row) => row.portfolio_name },
  { key: "nav", header: withCurrency("NAV", currency), align: "right", sortKey: "nav_n", render: (row) => <Amount value={row.nav_n} /> },
  { key: "cash_additions", header: withCurrency("Cumulative cash additions", currency), align: "right", sortKey: "cash_additions_n", render: (row) => <Amount value={row.cash_additions_n} /> },
  { key: "positions", header: withCurrency("Positions", currency), align: "right", sortKey: "positions_n", render: (row) => <Amount value={row.positions_n} /> },
  { key: "cash", header: withCurrency("Cash", currency), align: "right", sortKey: "cash_n", render: (row) => <Amount value={row.cash_n} /> },
  { key: "flow", header: withCurrency("Flow", currency), align: "right", sortKey: "flow_n", render: (row) => <Amount value={row.flow_n} /> },
  { key: "pnl", header: withCurrency("Daily PnL", currency), align: "right", sortKey: "pnl_n", render: (row) => <Amount value={row.pnl_n} /> },
  { key: "units", header: "Units", align: "right", render: (row) => <Amount value={row.units_n} digits={2} /> },
  { key: "unit_price", header: "Unit price", align: "right", sortKey: "unit_price_n", render: (row) => formatNumber(row.unit_price_n, 4) },
  { key: "daily_return", header: "Daily return %", align: "right", sortKey: "daily_return_n", render: (row) => <Pct value={row.daily_return_n} /> },
  { key: "cum", header: "Since reporting start %", align: "right", render: (row) => <Pct value={row.cumulative_n} /> },
  { key: "dd", header: "Drawdown %", align: "right", render: (row) => <Pct value={row.drawdown_n} colored={false} /> },
  { key: "returns", header: withCurrency("Returns", currency), align: "right", sortKey: "returns_n", render: (row) => <Amount value={row.returns_n} colored /> },
  { key: "broker", header: withCurrency("Broker value", currency), align: "right", render: (row) => <Amount value={row.broker_n} /> },
  { key: "difference", header: withCurrency("Difference", currency), align: "right", sortKey: "difference_n", render: (row) => <Amount value={row.difference_n} /> },
];

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <Box sx={{ minWidth: 120 }}>
      <Typography variant="caption" color="text.secondary" component="div">
        {label}
      </Typography>
      <Typography variant="body1" component="div" sx={{ fontVariantNumeric: "tabular-nums" }}>
        {children}
      </Typography>
    </Box>
  );
}

function SummaryRow({ summary, currency }: { summary: SeriesSummary; currency: string }) {
  const { money } = useAmounts();
  return (
    <Stack direction="row" spacing={3} sx={{ flexWrap: "wrap", rowGap: 1, mb: 1.5 }}>
      <Stat label="NAV">{money(toNumber(summary.nav), currency)}</Stat>
      <Stat label="Unit price">{formatNumber(toNumber(summary.unit_price), 4)}</Stat>
      <Stat label="Since reporting start">
        <Pct value={toNumber(summary.cumulative_return_pct)} />
      </Stat>
      <Stat label="Period return">
        <Pct value={toNumber(summary.period_return_pct)} />
      </Stat>
      <Stat label="Annualized">
        <Pct value={toNumber(summary.annualized_return_pct)} />
      </Stat>
      <Stat label="Max drawdown">
        <Pct value={toNumber(summary.max_drawdown_pct)} colored={false} />
      </Stat>
      <Stat label="Last day">{summary.last_day ?? "-"}</Stat>
    </Stack>
  );
}

type Filters = { date_gte: string; date_lte: string };

/** Bottom padding of the page content in `AppShell`, in pixels. */
const CONTENT_BOTTOM_PADDING = 16;
/** Below this the table stops shrinking and the page scrolls instead, so short viewports still get usable rows. */
const TABLE_MIN_HEIGHT = 280;

export default function ReturnsPage() {
  const [params, setParams] = useSearchParams();
  const portfolioId = Number(params.get("portfolio") ?? "0") || 0;
  const applied = useMemo<Filters>(() => ({ date_gte: params.get("date_gte") ?? "", date_lte: params.get("date_lte") ?? "" }), [params]);
  const table = useTableParams("day");

  const [days, setDays] = useState<PortfolioDay[] | null>(null);
  const [summary, setSummary] = useState<SeriesSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [portfolios, setPortfolios] = useState<PortfolioCard[]>([]);
  const [rebuilding, setRebuilding] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  function apply(next: Filters) {
    const merged = new URLSearchParams(params);
    for (const key of ["date_gte", "date_lte"] as const) {
      if (next[key]) merged.set(key, next[key]);
      else merged.delete(key);
    }
    merged.set("page", "1");
    setParams(merged);
  }
  const filters = useLiveFilters(applied, apply);

  useEffect(() => {
    let cancelled = false;
    fetchPortfolios()
      .then((payload) => {
        if (!cancelled) setPortfolios(payload.data);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    let cancelled = false;
    setDays(null);
    setError(null);
    fetchPortfolioDays(portfolioId || null, { date_gte: applied.date_gte || undefined, date_lte: applied.date_lte || undefined })
      .then((payload) => {
        if (cancelled) return;
        setDays(payload.data);
        setSummary(payload.summary);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [portfolioId, applied.date_gte, applied.date_lte, reloadKey]);

  const rebuild = useCallback(() => {
    setRebuilding(true);
    setError(null);
    rebuildPnl()
      .then(() => setReloadKey((key) => key + 1))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : String(reason)))
      .finally(() => setRebuilding(false));
  }, []);

  const rows = useMemo<Row[]>(
    () =>
      (days ?? []).map((day) => {
        const nav = Number(day.nav);
        const broker = toNumber(day.broker_value);
        return {
          ...day,
          nav_n: nav,
          cash_additions_n: Number(day.cumulative_cash_additions),
          returns_n: Number(day.returns_base),
          positions_n: Number(day.positions_value),
          cash_n: Number(day.cash_value),
          flow_n: Number(day.flow),
          pnl_n: Number(day.daily_pnl),
          units_n: Number(day.units),
          unit_price_n: Number(day.unit_price),
          daily_return_n: toNumber(day.daily_return_pct),
          cumulative_n: Number(day.cumulative_return_pct),
          drawdown_n: Number(day.drawdown_pct),
          broker_n: broker,
          difference_n: broker === null ? null : nav - broker,
        };
      }),
    [days],
  );
  const currency = rows[0]?.base_currency ?? "";
  const columns = useMemo(() => columnsFor(currency), [currency]);
  const sorted = useMemo(() => sortRows(rows, table.sort), [rows, table.sort]);
  const pageRows = sorted.slice((table.page - 1) * table.perPage, table.page * table.perPage);
  const unitPricePoints = useMemo(() => rows.map((row) => ({ date: row.day, value: row.unit_price_n })), [rows]);
  const drawdownPoints = useMemo(() => rows.map((row) => ({ date: row.day, value: row.drawdown_n * 100 })), [rows]);

  return (
    <AppShell title="Returns">
      <Stack spacing={1.5} sx={{ height: `calc(100vh - ${TOP_BAR_HEIGHT + BREADCRUMB_HEIGHT + CONTENT_BOTTOM_PADDING}px)`, minHeight: 0 }}>
        {error ? <Alert severity="error">{error}</Alert> : null}
        {days === null || rebuilding ? <LinearProgress /> : <Box sx={{ height: 4 }} />}
        <Paper variant="outlined" sx={{ p: 1.5, flexShrink: 0 }}>
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", rowGap: 1, mb: 1 }}>
            <Typography variant="h3" component="div">
              Unit price
            </Typography>
            <Stack direction="row" spacing={1} sx={{ alignItems: "center", flexWrap: "wrap", rowGap: 1 }}>
              <TextField size="small" label="From" placeholder="YYYY-MM-DD" value={filters.draft.date_gte} onChange={(event) => filters.set({ date_gte: event.target.value })} sx={{ width: 140 }} />
              <TextField size="small" label="To" placeholder="YYYY-MM-DD" value={filters.draft.date_lte} onChange={(event) => filters.set({ date_lte: event.target.value })} sx={{ width: 140 }} />
              <Select
                size="small"
                value={String(portfolioId)}
                onChange={(event) => {
                  const merged = new URLSearchParams(params);
                  merged.set("portfolio", String(event.target.value));
                  merged.set("page", "1");
                  setParams(merged);
                }}
                sx={{ minWidth: 160 }}
              >
                <MenuItem value="0">Total</MenuItem>
                {portfolios.map((portfolio) => (
                  <MenuItem key={portfolio.id} value={String(portfolio.id)}>
                    {portfolio.name}
                  </MenuItem>
                ))}
              </Select>
              <Button variant="outlined" size="small" onClick={rebuild} disabled={rebuilding}>
                {rebuilding ? "Rebuilding…" : "Rebuild"}
              </Button>
            </Stack>
          </Stack>
          <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>
            {portfolioId
              ? (portfolios.find((p) => p.id === portfolioId)?.reporting_start_date
                ? `Reporting since ${portfolios.find((p) => p.id === portfolioId)?.reporting_start_date}` : "Reporting: full history")
              : "Each portfolio contributes from its reporting start date. Opening capital is treated as a contribution."}
          </Typography>
          {summary ? <SummaryRow summary={summary} currency={currency} /> : null}
          <TimeSeriesChart series={[{ name: "Unit price", points: unitPricePoints }]} height={240} decimals={2} baseline={100} />
          <Typography variant="h3" component="div" sx={{ mt: 1.5, mb: 1 }}>
            Drawdown
          </Typography>
          <TimeSeriesChart
            series={[{ name: "Drawdown", points: drawdownPoints, type: "area", color: NEGATIVE_COLOR }]}
            height={200}
            decimals={1}
            suffix=" %"
            baseline={0}
            drawdown
          />
        </Paper>
        <Box sx={{ flex: 1, minHeight: TABLE_MIN_HEIGHT, display: "flex", flexDirection: "column" }}>
          <Typography variant="caption" color="text.secondary" sx={{ mb: 0.5 }}>
            Cumulative cash additions are lifetime deposits minus withdrawals through each date, including before the reporting start and date filters. Returns = NAV − cumulative cash additions.
          </Typography>
          <DataTable
            columns={columns}
            rows={pageRows}
            total={sorted.length}
            rowKey={(row) => `${row.portfolio_id}:${row.day}`}
            page={table.page}
            perPage={table.perPage}
            sort={table.sort}
            onPageChange={table.setPage}
            onPerPageChange={table.setPerPage}
            onSortChange={table.setSort}
            fill
          />
        </Box>
      </Stack>
    </AppShell>
  );
}
