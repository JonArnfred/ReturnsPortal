import EditOutlinedIcon from "@mui/icons-material/EditOutlined";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import IconButton from "@mui/material/IconButton";
import LinearProgress from "@mui/material/LinearProgress";
import Link from "@mui/material/Link";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import { Link as RouterLink } from "react-router-dom";
import { fetchPortfolios, updatePortfolio, type PortfolioCard } from "../api/client";
import AppShell from "../app/AppShell";
import { brokerLabel } from "../app/brokers";
import { useAmounts } from "../components/cells";
import { toNumber } from "../components/format";


const statusChip: Record<string, { label: string; color: "success" | "warning" | "error" | "default" }> = {
  connected: { label: "Connected", color: "success" },
  expired: { label: "Token expired", color: "warning" },
  error: { label: "Last sync failed", color: "error" },
};
function Metric({ label, value }: { label: string; value: string }) {
  return (
    <Box>
      <Typography variant="caption" color="text.secondary" component="div">
        {label}
      </Typography>
      <Typography variant="h3" component="div" sx={{ fontVariantNumeric: "tabular-nums" }}>
        {value}
      </Typography>
    </Box>
  );
}

function NameEditor({ portfolio, onSaved }: { portfolio: PortfolioCard; onSaved: (updated: PortfolioCard) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(portfolio.display_name ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function start() {
    setDraft(portfolio.display_name ?? "");
    setError(null);
    setEditing(true);
  }

  async function save(value: string | null) {
    setSaving(true);
    setError(null);
    try {
      onSaved(await updatePortfolio(portfolio.id, { display_name: value }));
      setEditing(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) {
    return (
      <Box sx={{ minWidth: 0 }}>
        <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
          <Typography variant="h2" component="div" sx={{ lineHeight: 1.2 }}>
            {portfolio.name}
          </Typography>
          <Tooltip title="Rename portfolio">
            <IconButton size="small" aria-label="Rename portfolio" onClick={start}>
              <EditOutlinedIcon sx={{ fontSize: 16 }} />
            </IconButton>
          </Tooltip>
        </Stack>
        {portfolio.display_name ? (
          <Typography variant="caption" color="text.secondary" component="div">
            Broker name: {portfolio.broker_name}
          </Typography>
        ) : null}
      </Box>
    );
  }

  return (
    <Box component="form" sx={{ minWidth: 0, flex: 1 }} onSubmit={(event) => { event.preventDefault(); void save(draft); }}>
      <TextField
        autoFocus
        fullWidth
        size="small"
        label="Display name"
        placeholder={portfolio.broker_name}
        value={draft}
        disabled={saving}
        error={Boolean(error)}
        helperText={error ?? `Shown everywhere instead of "${portfolio.broker_name}". Leave empty to use the broker name.`}
        slotProps={{ htmlInput: { maxLength: 80 } }}
        onChange={(event) => setDraft(event.target.value)}
        onKeyDown={(event) => event.key === "Escape" && setEditing(false)}
      />
      <Stack direction="row" spacing={1} sx={{ mt: 1 }}>
        <Button type="submit" size="small" variant="contained" disabled={saving}>
          Save
        </Button>
        <Button size="small" disabled={saving} onClick={() => setEditing(false)}>
          Cancel
        </Button>
        {portfolio.display_name ? (
          <Button size="small" color="inherit" disabled={saving} onClick={() => void save(null)}>
            Use broker name
          </Button>
        ) : null}
      </Stack>
    </Box>
  );
}

function ReportingDateEditor({ portfolio, onSaved }: { portfolio: PortfolioCard; onSaved: (updated: PortfolioCard) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(portfolio.reporting_start_date ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [maxDate, setMaxDate] = useState("");

  function startEditing() {
    const today = new Date();
    setMaxDate(`${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`);
    setDraft(portfolio.reporting_start_date ?? "");
    setError(null);
    setEditing(true);
  }

  async function save(value: string | null) {
    setSaving(true);
    setError(null);
    try {
      onSaved(await updatePortfolio(portfolio.id, { reporting_start_date: value }));
      setEditing(false);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  if (!editing) return (
    <Stack sx={{ gap: 0.5, alignItems: "flex-start" }}>
      <Typography variant="body2">
        Reporting: {portfolio.reporting_start_date ? `Since ${portfolio.reporting_start_date}` : "Full history"}
      </Typography>
      <Button size="small" onClick={startEditing}>
        Change reporting start date
      </Button>
    </Stack>
  );

  return (
    <Box component="form" onSubmit={(event) => { event.preventDefault(); void save(draft || null); }}>
      <TextField
        autoFocus fullWidth size="small" type="date" label="Reporting start date"
        value={draft} disabled={saving} error={Boolean(error)}
        onChange={(event) => setDraft(event.target.value)}
        slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: maxDate } }}
        helperText={error ?? "Returns and activity begin on this date. Existing holdings and cash carry forward. Leave blank for full history."}
      />
      <Stack direction="row" spacing={1} useFlexGap sx={{ mt: 1, flexWrap: "wrap" }}>
        <Button type="submit" size="small" variant="contained" disabled={saving}>{saving ? "Saving…" : "Save date"}</Button>
        <Button size="small" disabled={saving} onClick={() => setEditing(false)}>Cancel</Button>
        {portfolio.reporting_start_date ? <Button size="small" disabled={saving} onClick={() => void save(null)}>Use full history</Button> : null}
      </Stack>
    </Box>
  );
}

function Card({ portfolio, onChange }: { portfolio: PortfolioCard; onChange: (updated: PortfolioCard) => void }) {
  const { amount } = useAmounts();
  const currency = portfolio.base_currency;
  const cash = toNumber(portfolio.cash_base);
  const total = toNumber(portfolio.total_value_base);
  const positions = toNumber(portfolio.positions_value_base) ?? 0;
  const unbooked = toNumber(portfolio.unbooked_base);
  const unexplained = toNumber(portfolio.unexplained_base);
  const status = portfolio.connection_status ? statusChip[portfolio.connection_status] : null;
  const broker = portfolio.broker ? brokerLabel(portfolio.broker) : "No connection";
  const positionsHref = `/investments/positions?portfolio=${portfolio.id}`;

  return (
    <Paper variant="outlined" sx={{ p: 2, display: "flex", flexDirection: "column", gap: 1.5 }}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "flex-start", justifyContent: "space-between" }}>
        <Box sx={{ minWidth: 0, flex: 1 }}>
          <NameEditor portfolio={portfolio} onSaved={onChange} />
          <Typography variant="body2" color="text.secondary" component="div">
            {broker}
            {portfolio.environment === "sim" ? " (simulation)" : ""} · base {currency}
          </Typography>
        </Box>
        {status ? <Chip size="small" label={status.label} color={status.color} variant="outlined" /> : null}
      </Stack>

      <Box sx={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 2 }}>
        <Metric label="Open positions" value={String(portfolio.open_positions)} />
        <Metric label={`Cash (${currency})`} value={amount(cash)} />
        <Metric label={`Positions (${currency})`} value={amount(positions)} />
      </Box>

      <Divider />

      <Stack direction="row" spacing={1} sx={{ alignItems: "baseline", justifyContent: "space-between", flexWrap: "wrap" }}>
        <Typography variant="body2" component="div">
          Total value <strong>{amount(total)}</strong> {currency}
          {unbooked !== null && Math.abs(unbooked) >= 0.5 ? (
            <Typography variant="caption" color="text.secondary" component="span" sx={{ ml: 1 }}>
              (incl. {unbooked > 0 ? "+" : ""}
              {amount(unbooked)} unbooked trades)
            </Typography>
          ) : null}
          {unexplained !== null && Math.abs(unexplained) >= 0.5 ? (
            <Typography variant="caption" color="text.secondary" component="span" sx={{ ml: 1 }}>
              ({unexplained > 0 ? "+" : ""}
              {amount(unexplained)} not in cash or positions)
            </Typography>
          ) : null}
        </Typography>
        <Typography variant="caption" color="text.secondary" component="div">
          {portfolio.snapshot_date ? `broker snapshot ${portfolio.snapshot_date}` : "no broker snapshot yet"}
        </Typography>
      </Stack>

      {portfolio.cash_by_currency.length > 0 ? (
        <Stack direction="row" spacing={0.75} sx={{ flexWrap: "wrap", gap: 0.75 }}>
          {portfolio.cash_by_currency.map((row) => (
            <Chip key={row.currency} size="small" variant="outlined" label={`${row.currency} ${amount(toNumber(row.amount), 2)}`} />
          ))}
        </Stack>
      ) : null}

      <Divider />
      <ReportingDateEditor portfolio={portfolio} onSaved={onChange} />

      <Link component={RouterLink} to={positionsHref} variant="body2" underline="hover">
        View open positions
      </Link>
    </Paper>
  );
}

export default function PortfoliosPage() {
  const [portfolios, setPortfolios] = useState<PortfolioCard[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchPortfolios()
      .then((payload) => {
        if (!cancelled) setPortfolios(payload.data);
      })
      .catch((reason: unknown) => {
        if (!cancelled) setError(reason instanceof Error ? reason.message : String(reason));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <AppShell title="Portfolios">
      {error ? <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert> : null}
      {portfolios === null && !error ? <LinearProgress sx={{ mb: 0.5 }} /> : <Box sx={{ height: 4, mb: 0.5 }} />}
      {portfolios && portfolios.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No portfolios yet. Connect a broker under Setup to create one.
        </Typography>
      ) : null}
      <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "repeat(2, 1fr)", xl: "repeat(3, 1fr)" }, gap: 1.5 }}>
        {(portfolios ?? []).map((portfolio) => (
          <Card
            key={portfolio.id}
            portfolio={portfolio}
            onChange={(updated) => setPortfolios((current) => (current ?? []).map((row) => (row.id === updated.id ? updated : row)))}
          />
        ))}
      </Box>
    </AppShell>
  );
}
