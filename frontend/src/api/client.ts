import type { components } from "./schema";

export type ConnectionStatus = components["schemas"]["ConnectionStatus"];
export type ConnectionsResponse = components["schemas"]["ConnectionsResponse"];
export type SyncQueuedResponse = components["schemas"]["SyncQueuedResponse"];
export type IbkrConnectRequest = components["schemas"]["IbkrConnectRequest"];
export type ConnectionCreatedResponse = components["schemas"]["ConnectionCreatedResponse"];
export type TransactionRow = components["schemas"]["TransactionRow"];
export type TransactionsResponse = components["schemas"]["TransactionsResponse"];
export type PositionRow = components["schemas"]["PositionRow"];
export type PositionsResponse = components["schemas"]["PositionsResponse"];
export type PositionDetail = components["schemas"]["PositionDetail"];
export type PositionTrade = components["schemas"]["PositionTrade"];
export type ReturnsBlock = components["schemas"]["ReturnsBlock"];
export type PortfolioCard = components["schemas"]["PortfolioCard"];
export type OrderRow = components["schemas"]["OrderRow"];
export type Preference = components["schemas"]["Preference"];
export type PriceStatusRow = components["schemas"]["PriceStatusRow"];
export type PriceStatusResponse = components["schemas"]["PriceStatusResponse"];
export type DailyPriceRow = components["schemas"]["DailyPriceRow"];
export type DailyPricesResponse = components["schemas"]["DailyPricesResponse"];
export type PreferencesResponse = components["schemas"]["PreferencesResponse"];
export type OrdersResponse = components["schemas"]["OrdersResponse"];
export type PortfoliosResponse = components["schemas"]["PortfoliosResponse"];
export type PageMeta = components["schemas"]["PageMeta"];
export type PnlRow = components["schemas"]["PnlRow"];
export type PnlResponse = components["schemas"]["PnlResponse"];
export type PortfolioDay = components["schemas"]["PortfolioDay"];
export type PortfolioDaysResponse = components["schemas"]["PortfolioDaysResponse"];
export type SeriesSummary = components["schemas"]["SeriesSummary"];
export type IssueRow = components["schemas"]["IssueRow"];
export type IssuesResponse = components["schemas"]["IssuesResponse"];
export type FxStatusRow = components["schemas"]["FxStatusRow"];
export type FxStatusResponse = components["schemas"]["FxStatusResponse"];
export type FxRateRow = components["schemas"]["FxRateRow"];
export type FxSeriesResponse = components["schemas"]["FxSeriesResponse"];
export type RebuildResponse = components["schemas"]["RebuildResponse"];
export type DashboardResponse = components["schemas"]["DashboardResponse"];
export type ReportingCurrencySettings = components["schemas"]["ReportingCurrencySettings"];

export function fetchDashboard() {
  return fetchJson<DashboardResponse>("/api/reports/dashboard", { cache: "no-store" });
}

/** The API answers errors as `{status_code, error, detail, request_id}`; surface the `detail`. */
async function responseError(response: Response): Promise<Error> {
  const text = await response.text();
  try {
    const parsed = JSON.parse(text) as { detail?: unknown };
    if (typeof parsed.detail === "string" && parsed.detail) return new Error(parsed.detail);
  } catch {
    // Not JSON (e.g. a proxy error page): fall through to the raw text.
  }
  return new Error(text || `Request failed with HTTP ${response.status}`);
}

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) throw await responseError(response);
  return response.json() as Promise<T>;
}

export function fetchConnections() {
  return fetchJson<ConnectionsResponse>("/api/connections", { cache: "no-store" });
}

export function queueConnectionSync(connectionId: number) {
  return fetchJson<SyncQueuedResponse>(`/api/connections/${connectionId}/sync`, { method: "POST" });
}

export function connectIbkr(payload: IbkrConnectRequest) {
  return fetchJson<ConnectionCreatedResponse>("/api/connections/ibkr", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function fetchTransactions(query: URLSearchParams) {
  return fetchJson<TransactionsResponse>(`/api/ledger/transactions?${query.toString()}`, { cache: "no-store" });
}

export function fetchPositions() {
  return fetchJson<PositionsResponse>("/api/positions", { cache: "no-store" });
}

export function fetchPositionDetail(positionId: number) {
  return fetchJson<PositionDetail>(`/api/positions/${positionId}`, { cache: "no-store" });
}

export function fetchPortfolios() {
  return fetchJson<PortfoliosResponse>("/api/portfolios", { cache: "no-store" });
}

export function fetchOrders() {
  return fetchJson<OrdersResponse>("/api/orders", { cache: "no-store" });
}

export function fetchPriceStatus() {
  return fetchJson<PriceStatusResponse>("/api/prices/status", { cache: "no-store" });
}

export function fetchDailyPrices(securityId: number) {
  return fetchJson<DailyPricesResponse>(`/api/prices?security_id=${securityId}`, { cache: "no-store" });
}

export function fetchPreferences() {
  return fetchJson<PreferencesResponse>("/api/preferences", { cache: "no-store" });
}

export function savePreference(key: string, value: Record<string, string>) {
  return fetchJson<Preference>(`/api/preferences/${encodeURIComponent(key)}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ value }),
  });
}

export async function deletePreference(key: string) {
  const response = await fetch(`/api/preferences/${encodeURIComponent(key)}`, { method: "DELETE" });
  if (!response.ok && response.status !== 404) throw await responseError(response);
}

export function updatePortfolio(portfolioId: number, changes: { display_name?: string | null; reporting_start_date?: string | null }) {
  return fetchJson<PortfolioCard>(`/api/portfolios/${portfolioId}`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(changes),
  });
}

export function fetchPnlRows(query: URLSearchParams) {
  return fetchJson<PnlResponse>(`/api/reports/pnl?${query.toString()}`, { cache: "no-store" });
}

export function fetchPortfolioDays(portfolioId: number | null, query: { date_gte?: string; date_lte?: string } = {}) {
  const params = new URLSearchParams();
  if (portfolioId) params.set("portfolio_id", String(portfolioId));
  if (query.date_gte) params.set("date_gte", query.date_gte);
  if (query.date_lte) params.set("date_lte", query.date_lte);
  const suffix = params.toString();
  return fetchJson<PortfolioDaysResponse>(`/api/reports/portfolio-days${suffix ? `?${suffix}` : ""}`, { cache: "no-store" });
}

export function fetchReconciliationIssues() {
  return fetchJson<IssuesResponse>("/api/reconciliation/issues", { cache: "no-store" });
}

export function fetchFxStatus() {
  return fetchJson<FxStatusResponse>("/api/fx/status", { cache: "no-store" });
}

export function fetchFxRates(currency: string, base?: string) {
  const baseParam = base ? `&base_currency=${encodeURIComponent(base)}` : "";
  return fetchJson<FxSeriesResponse>(`/api/fx?currency=${encodeURIComponent(currency)}${baseParam}`, { cache: "no-store" });
}

export function fetchReportingCurrency() {
  return fetchJson<ReportingCurrencySettings>("/api/settings/reporting-currency", { cache: "no-store" });
}

export function saveReportingCurrency(currency: string) {
  return fetchJson<ReportingCurrencySettings>("/api/settings/reporting-currency", {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ currency }),
  });
}

export function rebuildPnl() {
  return fetchJson<RebuildResponse>("/api/reports/rebuild", { method: "POST", cache: "no-store" });
}
