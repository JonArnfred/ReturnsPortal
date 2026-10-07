import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import LinearProgress from "@mui/material/LinearProgress";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import { useEffect, useMemo, useState } from "react";
import { fetchDashboard, type DashboardResponse } from "../api/client";
import AppShell from "../app/AppShell";
import { Pct, useAmounts } from "../components/cells";
import { formatNumber, formatPct, toNumber } from "../components/format";
import StatTile from "../components/StatTile";
import TimeSeriesChart from "../charts/TimeSeriesChart";

export default function DashboardPage() {
  const [data, setData] = useState<DashboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetchDashboard()
      .then((payload) => {
        if (!cancelled) setData(payload);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, [reloadKey]);

  return (
    <AppShell title="Dashboard">
      <Stack spacing={1.5}>
        <Stack direction="row" sx={{ justifyContent: "space-between", alignItems: "center" }}>
          <Typography variant="body2" sx={{ color: "text.secondary" }}>
            {data?.as_of ? `${data.intraday ? "Intraday" : "End-of-day"} results as of ${data.as_of}` : "Calculated portfolio results"}
          </Typography>
          <Button size="small" variant="outlined" onClick={() => setReloadKey((key) => key + 1)} disabled={!data && !error}>Refresh</Button>
        </Stack>
        {!data && !error ? <><LinearProgress /><Typography>Loading dashboard…</Typography></> : null}
        {error ? <Alert severity="error">Could not load dashboard. {error}</Alert> : null}
        {data ? <DashboardContent data={data} /> : null}
      </Stack>
    </AppShell>
  );
}

export function DashboardContent({ data }: { data: DashboardResponse }) {
  const totalSeries = useMemo(() => data.series.map((point) => ({ date: point.day, value: Number(point.nav) })), [data]);
  const amounts = useAmounts();
  const money = (value: string | number | null | undefined) => value == null ? "—" : amounts.money(Number(value), data.base_currency ?? "");

  return (
    <>
      {data.warnings.map((warning) => <Alert key={warning} severity="warning">{warning}</Alert>)}
      {!data.as_of ? <Alert severity="info">No combined report is available. Check portfolio coverage and rebuild reports from the Returns page.</Alert> : null}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr 1fr", md: "repeat(4, 1fr)" }, gap: 1.5 }}>
        <StatTile label="Total NAV" value={money(data.nav)} hint={data.as_of ? `as of ${data.as_of}${data.intraday ? ", intraday" : ""}` : "No calculated data"} />
        <StatTile label="Daily PnL" value={<Box sx={{ color: (toNumber(data.daily_pnl) ?? 0) >= 0 ? "success.main" : "error.main" }}>{money(data.daily_pnl)}</Box>} hint={`${formatPct(toNumber(data.daily_return_pct))} %`} />
        <StatTile label="Daily FX effect" value={money(data.fx_effect_base)} hint="across all currencies" />
        <StatTile label="Recorded issues" value={formatNumber(data.issue_count)} hint="within reporting periods" />
      </Box>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", lg: "2fr 1fr" }, gap: 1.5 }}>
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="h3" sx={{ mb: 1 }}>
            Total NAV
          </Typography>
          {totalSeries.length ? <TimeSeriesChart series={[{ name: "Total NAV", points: totalSeries }]} height={220} decimals={0} suffix={` ${data.base_currency}`} sensitive /> : <Typography color="text.secondary">No NAV history available.</Typography>}
        </Paper>
        <Paper variant="outlined" sx={{ p: 1.5 }}>
          <Typography variant="h3" sx={{ mb: 1 }}>
            Portfolios
          </Typography>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Portfolio</TableCell>
                <TableCell align="right">NAV</TableCell>
                <TableCell align="right">Daily PnL</TableCell>
                <TableCell align="right">Day %</TableCell>
                <TableCell align="right">Period %</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.portfolios.length === 0 ? <TableRow><TableCell colSpan={5}>No portfolios connected.</TableCell></TableRow> : null}
              {data.portfolios.map((row) => (
                <TableRow key={row.portfolio_id}>
                  <TableCell>{row.portfolio_name}<Typography variant="caption" component="div" color="text.secondary">{row.reporting_start_date ? `Since ${row.reporting_start_date}` : "Full history"}</Typography></TableCell>
                  <TableCell align="right">{money(row.nav)}</TableCell>
                  <TableCell align="right">{money(row.daily_pnl)}</TableCell>
                  <TableCell align="right">
                    <Pct value={toNumber(row.daily_return_pct)} />
                  </TableCell>
                  <TableCell align="right">
                    <Pct value={toNumber(row.cumulative_return_pct)} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <Typography variant="h3" sx={{ mt: 2, mb: 1 }}>
            Daily FX effect by currency
          </Typography>
          <Table size="small">
            <TableBody>
              {data.fx_by_currency.length === 0 ? <TableRow><TableCell colSpan={2}>No foreign-currency attribution available.</TableCell></TableRow> : null}
              {data.fx_by_currency.map(({ currency: code, effect: value }) => (
                <TableRow key={code}>
                  <TableCell>{code}</TableCell>
                  <TableCell align="right">{money(value)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Paper>
      </Box>

      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 1.5 }}>
        {[
          { title: "Top daily contributors", rows: data.top },
          { title: "Bottom daily contributors", rows: data.bottom },
        ].map((block) => (
          <Paper key={block.title} variant="outlined" sx={{ p: 1.5 }}>
            <Typography variant="h3" sx={{ mb: 1 }}>
              {block.title}
            </Typography>
            {data.as_of ? (
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
                Valuation date: {data.as_of}{data.intraday ? " (intraday prices until the close)" : ""}
              </Typography>
            ) : null}
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Security</TableCell>
                  <TableCell>Portfolio</TableCell>
                  <TableCell align="right">Daily PnL</TableCell>
                  <TableCell align="right">Return %</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {block.rows.length === 0 ? <TableRow><TableCell colSpan={4}>No contributors available.</TableCell></TableRow> : null}
                {block.rows.map((row) => (
                  <TableRow key={`${row.portfolio_id}:${row.position_key}`}>
                    <TableCell>
                      {row.security_name}
                      <Typography component="span" variant="caption" sx={{ color: "text.secondary", ml: 0.75 }}>
                        {row.full_ticker}
                      </Typography>
                    </TableCell>
                    <TableCell>{row.portfolio_name}</TableCell>
                    <TableCell align="right">{money(row.daily_pnl_base)}</TableCell>
                    <TableCell align="right">
                      <Pct value={toNumber(row.daily_return_pct)} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Paper>
        ))}
      </Box>
    </>
  );
}
