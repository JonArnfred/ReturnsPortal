import type { SvgIconComponent } from "@mui/icons-material";
import AccountBalanceOutlinedIcon from "@mui/icons-material/AccountBalanceOutlined";
import CableOutlinedIcon from "@mui/icons-material/CableOutlined";
import CurrencyExchangeOutlinedIcon from "@mui/icons-material/CurrencyExchangeOutlined";
import DashboardOutlinedIcon from "@mui/icons-material/DashboardOutlined";
import FactCheckOutlinedIcon from "@mui/icons-material/FactCheckOutlined";
import ListAltOutlinedIcon from "@mui/icons-material/ListAltOutlined";
import PaymentsOutlinedIcon from "@mui/icons-material/PaymentsOutlined";
import PriceChangeOutlinedIcon from "@mui/icons-material/PriceChangeOutlined";
import ReceiptLongOutlinedIcon from "@mui/icons-material/ReceiptLongOutlined";
import SettingsOutlinedIcon from "@mui/icons-material/SettingsOutlined";
import ShowChartOutlinedIcon from "@mui/icons-material/ShowChartOutlined";
import TableChartOutlinedIcon from "@mui/icons-material/TableChartOutlined";
import WorkOutlineOutlinedIcon from "@mui/icons-material/WorkOutlineOutlined";

export type NavItem = {
  label: string;
  path: string;
  icon: SvgIconComponent;
};

export type NavSection = {
  label: string;
  items: NavItem[];
};

/**
 * Every page grouped by area. The left rail shows the areas as sections and the top bar shows the
 * same areas as menus, so the two always carry the same titles. An area whose only page shares its
 * name (Dashboard) is a plain entry in both: no caption in the rail, no dropdown in the top bar.
 */
export const railSections: NavSection[] = [
  {
    label: "Dashboard",
    items: [{ label: "Dashboard", path: "/", icon: DashboardOutlinedIcon }],
  },
  {
    label: "Reports",
    items: [
      { label: "PnL", path: "/reports/pnl", icon: TableChartOutlinedIcon },
      { label: "Returns", path: "/reports/returns", icon: ShowChartOutlinedIcon },
    ],
  },
  {
    label: "Investments",
    items: [
      { label: "Portfolios", path: "/investments/portfolios", icon: AccountBalanceOutlinedIcon },
      { label: "Trades", path: "/investments/trades", icon: ReceiptLongOutlinedIcon },
      { label: "Positions", path: "/investments/positions", icon: WorkOutlineOutlinedIcon },
      { label: "Dividends", path: "/investments/dividends", icon: PaymentsOutlinedIcon },
      { label: "Orders", path: "/investments/orders", icon: ListAltOutlinedIcon },
    ],
  },
  {
    label: "Data",
    items: [
      { label: "Prices", path: "/data/prices", icon: PriceChangeOutlinedIcon },
      { label: "FX rates", path: "/data/fx", icon: CurrencyExchangeOutlinedIcon },
      { label: "Reconcile", path: "/data/reconciliation", icon: FactCheckOutlinedIcon },
    ],
  },
  {
    label: "Setup",
    items: [
      { label: "Connections", path: "/setup/connections", icon: CableOutlinedIcon },
      { label: "Settings", path: "/setup/settings", icon: SettingsOutlinedIcon },
    ],
  },
];

export function findNavItem(pathname: string): { section: NavSection; item: NavItem } | null {
  for (const section of railSections) {
    for (const item of section.items) {
      if (item.path === pathname) return { section, item };
    }
  }
  return null;
}
