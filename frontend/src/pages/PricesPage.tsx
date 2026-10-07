import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutlined";
import ErrorOutlineIcon from "@mui/icons-material/ErrorOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { fetchDailyPrices, fetchPriceStatus, type DailyPriceRow, type PriceStatusRow } from "../api/client";
import AppShell from "../app/AppShell";
import { useLiveFilters } from "../app/useLiveFilters";
import TimeSeriesChart from "../charts/TimeSeriesChart";
import { Money, Pct, SecurityCell } from "../components/cells";
import DataTable, { sortRows, useTableParams, type Column } from "../components/DataTable";
import { formatNumber, toNumber } from "../components/format";
import SplitView from "../components/SplitView";
import TableSearch from "../components/TableSearch";

type Row = PriceStatusRow & { last_close_n: number | null; late_days: number | null; stale_days: number | null };
const dayDiff = (later: string | null | undefined, earlier: string | null | undefined) =>
  later && earlier ? Math.round((Date.parse(later) - Date.parse(earlier)) / 86_400_000) : null;

const sourceChip: Record<string, { label: string; color: "success" | "info" | "default" }> = {
  saxo: { label: "Saxo", color: "success" },
  yahoo: { label: "Yahoo", color: "info" },
  none: { label: "None", color: "default" },
};

function CoverageCell({ row }: { row: Row }) {
  if (row.last_error) {
    return (
      <Tooltip title={row.last_error}>
        <Chip size="small" color="error" variant="outlined" icon={<ErrorOutlineIcon />} label="Error" />
      </Tooltip>
    );
  }
  if (row.bars === 0) return <Chip size="small" variant="outlined" label="No prices" />;
  const notes: string[] = [];
  if (row.late_days !== null && row.late_days > 0) notes.push(`starts ${row.late_days} days after first trade`);
  if (row.held && row.stale_days !== null && row.stale_days > 4) notes.push(`last bar ${row.stale_days} days old`);
  if (notes.length === 0) {
    return <CheckCircleOutlineIcon sx={{ fontSize: 18, color: "success.main", display: "block", mx: "auto" }} />;
  }
  return (
    <Tooltip title={notes.join("; ")}>
      <Chip size="small" color="warning" variant="outlined" label="Gap" />
    </Tooltip>
  );
}

const columns: Column<Row>[] = [
  { key: "security", header: "Security", sortKey: "security_name", render: (row) => <SecurityCell name={row.security_name ?? "-"} fullTicker={row.full_ticker} /> },
  { key: "type", header: "Type", sortKey: "asset_type", render: (row) => row.asset_type },
  { key: "held", header: "Held", align: "center", sortKey: "held", render: (row) => (row.held ? "Yes" : "-") },
  {
    key: "source",
    header: "Source",
    align: "center",
    sortKey: "source",
    render: (row) => {
      const chip = sourceChip[row.source] ?? sourceChip.none;
      return (
        <Tooltip title={row.yahoo_symbol ? `Yahoo symbol ${row.yahoo_symbol}` : ""}>
          <Chip size="small" variant="outlined" color={chip.color} label={chip.label} />
        </Tooltip>
      );
    },
  },
  { key: "close", header: "Last close", align: "right", sortKey: "last_close_n", render: (row) => <Money value={row.last_close_n} currency={row.currency ?? undefined} digits={2} /> },
  { key: "coverage", header: "Coverage", align: "center", render: (row) => <CoverageCell row={row} /> },
  { key: "first_needed", header: "First trade", noWrap: true, sortKey: "first_needed", render: (row) => row.first_needed ?? "-" },
  { key: "first", header: "First price", noWrap: true, sortKey: "first_price_date", render: (row) => row.first_price_date ?? "-" },
  { key: "last", header: "Last price", noWrap: true, sortKey: "last_price_date", render: (row) => row.last_price_date ?? "-" },
  { key: "bars", header: "Bars", align: "right", sortKey: "bars", render: (row) => formatNumber(row.bars) },
];

type Bar = DailyPriceRow & { change: number | null };

