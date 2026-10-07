import Chip from "@mui/material/Chip";
import type { TransactionRow } from "../api/client";
import { DualMoney, SecurityCell } from "../components/cells";
import type { Column } from "../components/DataTable";
import { formatNumber, toNumber } from "../components/format";
import LedgerPage from "./LedgerPage";
const kindLabel: Record<string, string> = { dividend: "Dividend", withholding_tax: "Withholding tax" };

const columns: Column<TransactionRow>[] = [
  { key: "date", header: "Booking date", sortKey: "trade_date", noWrap: true, render: (row) => row.trade_date },
  { key: "value_date", header: "Value date", noWrap: true, render: (row) => row.value_date ?? "-" },
  { key: "portfolio", header: "Portfolio", sortKey: "portfolio_name", render: (row) => row.portfolio_name },
  { key: "account", header: "Account", noWrap: true, render: (row) => row.account_label ?? "-" },
  { key: "security", header: "Security", sortKey: "security_name", render: (row) => <SecurityCell name={row.security_name ?? "-"} fullTicker={row.full_ticker ?? ""} /> },
  {
    key: "kind",
    header: "Type",
    sortKey: "kind",
    render: (row) => <Chip size="small" label={kindLabel[row.kind] ?? row.kind} color={row.kind === "dividend" ? "success" : "default"} variant="outlined" />,
  },
  {
    key: "amount",
    header: "Amount",
    align: "right",
    sortKey: "amount_base",
    render: (row) => <DualMoney base={toNumber(row.amount_base)} baseCurrency={row.base_currency} local={toNumber(row.amount_local)} localCurrency={row.currency} digits={2} />,
  },
  { key: "fx", header: "FX rate", align: "right", render: (row) => formatNumber(toNumber(row.fx_rate_base), 4) },
  { key: "description", header: "Description", render: (row) => row.description ?? "-" },
];

export default function DividendsPage() {
  return <LedgerPage title="Dividends" kinds="dividend,withholding_tax" columns={columns} />;
}
