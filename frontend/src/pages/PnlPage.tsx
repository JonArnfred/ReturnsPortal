import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchPnlRows, fetchPortfolios, type PnlRow, type PortfolioCard } from "../api/client";
import AppShell from "../app/AppShell";
import { useFilterDefaults } from "../app/useFilterDefaults";
import { useLiveFilters } from "../app/useLiveFilters";
import { useServerTable } from "../app/useServerTable";
import { DualMoney, Money, Pct, PositionTypeCell, Quantity, SecurityCell } from "../components/cells";
import DataTable, { useTableParams, type Column } from "../components/DataTable";
import FilterPanel, { FilterField } from "../components/FilterPanel";
import { formatNumber, toNumber } from "../components/format";
const dual = (row: PnlRow, base: string | null, local: string | null) => (
  <DualMoney base={toNumber(base)} baseCurrency={row.base_currency} local={toNumber(local)} localCurrency={row.currency} />
);

const columns: Column<PnlRow>[] = [
  { key: "day", header: "Date", sortKey: "day", noWrap: true, render: (row) => row.day },
  { key: "portfolio", header: "Portfolio", sortKey: "portfolio_name", render: (row) => row.portfolio_name },
  { key: "security", header: "Security", sortKey: "security_name", render: (row) => <SecurityCell name={row.security_name ?? "-"} fullTicker={row.full_ticker ?? ""} /> },
  { key: "type", header: "Type", align: "center", render: (row) => <PositionTypeCell type={row.position_type === "short" ? "short" : "long"} /> },
  { key: "quantity", header: "Shares held", align: "right", sortKey: "quantity", render: (row) => <Quantity value={toNumber(row.quantity)} /> },
  { key: "price", header: "Price", align: "right", render: (row) => <Money value={toNumber(row.price)} currency={row.currency} digits={3} /> },
  { key: "price_change", header: "Price change", align: "right", render: (row) => <Money value={toNumber(row.price_change)} currency={row.currency} digits={3} /> },
  { key: "fx", header: "FX rate", align: "right", render: (row) => formatNumber(toNumber(row.fx), 4) },
  { key: "fx_change", header: "FX change", align: "right", render: (row) => formatNumber(toNumber(row.fx_change), 4) },
  { key: "mv", header: "Market value", align: "right", sortKey: "market_value_base", render: (row) => dual(row, row.market_value_base, row.market_value_local) },
  { key: "price_effect", header: "Price effect", align: "right", sortKey: "price_effect_base", render: (row) => dual(row, row.price_effect_base, row.price_effect_local) },
  { key: "trades", header: "Trades", align: "right", sortKey: "trade_flow_base", render: (row) => dual(row, row.trade_flow_base, row.trade_flow_local) },
  { key: "fx_effect", header: "FX effect", align: "right", sortKey: "fx_effect_base", render: (row) => dual(row, row.fx_effect_base, null) },
  { key: "interaction", header: "Interaction", align: "right", sortKey: "interaction_effect_base", render: (row) => dual(row, row.interaction_effect_base, null) },
  { key: "dividend", header: "Dividend effect", align: "right", sortKey: "dividend_effect_base", render: (row) => dual(row, row.dividend_effect_base, row.dividend_effect_local) },
  { key: "interest", header: "Interest", align: "right", sortKey: "interest_effect_base", render: (row) => dual(row, row.interest_effect_base, null) },
  { key: "costs", header: "Costs", align: "right", sortKey: "cost_effect_base", render: (row) => dual(row, row.cost_effect_base, row.cost_effect_local) },
  { key: "daily_pnl", header: "Daily PnL", align: "right", sortKey: "daily_pnl_base", render: (row) => dual(row, row.daily_pnl_base, row.daily_pnl_local) },
  { key: "daily_return", header: "Daily return %", align: "right", sortKey: "daily_return_pct", render: (row) => <Pct value={toNumber(row.daily_return_pct)} /> },
  {
    key: "daily_return_ccy",
    header: "Daily return constant currencies %",
    align: "right",
    sortKey: "constant_currency_return_pct",
    render: (row) => <Pct value={toNumber(row.constant_currency_return_pct)} />,
  },
  { key: "total_pnl", header: "Total PnL", align: "right", sortKey: "total_pnl_base", render: (row) => dual(row, row.total_pnl_base, row.total_pnl_local) },
];