/** Right pane of the split: close chart on top, OHLCV bars below, newest first. */
function PriceDetail({ security, bars }: { security: Row; bars: DailyPriceRow[] | null }) {
  const rows = useMemo<Bar[]>(() => {
    const list = bars ?? [];
    return list
      .map((bar, index) => {
        const previous = index > 0 ? Number(list[index - 1].close) : null;
        return { ...bar, change: previous ? Number(bar.close) / previous - 1 : null };
      })
      .reverse();
  }, [bars]);
  const points = useMemo(() => (bars ?? []).map((bar) => ({ date: bar.price_date, value: Number(bar.close) })), [bars]);
  const cell = (value: string | null) => <Money value={toNumber(value)} digits={2} />;

  return (
    <Paper variant="outlined" sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", px: 1.5, pt: 1.25 }}>
        <Typography variant="h3" component="div">
          {security.security_name ?? security.full_ticker} · daily close ({security.currency ?? "-"})
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {bars === null ? "loading…" : `${bars.length} bars · source ${security.source}`}
        </Typography>
      </Stack>
      <Box sx={{ px: 1, pb: 0.5 }}>
        {bars === null ? <Box sx={{ height: 260 }} /> : <TimeSeriesChart series={[{ name: "Close", points }]} height={260} decimals={2} />}
      </Box>
      <TableContainer sx={{ flex: 1, minHeight: 0, borderTop: "1px solid", borderColor: "divider" }}>
        <Table stickyHeader size="small">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell align="right">Open</TableCell>
              <TableCell align="right">High</TableCell>
              <TableCell align="right">Low</TableCell>
              <TableCell align="right">Close</TableCell>
              <TableCell align="right">Change</TableCell>
              <TableCell align="right">Volume</TableCell>
              <TableCell>Source</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((bar) => (
              <TableRow key={bar.price_date} hover>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{bar.price_date}</TableCell>
                <TableCell align="right">{cell(bar.open)}</TableCell>
                <TableCell align="right">{cell(bar.high)}</TableCell>
                <TableCell align="right">{cell(bar.low)}</TableCell>
                <TableCell align="right">{cell(bar.close)}</TableCell>
                <TableCell align="right">
                  <Pct value={bar.change} />
                </TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>{formatNumber(toNumber(bar.volume))}</TableCell>
                <TableCell>{bar.source}</TableCell>
              </TableRow>
            ))}
            {bars !== null && rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={8} align="center" sx={{ py: 4, color: "text.secondary" }}>
                  No bars stored for this security.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

type Filters = { search: string };

export default function PricesPage() {
  const [params, setParams] = useSearchParams();
  const applied = useMemo<Filters>(() => ({ search: params.get("search") ?? "" }), [params]);
  const selectedId = Number(params.get("security") ?? "") || null;
  const table = useTableParams("security_name", "asc");
  const [status, setStatus] = useState<PriceStatusRow[] | null>(null);
  // Stamped when the status arrives (in the browser), so nothing reads the clock during render.
  const [today, setToday] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [bars, setBars] = useState<DailyPriceRow[] | null>(null);

  function apply(next: Filters) {
    const merged = new URLSearchParams(params);
    if (next.search) merged.set("search", next.search);
    else merged.delete("search");
    merged.set("page", "1");
    setParams(merged);
  }
  const filters = useLiveFilters(applied, apply);

  useEffect(() => {
    let cancelled = false;
    fetchPriceStatus()
      .then((payload) => {
        if (cancelled) return;
        setToday(new Date().toISOString().slice(0, 10));
        setStatus(payload.data);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (selectedId === null) {
      setBars(null);
      return;
    }
    let cancelled = false;
    setBars(null);
    fetchDailyPrices(selectedId)
      .then((payload) => {
        if (!cancelled) setBars(payload.data);
      })
      .catch(() => {
        if (!cancelled) setBars([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  const rows = useMemo<Row[]>(
    () =>
      (status ?? []).map((row) => ({
        ...row,
        last_close_n: toNumber(row.last_close),
        late_days: dayDiff(row.first_price_date, row.first_needed),
        stale_days: dayDiff(today, row.last_price_date),
      })),
    [status, today],
  );
  const filtered = useMemo(() => {
    const needle = applied.search.trim().toLowerCase();
    return needle ? rows.filter((row) => `${row.security_name ?? ""} ${row.full_ticker}`.toLowerCase().includes(needle)) : rows;
  }, [rows, applied.search]);
  const sorted = useMemo(() => sortRows(filtered, table.sort), [filtered, table.sort]);
  const pageRows = sorted.slice((table.page - 1) * table.perPage, table.page * table.perPage);
  const selected = rows.find((row) => row.security_id === selectedId) ?? null;
  const counts = rows.reduce(
    (acc, row) => ({ ...acc, [row.source]: (acc[row.source] ?? 0) + 1, errors: acc.errors + (row.last_error ? 1 : 0) }),
    { errors: 0 } as Record<string, number>,
  );

  function select(row: Row) {
    const merged = new URLSearchParams(params);
    if (selectedId === row.security_id) merged.delete("security");
    else merged.set("security", String(row.security_id));
    setParams(merged, { replace: true });
  }

  return (
    <AppShell title="Prices">
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {status === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "center", justifyContent: "space-between", flexWrap: "wrap", mb: 1 }}>
        <Typography variant="body2" color="text.secondary">
          {rows.length} securities · {counts.saxo ?? 0} from Saxo · {counts.yahoo ?? 0} from Yahoo · {counts.none ?? 0} without a source · {counts.errors} with errors
        </Typography>
        <TableSearch value={filters.draft.search} onChange={(search) => filters.set({ search })} onFlush={filters.flush} />
      </Stack>
      <SplitView
        leftWidth={720}
        offsetTop={56}
        placeholder="Click a security to see its close chart and daily bars."
        left={
          <DataTable
            columns={columns}
            rows={pageRows}
            total={filtered.length}
            rowKey={(row) => String(row.security_id)}
            page={table.page}
            perPage={table.perPage}
            sort={table.sort}
            onPageChange={table.setPage}
            onPerPageChange={table.setPerPage}
            onSortChange={table.setSort}
            onRowClick={select}
            selectedKey={selectedId === null ? undefined : String(selectedId)}
            fill
          />
        }
        right={selected ? <PriceDetail security={selected} bars={bars} /> : null}
      />
    </AppShell>
  );
}
