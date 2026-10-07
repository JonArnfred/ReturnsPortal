import type Highcharts from "highcharts";
import { useMemo } from "react";
import { usePrivacy } from "../app/privacy";
import ChartFrame, { toTimestamp } from "./ChartFrame";
import { NEGATIVE_COLOR, POSITIVE_COLOR, SERIES_COLORS } from "./theme";

export type PricePoint = { date: string; close: number };
export type TradeMark = { date: string; price: number; quantity: number; kind: "buy" | "sell" };
export type ValuePoint = { date: string; value: number; quantity: number };

function marks(trades: TradeMark[], kind: "buy" | "sell"): Highcharts.PointOptionsObject[] {
  return trades
    .filter((trade) => trade.kind === kind)
    .map((trade) => ({ x: toTimestamp(trade.date), y: trade.price, custom: { quantity: Math.abs(trade.quantity) } }));
}

/** Daily close with a marker per trade: green triangles for buys, red for sells. The traded quantity leaves the tooltip while amounts are hidden. */
export function PriceTradesChart({ prices, trades, currency, height = 300 }: { prices: PricePoint[]; trades: TradeMark[]; currency: string; height?: number }) {
  const { hidden } = usePrivacy();
  const options = useMemo<Highcharts.Options>(
    () => ({
      chart: { height },
      legend: { enabled: false },
      xAxis: { type: "datetime" },
      yAxis: { labels: { format: "{value:,.2f}" } },
      tooltip: { shared: false, valueDecimals: 2, valueSuffix: ` ${currency}` },
      plotOptions: {
        scatter: {
          marker: { enabled: true, radius: 6, lineWidth: 0 },
          tooltip: { headerFormat: "<b>{point.key}</b><br/>", pointFormat: hidden ? "{series.name} at {point.y}" : "{series.name} {point.custom.quantity} at {point.y}" },
        },
      },
      series: [
        { type: "line", name: "Close", data: prices.map((point) => [toTimestamp(point.date), point.close]), zIndex: 1 },
        { type: "scatter", name: "Bought", color: POSITIVE_COLOR, marker: { symbol: "triangle" }, data: marks(trades, "buy"), zIndex: 2 },
        { type: "scatter", name: "Sold", color: NEGATIVE_COLOR, marker: { symbol: "triangle-down" }, data: marks(trades, "sell"), zIndex: 2 },
      ],
    }),
    [prices, trades, currency, height, hidden],
  );
  return <ChartFrame options={options} height={height} empty={prices.length === 0} />;
}

/**
 * Market value on the left axis and the number of shares held, stepped, on the right axis. Both reveal
 * holding size, so the axis labels and the tooltip go while amounts are hidden; the shape stays.
 */
export function MarketValueChart({ points, currency, height = 300 }: { points: ValuePoint[]; currency: string; height?: number }) {
  const { hidden } = usePrivacy();
  const options = useMemo<Highcharts.Options>(
    () => ({
      chart: { height },
      legend: { enabled: true },
      xAxis: { type: "datetime" },
      yAxis: [
        { title: { text: currency }, labels: { enabled: !hidden, format: "{value:,.0f}" } },
        { title: { text: "Shares" }, labels: { enabled: !hidden, format: "{value:,.0f}" }, opposite: true, gridLineWidth: 0 },
      ],
      tooltip: { enabled: !hidden, shared: true },
      series: [
        { type: "line", name: "Market value", data: points.map((point) => [toTimestamp(point.date), point.value]), tooltip: { valueDecimals: 0, valueSuffix: ` ${currency}` } },
        {
          type: "line",
          name: "Shares",
          yAxis: 1,
          step: "left",
          dashStyle: "ShortDash",
          color: SERIES_COLORS[1],
          lineWidth: 1.5,
          data: points.map((point) => [toTimestamp(point.date), point.quantity]),
          tooltip: { valueDecimals: 0 },
        },
      ],
    }),
    [points, currency, height, hidden],
  );
  return <ChartFrame options={options} height={height} empty={points.length === 0} />;
}
