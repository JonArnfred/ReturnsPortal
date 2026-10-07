import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import { fetchReconciliationIssues, type IssueRow } from "../api/client";
import AppShell from "../app/AppShell";
import { brokerLabel } from "../app/brokers";
import { Amount, SecurityCell } from "../components/cells";
import DataTable, { sortRows, useTableParams, type Column } from "../components/DataTable";
import { formatPct, formatRate } from "../components/format";

const kindLabel: Record<string, string> = {
  nav_mismatch: "NAV mismatch",
  missing_price: "Missing price",
  stale_price: "Stale price",
  missing_fx: "Missing FX",
  inferred_split: "Inferred split",
};

const kindColor: Record<string, "warning" | "error" | "info" | "default"> = {
  nav_mismatch: "error",
  missing_price: "error",
  stale_price: "warning",
  missing_fx: "error",
  inferred_split: "info",
};

type Row = IssueRow & { amount_n: number | null };


/** Where a NAV mismatch comes from: the three parts sum to the issue amount; the largest is emphasized. */
function GapBreakdown({ row }: { row: Row }) {
  if (row.kind !== "nav_mismatch") return null;
  if (row.gap_fx === null || row.gap_cash === null || row.gap_securities === null) {
    return (
      <Typography variant="caption" color="text.secondary">
        Broker FX rates not known
      </Typography>
    );
  }
  const parts = [
    { key: "fx", label: `FX: ECB vs ${brokerLabel(row.broker, "short") || "broker"}`, value: Number(row.gap_fx) },
    { key: "securities", label: "Prices & holdings", value: Number(row.gap_securities) },
    { key: "cash", label: "Cash", value: Number(row.gap_cash) },
  ];
  const total = parts.reduce((sum, part) => sum + Math.abs(part.value), 0);
  const largest = parts.reduce((best, part) => (Math.abs(part.value) > Math.abs(best.value) ? part : best));
  return (
    <Box sx={{ display: "inline-grid", gridTemplateColumns: "auto auto auto", columnGap: 1.5, rowGap: 0.25, alignItems: "baseline" }}>
      {parts.map((part) => {
        const share = total > 0 ? Math.abs(part.value) / total : 0;
        const main = part.key === largest.key && share > 0;
        const color = main ? "text.primary" : share < 0.01 ? "text.disabled" : "text.secondary";
        return (
          <Box key={part.key} sx={{ display: "contents", color, fontWeight: main ? 600 : 400 }}>
            <Box component="span">{part.label}</Box>
            <Box component="span" sx={{ textAlign: "right" }}>
              <Amount value={part.value} digits={2} />
            </Box>
            <Box component="span" sx={{ textAlign: "right", fontVariantNumeric: "tabular-nums" }}>
              {Math.round(share * 100)}%
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}

/**
 * The rate each side valued a held currency at, in the reporting currency per unit. The broker's own
 * quote (IBKR: into the account base) is shown under its rate; "Diff" is ECB over broker, and
 * "Effect" the currency's part of the FX gap. Dust holdings are left out.
 */
function FxRates({ row }: { row: Row }) {
  if (row.kind !== "nav_mismatch") return null;
  const broker = brokerLabel(row.broker, "short") || "Broker";
  const rates = (row.fx_rates ?? []).filter((rate) => Math.abs(Number(rate.value_local) * Number(rate.ecb_rate)) >= 1);
  if (rates.length === 0) return null;
  const head = { color: "text.secondary", fontSize: "0.75rem" };
  const num = { textAlign: "right", fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" } as const;
  return (
    <Box sx={{ display: "inline-grid", gridTemplateColumns: "auto auto auto auto auto", columnGap: 1.5, rowGap: 0.25, alignItems: "baseline" }}>
      <Box sx={{ ...head, whiteSpace: "nowrap" }}>{row.currency ? `${row.currency} per` : null}</Box>
      <Box sx={{ ...head, ...num }}>ECB</Box>
      <Box sx={{ ...head, ...num }}>{broker}</Box>
      <Box sx={{ ...head, ...num }}>Diff %</Box>
      <Box sx={{ ...head, ...num }}>Effect</Box>
      {rates.map((rate) => {
        const ecb = Number(rate.ecb_rate);
        const brokerRate = rate.broker_rate === null ? null : Number(rate.broker_rate);
        const diff = brokerRate ? ecb / brokerRate - 1 : null;
        const same = diff !== null && Math.abs(diff) < 0.000005;
        const quoted = rate.broker_quote_currency && rate.broker_quote_currency !== rate.currency;
        return (
          <Box key={rate.currency} sx={{ display: "contents", color: same ? "text.disabled" : "text.primary" }}>
            <Box component="span" sx={{ fontWeight: 600 }}>
              {rate.currency}
            </Box>
            <Box component="span" sx={num} title={rate.ecb_rate_date ? `ECB fixing of ${rate.ecb_rate_date}` : undefined}>
              {formatRate(ecb)}
            </Box>
            <Box component="span" sx={num} title={rate.broker_rate_date ? `${broker} rate of ${rate.broker_rate_date}` : undefined}>
              {formatRate(brokerRate)}
              {quoted ? (
                <Box component="span" sx={{ display: "block", color: "text.secondary", fontSize: "0.75rem" }}>
                  {formatRate(Number(rate.broker_quote_rate))} {rate.broker_quote_currency}
                </Box>
              ) : null}
            </Box>
            <Box component="span" sx={num}>
              {same ? "same" : formatPct(diff, 2)}
            </Box>
            <Box component="span" sx={num}>
              <Amount value={rate.gap_fx === null ? null : Number(rate.gap_fx)} digits={2} />
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}

const columns: Column<Row>[] = [
  { key: "day", header: "Date", sortKey: "day", noWrap: true, render: (row) => row.day },
  { key: "portfolio", header: "Portfolio", sortKey: "portfolio_name", render: (row) => row.portfolio_name },
  {
    key: "kind",
    header: "Kind",
    sortKey: "kind",
    render: (row) => <Chip size="small" variant="outlined" color={kindColor[row.kind] ?? "default"} label={kindLabel[row.kind] ?? row.kind} />,
  },
  {
    key: "security",
    header: "Security",
    sortKey: "security_name",
    render: (row) => (row.security_name ? <SecurityCell name={row.security_name} fullTicker={row.full_ticker ?? ""} /> : (row.currency ?? "-")),
  },
  { key: "message", header: "Message", render: (row) => row.message },
  { key: "source", header: "Where from", render: (row) => <GapBreakdown row={row} /> },
  { key: "fx_rates", header: "FX rates", render: (row) => <FxRates row={row} /> },
  { key: "amount", header: "Amount", align: "right", sortKey: "amount_n", render: (row) => <Amount value={row.amount_n} digits={2} /> },
];

export default function ReconciliationPage() {
  const table = useTableParams("day");
  const [issues, setIssues] = useState<IssueRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchReconciliationIssues()
      .then((payload) => {
        if (!cancelled) setIssues(payload.data);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const rows = useMemo<Row[]>(
    () => (issues ?? []).map((issue) => ({ ...issue, amount_n: issue.amount === null ? null : Number(issue.amount) })),
    [issues],
  );
  const sorted = useMemo(() => sortRows(rows, table.sort), [rows, table.sort]);
  const pageRows = sorted.slice((table.page - 1) * table.perPage, table.page * table.perPage);

  return (
    <AppShell title="Reconciliation">
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {issues === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
      <DataTable
        columns={columns}
        rows={pageRows}
        total={sorted.length}
        rowKey={(row) => String(row.id)}
        page={table.page}
        perPage={table.perPage}
        sort={table.sort}
        onPageChange={table.setPage}
        onPerPageChange={table.setPerPage}
        onSortChange={table.setSort}
      />
    </AppShell>
  );
}
