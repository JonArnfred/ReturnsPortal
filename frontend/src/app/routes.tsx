import type { RouteObject } from "react-router-dom";
import ConnectionsPage from "../pages/ConnectionsPage";
import DashboardPage from "../pages/DashboardPage";
import DividendsPage from "../pages/DividendsPage";
import FxPage from "../pages/FxPage";
import OrdersPage from "../pages/OrdersPage";
import PnlPage from "../pages/PnlPage";
import PortfoliosPage from "../pages/PortfoliosPage";
import PositionDetailPage from "../pages/PositionDetailPage";
import PositionsPage from "../pages/PositionsPage";
import PricesPage from "../pages/PricesPage";
import ReconciliationPage from "../pages/ReconciliationPage";
import ReturnsPage from "../pages/ReturnsPage";
import SettingsPage from "../pages/SettingsPage";
import TradesPage from "../pages/TradesPage";

export function createAppRoutes(): RouteObject[] {
  return [
    { path: "/", element: <DashboardPage /> },
    { path: "/reports/pnl", element: <PnlPage /> },
    { path: "/reports/returns", element: <ReturnsPage /> },
    { path: "/investments/portfolios", element: <PortfoliosPage /> },
    { path: "/investments/trades", element: <TradesPage /> },
    { path: "/investments/positions", element: <PositionsPage /> },
    { path: "/investments/positions/:positionId", element: <PositionDetailPage /> },
    { path: "/investments/dividends", element: <DividendsPage /> },
    { path: "/investments/orders", element: <OrdersPage /> },
    { path: "/data/prices", element: <PricesPage /> },
    { path: "/data/fx", element: <FxPage /> },
    { path: "/data/reconciliation", element: <ReconciliationPage /> },
    { path: "/setup/connections", element: <ConnectionsPage /> },
    { path: "/setup/settings", element: <SettingsPage /> },
  ];
}
