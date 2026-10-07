import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import LinearProgress from "@mui/material/LinearProgress";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import { fetchReportingCurrency, saveReportingCurrency, type ReportingCurrencySettings } from "../api/client";
import AppShell from "../app/AppShell";

const POLL_MS = 5000;

export default function SettingsPage() {
  const [current, setCurrent] = useState<ReportingCurrencySettings | null>(null);
  const [choice, setChoice] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  async function load() {
    try {
      const loaded = await fetchReportingCurrency();
      setCurrent(loaded);
      setChoice((previous) => previous || loaded.currency);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }

  useEffect(() => {
    void load();
  }, []);

  // While portfolios are re-booked in the new currency, check back until the rebuild is done.
  useEffect(() => {
    if (!current?.pending) return;
    const timer = setTimeout(() => void load(), POLL_MS);
    return () => clearTimeout(timer);
  }, [current]);

  async function save() {
    setSaving(true);
    setNotice(null);
    try {
      const saved = await saveReportingCurrency(choice);
      setCurrent(saved);
      setError(null);
      setNotice(
        saved.task_id
          ? `Reporting currency set to ${saved.currency}. Every portfolio is being recalculated; reports show mixed currencies until it finishes.`
          : `Reporting currency set to ${saved.currency}, but the task queue is down, so nothing was recalculated yet. Start the worker and press Save again.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSaving(false);
    }
  }

  const options = current?.options ?? [];
  const selected = options.find((option) => option.code === choice);
  // Saving the same currency again re-queues a recalculation that did not run (e.g. the worker was down).
  const changed = current !== null && (choice !== current.currency || current.pending);

  return (
    <AppShell title="Settings">
      <Stack spacing={1.5} sx={{ maxWidth: 900 }}>
        {error ? (
          <Alert severity="error" onClose={() => setError(null)}>
            {error}
          </Alert>
        ) : null}
        {notice ? (
          <Alert severity="info" onClose={() => setNotice(null)}>
            {notice}
          </Alert>
        ) : null}

        <Paper variant="outlined" sx={{ p: 2 }}>
          <Stack spacing={1.5}>
            <div>
              <Typography variant="h3">Reporting currency</Typography>
              <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
                Every portfolio is booked and reported in this currency; holdings in other currencies are converted with
                ECB reference rates. Changing it recalculates everything from the stored broker data, without contacting
                the brokers.
              </Typography>
            </div>
            {current === null && !error ? <LinearProgress /> : null}
            {current ? (
              <Box sx={{ display: "flex", gap: 1.5, alignItems: "flex-start" }}>
                <TextField
                  select
                  size="small"
                  label="Currency"
                  value={choice}
                  onChange={(event) => setChoice(event.target.value)}
                  sx={{ width: 220 }}
                  helperText={current.currency === current.default_currency ? "Default from the environment" : `Default: ${current.default_currency}`}
                >
                  {options.map((option) => (
                    <MenuItem key={option.code} value={option.code} disabled={!option.allowed} title={option.reason ?? undefined}>
                      {option.code}
                    </MenuItem>
                  ))}
                </TextField>
                <Button variant="contained" sx={{ mt: 0.25 }} onClick={() => void save()} disabled={!changed || saving || selected?.allowed === false}>
                  {saving ? "Saving…" : "Save"}
                </Button>
              </Box>
            ) : null}
            {options.some((option) => !option.allowed) ? (
              <Typography variant="caption" color="text.secondary">
                {options.find((option) => !option.allowed)?.reason}. The other currencies are disabled.
              </Typography>
            ) : null}
          </Stack>
        </Paper>

        {current && current.portfolios.length > 0 ? (
          <Paper variant="outlined" sx={{ p: 2 }}>
            <Stack spacing={1}>
              <Box sx={{ display: "flex", gap: 1, alignItems: "center" }}>
                <Typography variant="h3">Portfolios</Typography>
                <Chip
                  size="small"
                  variant="outlined"
                  color={current.pending ? "warning" : "success"}
                  label={current.pending ? "Recalculating…" : `All in ${current.currency}`}
                />
              </Box>
              {current.pending ? <LinearProgress /> : null}
              {current.portfolios.map((portfolio) => (
                <Typography key={portfolio.portfolio_id} variant="body2" color="text.secondary">
                  {portfolio.portfolio_name}: booked in {portfolio.booked_currency}
                  {portfolio.built_currency ? `, reports built in ${portfolio.built_currency}` : ", reports not built yet"}
                </Typography>
              ))}
            </Stack>
          </Paper>
        ) : null}
      </Stack>
    </AppShell>
  );
}
