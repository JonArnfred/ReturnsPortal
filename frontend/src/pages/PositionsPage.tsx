import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutlined";
import RemoveCircleOutlineIcon from "@mui/icons-material/RemoveCircleOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { fetchPositions, type PositionRow } from "../api/client";
import AppShell from "../app/AppShell";
import { useFilterDefaults } from "../app/useFilterDefaults";
import { useLiveFilters } from "../app/useLiveFilters";
import { Amount, Money, Pct, PositionTypeCell, Quantity, SecurityCell, useAmounts } from "../components/cells";
import DataTable, { sortRows, useTableParams, type Column } from "../components/DataTable";
import FilterPanel, { FilterField } from "../components/FilterPanel";
import { toNumber, withCurrency } from "../components/format";
import TableSearch from "../components/TableSearch";

type Row = PositionRow & {
  quantity_n: number;
  value_n: number;
  dividends_n: number;
  return_n: number | null;
  roi_n: number | null;
  ann_days_n: number | null;
  ann_months_n: number | null;
  pct_aum_n: number | null;
  pct_portfolio_n: number | null;
  period: string;
};
function formatDate(value: string) {
  return new Date(`${value}T00:00:00Z`).toLocaleDateString("en-US", { month: "long", day: "2-digit", year: "numeric", timeZone: "UTC" });
}

/** Columns; amounts in the portfolios' reporting currency, named in the headers. */
const positionColumns = (currency: string): Column<Row>[] => [
  { key: "portfolio", header: "Portfolio", sortKey: "portfolio_name", render: (row) => <Chip size="small" variant="outlined" label={row.portfolio_name} /> },
  { key: "security", header: "Security", sortKey: "security_name", render: (row) => <SecurityCell name={row.security_name ?? "-"} fullTicker={row.full_ticker} /> },
  { key: "quantity", header: "Quantity", align: "right", sortKey: "quantity_n", render: (row) => <Quantity value={row.quantity_n} /> },
  { key: "period", header: "Period", sortKey: "opened", render: (row) => row.period },
  { key: "type", header: "Position type", align: "center", render: (row) => <PositionTypeCell type={row.position_type as "long" | "short"} /> },
  {
    key: "status",
    header: "Status",
    align: "center",
    sortKey: "status",
    render: (row) => (
      <Tooltip title={row.status === "open" ? "Open" : "Closed"}>
        {row.status === "open" ? (
          <CheckCircleOutlineIcon sx={{ fontSize: 18, color: "success.main", display: "block", mx: "auto" }} />
        ) : (
          <RemoveCircleOutlineIcon sx={{ fontSize: 18, color: "text.disabled", display: "block", mx: "auto" }} />
        )}
      </Tooltip>
    ),
  },
  { key: "price", header: "Current price", align: "right", render: (row) => <Money value={toNumber(row.current_price)} currency={row.currency ?? undefined} digits={2} /> },
  { key: "avg_buy", header: "Lifetime avg buy price", align: "right", render: (row) => <Money value={toNumber(row.avg_buy_price)} currency={row.currency ?? undefined} digits={2} /> },
  { key: "avg_sell", header: "Lifetime avg sell price", align: "right", render: (row) => <Money value={toNumber(row.avg_sell_price)} currency={row.currency ?? undefined} digits={2} /> },
  { key: "value", header: withCurrency("Value", currency), align: "right", sortKey: "value_n", render: (row) => <Amount value={row.value_n} digits={2} /> },
  { key: "pct_aum", header: "% AUM", align: "right", sortKey: "pct_aum_n", render: (row) => <Pct value={row.pct_aum_n} colored={false} /> },
  { key: "pct_portfolio", header: "% Portfolio", align: "right", sortKey: "pct_portfolio_n", render: (row) => <Pct value={row.pct_portfolio_n} colored={false} /> },
  { key: "dividends", header: withCurrency("Dividends", currency), align: "right", sortKey: "dividends_n", render: (row) => <Amount value={row.dividends_n} digits={2} /> },
  { key: "return", header: withCurrency("Return", currency), align: "right", sortKey: "return_n", render: (row) => <Amount value={row.return_n} digits={2} colored /> },
  { key: "roi", header: "ROI %", align: "right", sortKey: "roi_n", render: (row) => <Pct value={row.roi_n} /> },
  { key: "ann_days", header: "Annualized days %", align: "right", sortKey: "ann_days_n", render: (row) => <Pct value={row.ann_days_n} /> },
  { key: "ann_months", header: "Annualized months %", align: "right", sortKey: "ann_months_n", render: (row) => <Pct value={row.ann_months_n} /> },
];

type Filters = { portfolio: string; type: string; status: string; search: string };
const builtin: Filters = { portfolio: "", type: "all", status: "open", search: "" };