/** URL parameter names double as the API query names, so useServerTable can forward them untouched. */
type Filters = { portfolio_id: string; position_type: string; position_kind: string; date_gte: string; date_lte: string; search: string };
const emptyFilters: Filters = { portfolio_id: "", position_type: "", position_kind: "", date_gte: "", date_lte: "", search: "" };
const filterKeys: (keyof Filters)[] = ["portfolio_id", "position_type", "position_kind", "date_gte", "date_lte", "search"];
const fixed: Record<string, string> = {};

export default function PnlPage() {
  const [params, setParams] = useSearchParams();
  const filterDefaults = useFilterDefaults("pnl", emptyFilters);
  const applied = useMemo<Filters>(() => Object.fromEntries(filterKeys.map((key) => [key, params.get(key) ?? ""])) as Filters, [params]);
  const filters = useLiveFilters(applied, applyFilters);
  const table = useTableParams("day");
  const { rows, meta, loading, error } = useServerTable(fetchPnlRows, fixed, { per_page: "100", order_by: "day", order: "desc" });

  const [portfolios, setPortfolios] = useState<PortfolioCard[]>([]);
  useEffect(() => {
    let cancelled = false;
    fetchPortfolios()
      .then((payload) => {
        if (!cancelled) setPortfolios(payload.data);
      })
      .catch(() => undefined); // the dropdown simply stays empty
    return () => {
      cancelled = true;
    };
  }, []);

  function applyFilters(next: Filters) {
    const merged = new URLSearchParams(params);
    for (const key of filterKeys) {
      if (next[key]) merged.set(key, next[key]);
      else merged.delete(key);
    }
    merged.set("page", "1");
    setParams(merged);
  }

  return (
    <AppShell title="PnL">
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start" }}>
        <FilterPanel
          onReset={() => applyFilters(filterDefaults.defaults)}
          onSaveDefault={() => {
            filters.flush();
            void filterDefaults.save(filters.draft);
          }}
          savedDefault={{ exists: filterDefaults.saved !== null, busy: filterDefaults.busy, error: filterDefaults.error, onClear: () => void filterDefaults.clear() }}
        >
          <FilterField label="Period">
            <Stack spacing={1}>
              <TextField fullWidth label="From" placeholder="YYYY-MM-DD" value={filters.draft.date_gte} onChange={(event) => filters.set({ date_gte: event.target.value })} />
              <TextField fullWidth label="To" placeholder="YYYY-MM-DD" value={filters.draft.date_lte} onChange={(event) => filters.set({ date_lte: event.target.value })} />
            </Stack>
          </FilterField>
          <FilterField label="Portfolio">
            <Select fullWidth displayEmpty value={filters.draft.portfolio_id} onChange={(event) => filters.setNow({ portfolio_id: String(event.target.value) })}>
              <MenuItem value="">All portfolios</MenuItem>
              {portfolios.map((portfolio) => (
                <MenuItem key={portfolio.id} value={String(portfolio.id)}>
                  {portfolio.name}
                </MenuItem>
              ))}
            </Select>
          </FilterField>
          <FilterField label="Position type">
            <ToggleButtonGroup exclusive fullWidth size="small" value={filters.draft.position_type || "all"} onChange={(_event, value: string | null) => value && filters.setNow({ position_type: value === "all" ? "" : value })}>
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="long">Long</ToggleButton>
              <ToggleButton value="short">Short</ToggleButton>
            </ToggleButtonGroup>
          </FilterField>
          <FilterField label="Kind">
            <ToggleButtonGroup exclusive fullWidth size="small" value={filters.draft.position_kind || "all"} onChange={(_event, value: string | null) => value && filters.setNow({ position_kind: value === "all" ? "" : value })}>
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="security">Securities</ToggleButton>
              <ToggleButton value="cash">Cash</ToggleButton>
            </ToggleButtonGroup>
          </FilterField>
          <FilterField label="Position">
            <TextField fullWidth placeholder="Type to find ..." value={filters.draft.search} onChange={(event) => filters.set({ search: event.target.value })} />
          </FilterField>
        </FilterPanel>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
          {loading ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            {meta ? `${meta.total} position days` : ""}
          </Typography>
          <DataTable
            columns={columns}
            rows={rows}
            total={meta?.total ?? 0}
            rowKey={(row) => `${row.portfolio_id}:${row.position_key}:${row.day}`}
            page={table.page}
            perPage={table.perPage}
            sort={table.sort}
            onPageChange={table.setPage}
            onPerPageChange={table.setPerPage}
            onSortChange={table.setSort}
            offsetTop={190}
          />
        </Box>
      </Stack>
    </AppShell>
  );
}
