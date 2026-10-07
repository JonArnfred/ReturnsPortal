import Alert from "@mui/material/Alert";
import Button from "@mui/material/Button";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { connectIbkr, fetchConnections, queueConnectionSync, type ConnectionStatus } from "../api/client";
import AppShell from "../app/AppShell";
import { brokerLabel, type Broker } from "../app/brokers";

/** Messages for the error codes the Saxo OAuth callback redirects with. */
const authorizationErrors: Record<string, string> = {
  denied: "Saxo did not authorize the connection. Try again, and approve the access on Saxo's page.",
  missing_code: "Saxo's answer was incomplete. Start the connection again.",
  other_browser: "The login was started in another browser or has expired. Start it again from this page.",
  invalid_state: "The login link has expired or was already used. Start the connection again.",
  exchange_failed: "Saxo's login worked, but exchanging it for access failed; see the API log. Try again.",
  not_configured: "No Saxo app is configured. Set SAXO_APP_KEY and SAXO_APP_SECRET in backend/.env and restart the API.",
};

const statusChip: Record<string, { label: string; color: "success" | "warning" | "error" | "default" }> = {
  connected: { label: "Connected", color: "success" },
  expired: { label: "Token expired", color: "warning" },
  error: { label: "Last sync failed", color: "error" },
  not_configured: { label: "Not connected", color: "default" },
};

function formatTime(value: string | null | undefined) {
  return value ? value.replace("T", " ").slice(0, 16) : null;
}

export default function ConnectionsPage() {
  const [params, setParams] = useSearchParams();
  const [connections, setConnections] = useState<ConnectionStatus[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "success" | "error" | "info"; text: string } | null>(() => {
    const connected = params.get("connected");
    const error = params.get("error");
    if (connected) return { kind: "success", text: `${brokerLabel(connected)} authorized. Accounts, history, prices and FX are being pulled now; the dashboard updates once the rebuild finishes.` };
    if (error) return { kind: "error", text: authorizationErrors[error] ?? "The broker authorization failed. Start it again." };
    return null;
  });
  const reloadTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async () => {
    try {
      const payload = await fetchConnections();
      setConnections(payload.connections);
      setLoadError(null);
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : String(error));
    }
  }, []);

  useEffect(() => {
    void load();
    return () => {
      if (reloadTimer.current) clearTimeout(reloadTimer.current);
    };
  }, [load]);

  // The OAuth callback's result is read into the notice above; then it leaves the URL.
  useEffect(() => {
    if (params.has("connected") || params.has("error")) {
      const cleaned = new URLSearchParams(params);
      cleaned.delete("connected");
      cleaned.delete("error");
      cleaned.delete("connection_id");
      setParams(cleaned, { replace: true });
    }
  }, [params, setParams]);

  async function sync(connection: ConnectionStatus) {
    try {
      const queued = await queueConnectionSync(connection.id);
      setNotice({ kind: "info", text: `Sync queued for ${brokerLabel(connection.broker, "product")} (task ${queued.task_id}).` });
      if (reloadTimer.current) clearTimeout(reloadTimer.current);
      reloadTimer.current = setTimeout(() => void load(), 3000);
    } catch (error) {
      setNotice({ kind: "error", text: error instanceof Error ? error.message : String(error) });
    }
  }

  const [ibkrOpen, setIbkrOpen] = useState(false);

  async function connectedIbkr(connectionId: number, taskId: string | null) {
    setIbkrOpen(false);
    setNotice({
      kind: taskId ? "success" : "error",
      text: taskId
        ? `Interactive Brokers connected (connection ${connectionId}). The statement, prices and FX are being pulled now; the dashboard updates once the rebuild finishes.`
        : `Interactive Brokers connected (connection ${connectionId}), but the task queue is down; use Sync now once it is back.`,
    });
    await load();
  }

  const saxo = connections?.find((connection) => connection.broker === "saxo") ?? null;
  const ibkr = connections?.find((connection) => connection.broker === "ibkr") ?? null;

  return (
    <AppShell title="Connections">
      <Stack spacing={1.5} sx={{ maxWidth: 900 }}>
        {notice ? (
          <Alert severity={notice.kind} onClose={() => setNotice(null)}>
            {notice.text}
          </Alert>
        ) : null}
        {loadError ? <Alert severity="error">Could not load connections: {loadError}</Alert> : null}

        <ConnectionCard
          broker="saxo"
          connection={saxo}
          loading={connections === null && !loadError}
          connectHref="/api/connections/saxo/authorize"
          onSync={sync}
        />
        <ConnectionCard
          broker="ibkr"
          connection={ibkr}
          loading={connections === null && !loadError}
          onConnect={() => setIbkrOpen(true)}
          onSync={sync}
        />
        <IbkrConnectDialog open={ibkrOpen} reconnect={ibkr !== null} onClose={() => setIbkrOpen(false)} onConnected={connectedIbkr} />

        <Typography variant="body2" color="text.secondary">
          Connections use read-only access. Saxo authorizes through OAuth and returns to this page; Interactive Brokers
          takes a Flex Web Service token and the id of an Activity Flex Query. Credentials are stored encrypted. A sync
          pulls accounts, positions, balances and the full history into raw payloads first.
        </Typography>
      </Stack>
    </AppShell>
  );
}

