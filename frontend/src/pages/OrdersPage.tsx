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
import { useSearchParams } from "react-router-dom";
import { fetchOrders, type OrderRow } from "../api/client";
import AppShell from "../app/AppShell";
import { useFilterDefaults } from "../app/useFilterDefaults";
import { useLiveFilters } from "../app/useLiveFilters";
import { Money, Quantity, SecurityCell } from "../components/cells";
import DataTable, { sortRows, useTableParams, type Column } from "../components/DataTable";
import FilterPanel, { FilterField } from "../components/FilterPanel";
import TableSearch from "../components/TableSearch";
import { toNumber } from "../components/format";

type Row = OrderRow & {
  quantity_n: number | null;
  filled_n: number | null;
  price_n: number | null;
  avg_fill_n: number | null;
  placed_sort: string;
};
function formatTime(value: string | null | undefined) {
  return value ? value.replace("T", " ").slice(0, 16) : "-";
}

const statusChip: Record<string, { label: string; color: "success" | "warning" | "error" | "default" | "info" }> = {
  working: { label: "Outstanding", color: "info" },
  filled: { label: "Filled", color: "success" },
  cancelled: { label: "Cancelled", color: "default" },
  expired: { label: "Expired", color: "default" },
  rejected: { label: "Rejected", color: "error" },
  other: { label: "Other", color: "warning" },
};

function StatusCell({ row }: { row: Row }) {
  const chip = statusChip[row.status] ?? statusChip.other;
  const label = row.status === "working" && !row.is_open ? "Not on book" : chip.label;
  const color = row.status === "working" && !row.is_open ? "warning" : chip.color;
  return (
    <Tooltip title={`Broker status: ${row.broker_status ?? "-"}`}>
      <Chip size="small" variant="outlined" label={label} color={color} />
    </Tooltip>
  );
}

const columns: Column<Row>[] = [
  { key: "placed", header: "Placed", noWrap: true, sortKey: "placed_sort", render: (row) => formatTime(row.placed_at) },
  { key: "portfolio", header: "Portfolio", sortKey: "portfolio_name", render: (row) => <Chip size="small" variant="outlined" label={row.portfolio_name} /> },
  { key: "security", header: "Security", sortKey: "security_name", render: (row) => <SecurityCell name={row.security_name ?? "-"} fullTicker={row.full_ticker ?? row.instrument_symbol ?? ""} /> },
  {
    key: "side",
    header: "Side",
    align: "center",
    sortKey: "buy_sell",
    render: (row) => (row.buy_sell ? <Chip size="small" label={row.buy_sell === "buy" ? "Buy" : "Sell"} color={row.buy_sell === "buy" ? "success" : "error"} variant="outlined" /> : "-"),
  },
  { key: "type", header: "Type", noWrap: true, sortKey: "order_type", render: (row) => `${row.order_type ?? "-"}${row.duration ? ` · ${row.duration}` : ""}` },
  { key: "quantity", header: "Quantity", align: "right", sortKey: "quantity_n", render: (row) => <Quantity value={row.quantity_n} /> },
  { key: "filled", header: "Filled", align: "right", sortKey: "filled_n", render: (row) => <Quantity value={row.filled_n} /> },
  { key: "price", header: "Price", align: "right", sortKey: "price_n", render: (row) => <Money value={row.price_n} currency={row.currency ?? undefined} digits={2} /> },
  { key: "avg_fill", header: "Avg fill", align: "right", sortKey: "avg_fill_n", render: (row) => <Money value={row.avg_fill_n} currency={row.currency ?? undefined} digits={2} /> },
  { key: "status", header: "Status", align: "center", sortKey: "status", render: (row) => <StatusCell row={row} /> },
  { key: "activity", header: "Last activity", noWrap: true, sortKey: "last_activity_at", render: (row) => formatTime(row.last_activity_at) },
  { key: "expires", header: "Expires", noWrap: true, render: (row) => formatTime(row.expires_at) },
  { key: "account", header: "Account", noWrap: true, render: (row) => row.account_label ?? "-" },
];

