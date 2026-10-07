import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import type { TransactionRow } from "../api/client";
import { DualMoney, Money, Quantity, SecurityCell } from "../components/cells";
import { formatNumber, toNumber } from "../components/format";
import type { Column } from "../components/DataTable";
import LedgerPage from "./LedgerPage";
function TradeTypeChip({ quantity }: { quantity: number | null }) {
  if (quantity === null) return <>-</>;
  return <Chip size="small" label={quantity >= 0 ? "Buy" : "Sell"} color={quantity >= 0 ? "success" : "error"} variant="outlined" />;
}

const columns: Column<TransactionRow>[] = [
  { key: "date", header: "Trade date", sortKey: "trade_date", noWrap: true, render: (row) => row.trade_date },
  { key: "value_date", header: "Value date", noWrap: true, render: (row) => row.value_date ?? "-" },
  { key: "portfolio", header: "Portfolio", sortKey: "portfolio_name", render: (row) => row.portfolio_name },
  { key: "account", header: "Account", noWrap: true, render: (row) => row.account_label ?? "-" },
  { key: "security", header: "Security", sortKey: "security_name", render: (row) => <SecurityCell name={row.security_name ?? "-"} fullTicker={row.full_ticker ?? ""} /> },
  {
    key: "trade_type",
    header: "Trade type",
    align: "center",
    render: (row) =>
      row.kind === "corporate_action" ? (
        <Chip size="small" label="Corp. action" variant="outlined" />
      ) : (
        <TradeTypeChip quantity={toNumber(row.quantity)} />
      ),
  },
  {
    key: "booking",
    header: "Booking",
    align: "center",
    render: (row) =>
      row.provisional ? (
        <Tooltip title="Executed at the broker but not booked yet. The booked trade replaces this row, with its commission.">
          <Chip size="small" label="Executed" color="warning" variant="outlined" />
        </Tooltip>
      ) : (
        <Chip size="small" label="Booked" variant="outlined" />
      ),
  },
  { key: "quantity", header: "Quantity", align: "right", sortKey: "quantity", render: (row) => <Quantity value={toNumber(row.quantity)} /> },
  { key: "price", header: "Price", align: "right", render: (row) => <Money value={toNumber(row.price)} currency={row.currency} digits={3} /> },
  {
    key: "amount",
    header: "Amount",
    align: "right",
    sortKey: "amount_base",
    render: (row) => <DualMoney base={toNumber(row.amount_base)} baseCurrency={row.base_currency} local={toNumber(row.amount_local)} localCurrency={row.currency} digits={2} />,
  },
  { key: "fx", header: "FX rate", align: "right", render: (row) => formatNumber(toNumber(row.fx_rate_base), 4) },
];

export default function TradesPage() {
  return <LedgerPage title="Trades" kinds="trade,corporate_action" columns={columns} filters={{ portfolio: true, account: true, tradeType: true }} />;
}
