import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({ server: { middlewareMode: true, hmr: false, ws: false } });
try {
  const { DashboardContent } = await server.ssrLoadModule("/src/pages/DashboardPage.tsx");
  const payload = {
    as_of: "2024-01-09", intraday: false, base_currency: "EUR", nav: "12345.67", daily_pnl: "-120",
    daily_return_pct: "-0.01", fx_effect_base: "-25.5", issue_count: 17,
    series: [{ day: "2024-01-09", nav: "12345.67" }],
    portfolios: [{ portfolio_id: 42, portfolio_name: "Actual portfolio", nav: "12345.67",
      daily_pnl: "-120", daily_return_pct: "-0.01", cumulative_return_pct: "0.15" }],
    fx_by_currency: [{ currency: "USD", effect: "-25.5" }],
    top: [{ portfolio_id: 42, position_key: "cash:USD", security_name: "Cash USD", full_ticker: "USD",
      portfolio_name: "Actual portfolio", daily_pnl_base: "5", daily_return_pct: null }],
    bottom: [], warnings: ["Another portfolio has no calculated returns and is excluded from totals."],
  };

  await test("dashboard presents API values, date, currency, issues and missing coverage", () => {
    const html = renderToStaticMarkup(createElement(DashboardContent, { data: payload }));
    for (const text of ["12,346 EUR", "-120 EUR", "-1.00", "as of 2024-01-09", ">17<",
      "Actual portfolio", "Cash USD", "excluded from totals", "No contributors available.",
      "Valuation date: 2024-01-09"]) {
      assert.ok(html.includes(text), text);
    }
    assert.doesNotMatch(html, /DKK|contributors today|Open issues/);
  });

  await test("contributors show their valuation date alongside pending daily results", () => {
    const warning = "Daily results after 2024-01-09 are pending: later dates only carry forward earlier market data.";
    const html = renderToStaticMarkup(createElement(DashboardContent, { data: {
      ...payload, warnings: [warning],
    } }));
    assert.ok(html.includes(warning));
    assert.equal(html.split("Valuation date: 2024-01-09").length - 1, 2);
  });

  await test("today's results are labelled intraday", () => {
    const html = renderToStaticMarkup(createElement(DashboardContent, { data: { ...payload, intraday: true } }));
    assert.ok(html.includes("as of 2024-01-09, intraday"));
    assert.equal(html.split("Valuation date: 2024-01-09 (intraday prices until the close)").length - 1, 2);
  });

  await test("an empty dashboard does not manufacture zero-valued investments", () => {
    const html = renderToStaticMarkup(createElement(DashboardContent, { data: {
      ...payload, as_of: null, base_currency: null, nav: null, daily_pnl: null,
      daily_return_pct: null, fx_effect_base: null, issue_count: 0,
      series: [], portfolios: [], fx_by_currency: [], top: [], bottom: [], warnings: [],
    } }));
    assert.match(html, /No combined report is available/);
    assert.match(html, /No NAV history available/);
    assert.match(html, /No portfolios connected/);
    assert.doesNotMatch(html, /0 DKK|0 EUR|Actual portfolio|Cash USD/);
  });
} finally {
  await server.close();
}
