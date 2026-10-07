import CheckCircleOutlineIcon from "@mui/icons-material/CheckCircleOutlined";
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
import { fetchFxRates, fetchFxStatus, type FxRateRow, type FxStatusRow } from "../api/client";
import AppShell from "../app/AppShell";
import TimeSeriesChart from "../charts/TimeSeriesChart";
import DataTable, { sortRows, useTableParams, type Column } from "../components/DataTable";
import { formatNumber } from "../components/format";
import SplitView from "../components/SplitView";

type Row = FxStatusRow & { key: string; last_rate_n: number | null; late_days: number | null; stale_days: number | null };

const dayDiff = (later: string | null | undefined, earlier: string | null | undefined) =>
  later && earlier ? Math.round((Date.parse(later) - Date.parse(earlier)) / 86_400_000) : null;

function CoverageCell({ row }: { row: Row }) {
  if (row.currency === row.base_currency) return <span>-</span>;
  const notes: string[] = [];
  if (row.first_date === null) notes.push("no rates stored");
  if (row.late_days !== null && row.late_days > 0) notes.push(`starts ${row.late_days} days after first needed`);
  if (row.stale_days !== null && row.stale_days > 5) notes.push(`last rate ${row.stale_days} days old`);
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
  { key: "currency", header: "Currency", sortKey: "currency", render: (row) => row.currency },
  { key: "base", header: "Base", sortKey: "base_currency", render: (row) => row.base_currency },
  { key: "coverage", header: "Coverage", align: "center", render: (row) => <CoverageCell row={row} /> },
  { key: "first_needed", header: "First needed", noWrap: true, sortKey: "first_needed", render: (row) => row.first_needed ?? "-" },
  { key: "first", header: "First rate", noWrap: true, sortKey: "first_date", render: (row) => row.first_date ?? "-" },
  { key: "last", header: "Last rate date", noWrap: true, sortKey: "last_date", render: (row) => row.last_date ?? "-" },
  { key: "days", header: "Days", align: "right", sortKey: "days", render: (row) => formatNumber(row.days) },
  { key: "rate", header: "Last rate", align: "right", sortKey: "last_rate_n", render: (row) => formatNumber(row.last_rate_n, 6) },
];

function FxDetail({ row, rates }: { row: Row; rates: FxRateRow[] | null }) {
  const points = useMemo(() => (rates ?? []).map((rate) => ({ date: rate.rate_date, value: Number(rate.rate) })), [rates]);
  const latest = useMemo(() => (rates ?? []).slice(-250).reverse(), [rates]);
  return (
    <Paper variant="outlined" sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <Stack direction="row" spacing={1.5} sx={{ alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap", px: 1.5, pt: 1.25 }}>
        <Typography variant="h3" component="div">
          {row.base_currency} per 1 {row.currency}
        </Typography>
        <Typography variant="caption" color="text.secondary">
          {rates === null ? "loading…" : `${rates.length} published days · ECB crossed via EUR`}
        </Typography>
      </Stack>
      <Box sx={{ px: 1, pb: 0.5 }}>
        {rates === null ? <Box sx={{ height: 260 }} /> : <TimeSeriesChart series={[{ name: row.currency, points }]} height={260} decimals={4} />}
      </Box>
      <TableContainer sx={{ flex: 1, minHeight: 0, borderTop: "1px solid", borderColor: "divider" }}>
        <Table stickyHeader size="small">
          <TableHead>
            <TableRow>
              <TableCell>Date</TableCell>
              <TableCell align="right">Rate</TableCell>
              <TableCell>Source</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {latest.map((rate) => (
              <TableRow key={rate.rate_date} hover>
                <TableCell sx={{ whiteSpace: "nowrap" }}>{rate.rate_date}</TableCell>
                <TableCell align="right" sx={{ fontVariantNumeric: "tabular-nums" }}>{formatNumber(Number(rate.rate), 6)}</TableCell>
                <TableCell>{rate.source}</TableCell>
              </TableRow>
            ))}
            {rates !== null && latest.length === 0 ? (
              <TableRow>
                <TableCell colSpan={3} align="center" sx={{ py: 4, color: "text.secondary" }}>
                  No rates stored for this currency.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}

export default function FxPage() {
  const [params, setParams] = useSearchParams();
  const selected = params.get("currency");
  const table = useTableParams("currency", "asc");
  const [status, setStatus] = useState<FxStatusRow[] | null>(null);
  // Stamped when the status arrives (in the browser), so nothing reads the clock during render.
  const [today, setToday] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rates, setRates] = useState<FxRateRow[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchFxStatus()
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

  const rows = useMemo<Row[]>(
    () =>
      (status ?? []).map((row) => ({
        ...row,
        key: `${row.base_currency}:${row.currency}`,
        last_rate_n: row.last_rate === null ? null : Number(row.last_rate),
        late_days: dayDiff(row.first_date, row.first_needed),
        stale_days: dayDiff(today, row.last_date),
      })),
    [status, today],
  );
  const selectedRow = rows.find((row) => row.key === selected) ?? null;

  useEffect(() => {
    if (selectedRow === null) {
      setRates(null);
      return;
    }
    let cancelled = false;
    setRates(null);
    fetchFxRates(selectedRow.currency, selectedRow.base_currency)
      .then((payload) => {
        if (!cancelled) setRates(payload.data);
      })
      .catch(() => {
        if (!cancelled) setRates([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedRow]);

  const sorted = useMemo(() => sortRows(rows, table.sort), [rows, table.sort]);
  const pageRows = sorted.slice((table.page - 1) * table.perPage, table.page * table.perPage);

  function select(row: Row) {
    const merged = new URLSearchParams(params);
    if (selected === row.key) merged.delete("currency");
    else merged.set("currency", row.key);
    setParams(merged, { replace: true });
  }

  return (
    <AppShell title="FX rates">
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {status === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {rows.length} currencies · ECB reference rates crossed through EUR, stored as base currency per unit; the engine carries the last rate over weekends and holidays
      </Typography>
      <SplitView
        leftWidth={640}
        offsetTop={44}
        placeholder="Click a currency to see its rate history."
        left={
          <DataTable
            columns={columns}
            rows={pageRows}
            total={sorted.length}
            rowKey={(row) => row.key}
            page={table.page}
            perPage={table.perPage}
            sort={table.sort}
            onPageChange={table.setPage}
            onPerPageChange={table.setPerPage}
            onSortChange={table.setSort}
            onRowClick={select}
            selectedKey={selected ?? undefined}
            fill
          />
        }
        right={selectedRow ? <FxDetail row={selectedRow} rates={rates} /> : null}
      />
    </AppShell>
  );
}