function IbkrConnectDialog({
  open,
  reconnect,
  onClose,
  onConnected,
}: {
  open: boolean;
  reconnect: boolean;
  onClose: () => void;
  onConnected: (connectionId: number, taskId: string | null) => void;
}) {
  const [token, setToken] = useState("");
  const [queryId, setQueryId] = useState("");
  const [expiresOn, setExpiresOn] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ready = token.trim().length >= 8 && /^\d+$/.test(queryId.trim());

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const created = await connectIbkr({
        token: token.trim(),
        query_id: queryId.trim(),
        expires_at: expiresOn ? `${expiresOn}T23:59:59Z` : null,
      });
      setToken("");
      onConnected(created.connection_id, created.task_id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onClose={busy ? undefined : onClose} fullWidth maxWidth="sm">
      <DialogTitle>{reconnect ? "Reconnect Interactive Brokers" : "Connect Interactive Brokers"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ mt: 0.5 }}>
          <Typography variant="body2" color="text.secondary">
            In Client Portal, under Performance &amp; Reports, Flex Queries, enable the Flex Web Service and generate a
            token (up to a year). The query id is shown next to the Activity Flex Query. The token is stored encrypted and
            never shown again.
          </Typography>
          <TextField
            label="Flex Web Service token"
            type="password"
            autoComplete="off"
            value={token}
            onChange={(event) => setToken(event.target.value)}
            fullWidth
            required
          />
          <TextField
            label="Activity Flex Query id"
            value={queryId}
            onChange={(event) => setQueryId(event.target.value)}
            slotProps={{ htmlInput: { inputMode: "numeric" } }}
            sx={{ maxWidth: 240 }}
            required
          />
          <TextField
            label="Token valid until"
            type="date"
            value={expiresOn}
            onChange={(event) => setExpiresOn(event.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
            helperText="As chosen when the token was generated; a year from today when left empty."
            sx={{ maxWidth: 240 }}
          />
          {error ? <Alert severity="error">{error}</Alert> : null}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button variant="contained" onClick={() => void submit()} disabled={!ready || busy}>
          {busy ? "Connecting…" : reconnect ? "Reconnect" : "Connect"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function ConnectionCard({
  broker,
  connection,
  loading,
  connectHref,
  onConnect,
  onSync,
}: {
  broker: Broker;
  connection: ConnectionStatus | null;
  loading: boolean;
  connectHref?: string;
  onConnect?: () => void;
  onSync: (connection: ConnectionStatus) => void;
}) {
  const chip = statusChip[connection?.status ?? "not_configured"];
  const details: string[] = [];
  if (connection) {
    details.push(`${connection.environment} environment`);
    if (connection.client_name) details.push(connection.client_name);
    if (connection.base_currency) details.push(`base ${connection.base_currency}`);
    if (connection.query_id) details.push(`query ${connection.query_id}`);
    details.push(`${connection.account_count} account${connection.account_count === 1 ? "" : "s"}`);
    const finished = formatTime(connection.last_sync_finished_at);
    if (finished) details.push(`last sync ${finished}`);
    const expires = formatTime(connection.refresh_token_expires_at ?? connection.access_token_expires_at);
    if (expires) details.push(`token valid until ${expires}`);
  }

  return (
    <Paper variant="outlined" sx={{ p: 2, display: "flex", alignItems: "center", gap: 2 }}>
      <div style={{ flex: 1, minWidth: 0 }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <Typography variant="h3">{brokerLabel(broker, "product")}</Typography>
          {loading ? null : <Chip size="small" label={chip.label} color={chip.color} variant="outlined" />}
        </Stack>
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
          {loading ? "Loading…" : details.length ? details.join(" · ") : "No connection yet."}
        </Typography>
        {connection?.last_sync_error ? (
          <Typography variant="caption" sx={{ color: "error.main", display: "block", mt: 0.5 }}>
            {connection.last_sync_error}
          </Typography>
        ) : null}
      </div>
      <Button variant="outlined" disabled={!connection} onClick={() => connection && onSync(connection)}>
        Sync now
      </Button>
      {connectHref ? (
        <Button variant="contained" component="a" href={connectHref}>
          {connection ? "Reconnect" : "Connect"}
        </Button>
      ) : (
        <Button variant="contained" onClick={onConnect} disabled={!onConnect}>
          {connection ? "Reconnect" : "Connect"}
        </Button>
      )}
    </Paper>
  );
}
