import assert from "node:assert/strict";
import test from "node:test";

import { render } from "../dist/server/entry-server.js";

test("known application routes render with HTTP 200", () => {
  for (const path of ["/", "/reports/pnl", "/reports/returns", "/investments/portfolios", "/investments/trades", "/investments/positions", "/investments/positions/1", "/investments/dividends", "/investments/orders", "/data/prices", "/data/fx", "/data/reconciliation", "/setup/connections", "/setup/settings"]) {
    assert.equal(render(path).statusCode, 200, path);
  }
});

test("unknown application routes render the not-found page with HTTP 404", () => {
  const result = render("/does-not-exist");

  assert.equal(result.statusCode, 404);
  assert.match(result.html, /Page not found/);
});

test("dashboard SSR shows a loading state before requesting real report data", () => {
  const html = render("/").html;
  assert.match(html, /Loading dashboard/);
  assert.doesNotMatch(html, /Top contributors today|Open issues|Total NAV/);
});

test("returns labels lifetime cash additions and monetary returns beside NAV", () => {
  const html = render("/reports/returns?date_gte=2024-01-01").html;
  assert.match(html, /Cumulative cash additions/);
  assert.match(html, />Returns</);
  assert.match(html, /lifetime deposits minus withdrawals through each date/);
});

test("the amounts toggle is on every page and reflects the hide-amounts cookie", () => {
  for (const path of ["/", "/reports/returns", "/investments/positions/1", "/data/prices", "/setup/connections"]) {
    const shown = render(path).html;
    assert.match(shown, /aria-label="Hide amounts"/, path);
    assert.match(shown, /aria-pressed="true"[^>]*aria-label="Show amounts"/, path);

    const hidden = render(path, { hideAmounts: true }).html;
    assert.match(hidden, /aria-pressed="true"[^>]*aria-label="Hide amounts"/, path);
  }
});
