import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import TextField from "@mui/material/TextField";
import ToggleButton from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchPortfolios, fetchTransactions, type PortfolioCard, type TransactionRow } from "../api/client";
import AppShell from "../app/AppShell";
import { useFilterDefaults } from "../app/useFilterDefaults";
import { useLiveFilters } from "../app/useLiveFilters";
import { useServerTable } from "../app/useServerTable";
import DataTable, { useTableParams, type Column } from "../components/DataTable";
import FilterPanel, { FilterField } from "../components/FilterPanel";
import TableSearch from "../components/TableSearch";

/** URL parameter names double as the API query names, so useServerTable can forward them untouched. */
type Filters = { portfolio_id: string; account: string; trade_type: string; date_gte: string; date_lte: string; search: string };
const emptyFilters: Filters = { portfolio_id: "", account: "", trade_type: "", date_gte: "", date_lte: "", search: "" };

const filterKeys: (keyof Filters)[] = ["portfolio_id", "account", "trade_type", "date_gte", "date_lte", "search"];

type OptionalFilters = { portfolio?: boolean; account?: boolean; tradeType?: boolean };

type LedgerPageProps = {
  title: string;
  kinds: string;
  columns: Column<TransactionRow>[];
  /** Which filters to show besides period and security. */
  filters?: OptionalFilters;
};

/** Shared page for any ledger view: fixed kinds, a column set, period and search filters, server paging. */
export default function LedgerPage({ title, kinds, columns, filters: optional = {} }: LedgerPageProps) {
  const [params, setParams] = useSearchParams();
  const filterDefaults = useFilterDefaults(title.toLowerCase(), emptyFilters);
  const applied = useMemo<Filters>(
    () => Object.fromEntries(filterKeys.map((key) => [key, params.get(key) ?? ""])) as Filters,
    [params],
  );
  const filters = useLiveFilters(applied, apply);
  const table = useTableParams("trade_date");
  const fixed = useMemo(() => ({ kinds }), [kinds]);
  const { rows, meta, loading, error } = useServerTable(fetchTransactions, fixed, { per_page: "100", order_by: "trade_date", order: "desc" });

  const needsPortfolios = Boolean(optional.portfolio || optional.account);
  const [portfolios, setPortfolios] = useState<PortfolioCard[]>([]);
  useEffect(() => {
    if (!needsPortfolios) return;
    let cancelled = false;
    fetchPortfolios()
      .then((payload) => {
        if (!cancelled) setPortfolios(payload.data);
      })
      .catch(() => undefined); // the dropdowns simply stay empty
    return () => {
      cancelled = true;
    };
  }, [needsPortfolios]);
  const accounts = useMemo(
    () => portfolios.filter((portfolio) => !filters.draft.portfolio_id || String(portfolio.id) === filters.draft.portfolio_id).flatMap((portfolio) => portfolio.accounts),
    [portfolios, filters.draft.portfolio_id],
  );

  function apply(next: Filters) {
    const merged = new URLSearchParams(params);
    for (const key of filterKeys) {
      if (next[key]) merged.set(key, next[key]);
      else merged.delete(key);
    }
    merged.set("page", "1");
    setParams(merged);
  }

  return (
    <AppShell title={title}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "flex-start" }}>
        <FilterPanel
          onReset={() => apply(filterDefaults.defaults)}
          onSaveDefault={() => {
            filters.flush();
            void filterDefaults.save(filters.draft);
          }}
          savedDefault={{ exists: filterDefaults.saved !== null, busy: filterDefaults.busy, error: filterDefaults.error, onClear: () => void filterDefaults.clear() }}
        >
          {optional.portfolio ? (
            <FilterField label="Portfolio">
              <Select
                fullWidth
                displayEmpty
                value={filters.draft.portfolio_id}
                onChange={(event) => {
                  const portfolio_id = String(event.target.value);
                  const stillValid = portfolios
                    .filter((portfolio) => !portfolio_id || String(portfolio.id) === portfolio_id)
                    .some((portfolio) => portfolio.accounts.some((account) => String(account.id) === filters.draft.account));
                  filters.setNow({ portfolio_id, account: stillValid ? filters.draft.account : "" });
                }}
              >
                <MenuItem value="">All portfolios</MenuItem>
                {portfolios.map((portfolio) => (
                  <MenuItem key={portfolio.id} value={String(portfolio.id)}>
                    {portfolio.name}
                  </MenuItem>
                ))}
              </Select>
            </FilterField>
          ) : null}
          {optional.account ? (
            <FilterField label="Account">
              <Select fullWidth displayEmpty value={filters.draft.account} onChange={(event) => filters.setNow({ account: String(event.target.value) })}>
                <MenuItem value="">All accounts</MenuItem>
                {accounts.map((account) => (
                  <MenuItem key={account.id} value={String(account.id)}>
                    {account.label}
                  </MenuItem>
                ))}
              </Select>
            </FilterField>
          ) : null}
          {optional.tradeType ? (
            <FilterField label="Trade type">
              <ToggleButtonGroup exclusive fullWidth size="small" value={filters.draft.trade_type || "all"} onChange={(_event, value: string | null) => value && filters.setNow({ trade_type: value === "all" ? "" : value })}>
                <ToggleButton value="all">All</ToggleButton>
                <ToggleButton value="buy">Buy</ToggleButton>
                <ToggleButton value="sell">Sell</ToggleButton>
                <ToggleButton value="corporate_action">Corp.</ToggleButton>
              </ToggleButtonGroup>
            </FilterField>
          ) : null}
          <FilterField label="Period">
            <Stack spacing={1}>
              <TextField fullWidth label="From" placeholder="YYYY-MM-DD" value={filters.draft.date_gte} onChange={(event) => filters.set({ date_gte: event.target.value })} />
              <TextField fullWidth label="To" placeholder="YYYY-MM-DD" value={filters.draft.date_lte} onChange={(event) => filters.set({ date_lte: event.target.value })} />
            </Stack>
          </FilterField>
        </FilterPanel>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
          {loading ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
          <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", mb: 1 }}>
            <Typography variant="body2" color="text.secondary">
              {meta ? `${meta.total} rows` : ""}
            </Typography>
            <TableSearch value={filters.draft.search} onChange={(search) => filters.set({ search })} onFlush={filters.flush} />
          </Stack>
          <DataTable
            columns={columns}
            rows={rows}
            total={meta?.total ?? 0}
            rowKey={(row) => String(row.id)}
            page={table.page}
            perPage={table.perPage}
            sort={table.sort}
            onPageChange={table.setPage}
            onPerPageChange={table.setPerPage}
            onSortChange={table.setSort}
            offsetTop={200}
          />
        </Box>
      </Stack>
    </AppShell>
  );
}