export default function PositionsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const filterDefaults = useFilterDefaults("positions", builtin);
  const applied = useMemo<Filters>(
    () => ({
      portfolio: params.get("portfolio") ?? "",
      type: params.get("type") ?? "all",
      status: params.get("status") ?? "open",
      search: params.get("search") ?? "",
    }),
    [params],
  );
  const filters = useLiveFilters(applied, apply);
  const [positions, setPositions] = useState<PositionRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const table = useTableParams("value_n");
  const { amount } = useAmounts();

  useEffect(() => {
    let cancelled = false;
    fetchPositions()
      .then((payload) => {
        if (!cancelled) setPositions(payload.data);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo<Row[]>(
    () =>
      (positions ?? []).map((row) => ({
        ...row,
        quantity_n: toNumber(row.quantity) ?? 0,
        value_n: toNumber(row.value_base) ?? 0,
        dividends_n: toNumber(row.dividends_base) ?? 0,
        return_n: toNumber(row.return_base),
        roi_n: toNumber(row.roi_pct),
        ann_days_n: toNumber(row.annualized_days_pct),
        ann_months_n: toNumber(row.annualized_months_pct),
        pct_aum_n: toNumber(row.pct_aum),
        pct_portfolio_n: toNumber(row.pct_portfolio),
        period: `${formatDate(row.opened)} - ${row.closed ? formatDate(row.closed) : ""}`,
      })),
    [positions],
  );
  const currency = rows[0]?.base_currency ?? "";
  const columns = useMemo(() => positionColumns(currency), [currency]);
  const portfolios = useMemo(() => [...new Map(rows.map((row) => [row.portfolio_id, row.portfolio_name])).entries()], [rows]);

  const filtered = useMemo(() => {
    const needle = applied.search.trim().toLowerCase();
    return rows.filter((row) => {
      if (applied.portfolio && String(row.portfolio_id) !== applied.portfolio) return false;
      if (applied.type !== "all" && row.position_type !== applied.type) return false;
      if (applied.status !== "all" && row.status !== applied.status) return false;
      if (needle && !(row.security_name ?? "").toLowerCase().includes(needle) && !row.full_ticker.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [rows, applied]);

  const sorted = useMemo(() => sortRows(filtered, table.sort), [filtered, table.sort]);
  const pageRows = sorted.slice((table.page - 1) * table.perPage, table.page * table.perPage);
  const totals = filtered.reduce(
    (acc, row) => ({ value: acc.value + row.value_n, ret: acc.ret === null || row.return_n === null ? null : acc.ret + row.return_n, dividends: acc.dividends + row.dividends_n }),
    { value: 0, ret: 0 as number | null, dividends: 0 },
  );

  function apply(next: Filters) {
    const merged = new URLSearchParams(params);
    const entries: [string, string, string][] = [
      ["portfolio", next.portfolio, ""],
      ["type", next.type, "all"],
      ["status", next.status, "open"],
      ["search", next.search, ""],
    ];
    for (const [key, value, defaultValue] of entries) {
      if (value && value !== defaultValue) merged.set(key, value);
      else merged.delete(key);
    }
    merged.set("page", "1");
    setParams(merged);
  }

  return (
    <AppShell title="Positions">
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start" }}>
        <FilterPanel
          onReset={() => apply(filterDefaults.defaults)}
          onSaveDefault={() => {
            filters.flush();
            void filterDefaults.save(filters.draft);
          }}
          savedDefault={{ exists: filterDefaults.saved !== null, busy: filterDefaults.busy, error: filterDefaults.error, onClear: () => void filterDefaults.clear() }}
        >
          <FilterField label="Portfolio">
            <Select fullWidth displayEmpty value={filters.draft.portfolio} onChange={(event) => filters.setNow({ portfolio: String(event.target.value) })}>
              <MenuItem value="">All portfolios</MenuItem>
              {portfolios.map(([id, name]) => (
                <MenuItem key={id} value={String(id)}>
                  {name}
                </MenuItem>
              ))}
            </Select>
          </FilterField>
          <FilterField label="Type">
            <ToggleButtonGroup exclusive fullWidth size="small" value={filters.draft.type} onChange={(_event, value: string | null) => value && filters.setNow({ type: value })}>
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="long">Long</ToggleButton>
              <ToggleButton value="short">Short</ToggleButton>
            </ToggleButtonGroup>
          </FilterField>
          <FilterField label="Status">
            <ToggleButtonGroup exclusive fullWidth size="small" value={filters.draft.status} onChange={(_event, value: string | null) => value && filters.setNow({ status: value })}>
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="open">Open</ToggleButton>
              <ToggleButton value="closed">Closed</ToggleButton>
            </ToggleButtonGroup>
          </FilterField>
        </FilterPanel>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
          {positions === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", mb: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {filtered.length} positions · value {amount(totals.value)} {currency} · return {amount(totals.ret)} {currency} · dividends{" "}
              {amount(totals.dividends)} {currency}
            </Typography>
            <TableSearch value={filters.draft.search} onChange={(search) => filters.set({ search })} onFlush={filters.flush} />
          </Stack>
          <DataTable
            columns={columns}
            rows={pageRows}
            total={filtered.length}
            rowKey={(row) => String(row.id)}
            page={table.page}
            perPage={table.perPage}
            sort={table.sort}
            onPageChange={table.setPage}
            onPerPageChange={table.setPerPage}
            onSortChange={table.setSort}
            onRowClick={(row) => navigate(`/investments/positions/${row.id}`)}
            offsetTop={190}
          />
        </Box>
      </Stack>
    </AppShell>
  );
}