type Filters = { portfolio: string; status: string; side: string; search: string };
const builtin: Filters = { portfolio: "", status: "all", side: "all", search: "" };

export default function OrdersPage() {
  const [params, setParams] = useSearchParams();
  const filterDefaults = useFilterDefaults("orders", builtin);
  const applied = useMemo<Filters>(
    () => ({
      portfolio: params.get("portfolio") ?? builtin.portfolio,
      status: params.get("status") ?? builtin.status,
      side: params.get("side") ?? builtin.side,
      search: params.get("search") ?? builtin.search,
    }),
    [params],
  );
  const filters = useLiveFilters(applied, apply);
  const [orders, setOrders] = useState<OrderRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const table = useTableParams("placed_sort");

  useEffect(() => {
    let cancelled = false;
    fetchOrders()
      .then((payload) => {
        if (!cancelled) setOrders(payload.data);
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
      (orders ?? []).map((row) => ({
        ...row,
        quantity_n: toNumber(row.quantity),
        filled_n: toNumber(row.filled_quantity),
        price_n: toNumber(row.price),
        avg_fill_n: toNumber(row.average_fill_price),
        placed_sort: row.placed_at ?? "",
      })),
    [orders],
  );
  const portfolios = useMemo(() => [...new Map(rows.map((row) => [row.portfolio_id, row.portfolio_name])).entries()], [rows]);

  const filtered = useMemo(() => {
    const needle = applied.search.trim().toLowerCase();
    return rows.filter((row) => {
      if (applied.portfolio && String(row.portfolio_id) !== applied.portfolio) return false;
      if (applied.status === "open" ? !row.is_open : applied.status !== "all" && row.status !== applied.status) return false;
      if (applied.side !== "all" && row.buy_sell !== applied.side) return false;
      if (needle) {
        const haystack = `${row.security_name ?? ""} ${row.full_ticker ?? ""} ${row.instrument_symbol ?? ""}`.toLowerCase();
        if (!haystack.includes(needle)) return false;
      }
      return true;
    });
  }, [rows, applied]);

  const sorted = useMemo(() => sortRows(filtered, table.sort), [filtered, table.sort]);
  const pageRows = sorted.slice((table.page - 1) * table.perPage, table.page * table.perPage);
  const openCount = filtered.filter((row) => row.is_open).length;

  function apply(next: Filters) {
    const merged = new URLSearchParams(params);
    for (const key of Object.keys(builtin) as (keyof Filters)[]) {
      if (next[key] && next[key] !== builtin[key]) merged.set(key, next[key]);
      else merged.delete(key);
    }
    merged.set("page", "1");
    setParams(merged);
  }

  return (
    <AppShell title="Orders">
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
          <FilterField label="Status">
            <Select fullWidth value={filters.draft.status} onChange={(event) => filters.setNow({ status: String(event.target.value) })}>
              <MenuItem value="all">All orders</MenuItem>
              <MenuItem value="open">Outstanding</MenuItem>
              <MenuItem value="filled">Filled</MenuItem>
              <MenuItem value="cancelled">Cancelled</MenuItem>
              <MenuItem value="expired">Expired</MenuItem>
              <MenuItem value="rejected">Rejected</MenuItem>
            </Select>
          </FilterField>
          <FilterField label="Side">
            <ToggleButtonGroup exclusive fullWidth size="small" value={filters.draft.side} onChange={(_event, value: string | null) => value && filters.setNow({ side: value })}>
              <ToggleButton value="all">All</ToggleButton>
              <ToggleButton value="buy">Buy</ToggleButton>
              <ToggleButton value="sell">Sell</ToggleButton>
            </ToggleButtonGroup>
          </FilterField>
        </FilterPanel>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
          {orders === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", mb: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {filtered.length} orders · {openCount} outstanding
              {orders && orders.length === 0 ? " · no orders captured yet, run a broker sync" : ""}
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
            offsetTop={190}
          />
        </Box>
      </Stack>
    </AppShell>
  );
}
