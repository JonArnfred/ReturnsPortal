import type Highcharts from "highcharts";
import { useMemo } from "react";
import { usePrivacy } from "../app/privacy";
import ChartFrame, { toTimestamp } from "./ChartFrame";

export type SeriesPoint = { date: string; value: number };

export type TimeSeries = {
  name: string;
  points: SeriesPoint[];
  color?: string;
  type?: "line" | "area";
};

type TimeSeriesChartProps = {
  series: TimeSeries[];
  height?: number;
  /** Decimals shown on the axis and in the tooltip. */
  decimals?: number;
  /** Suffix for values, e.g. " %" or " EUR". */
  suffix?: string;
  /** Show the legend; defaults to on when there is more than one series. */
  legend?: boolean;
  /** Value of the y-axis to emphasize with a plot line, e.g. 0 or 100. */
  baseline?: number;
  /** Colour fills below the baseline with the negative colour (drawdown style). */
  negativeColor?: string;
  /**
   * Underwater (drawdown) style: the y-axis tops out at 0, the area fills from 0 down to the
   * series with a stronger fill and a thin edge line.
   */
  drawdown?: boolean;
  /** The values reveal holding size (NAV, market value); axis labels and tooltip go while amounts are hidden. */
  sensitive?: boolean;
};

/** Line or area chart of one or more dated series; see `ChartFrame` for the SSR handling. */
export default function TimeSeriesChart({
  series,
  height = 240,
  decimals = 2,
  suffix = "",
  legend,
  baseline,
  negativeColor,
  drawdown = false,
  sensitive = false,
}: TimeSeriesChartProps) {
  const { hidden } = usePrivacy();
  const masked = sensitive && hidden;
  const options = useMemo<Highcharts.Options>(
    () => ({
      chart: { height, type: "line" },
      legend: { enabled: legend ?? series.length > 1 },
      xAxis: { type: "datetime" },
      yAxis: {
        labels: { enabled: !masked, format: `{value:,.${decimals}f}${suffix}` },
        ...(drawdown ? { max: 0, maxPadding: 0, softMin: -1, endOnTick: false } : {}),
        plotLines:
          baseline === undefined ? [] : [{ value: baseline, color: "#9aa5b1", width: 1, zIndex: 2 }],
      },
      tooltip: { enabled: !masked, valueDecimals: decimals, valueSuffix: suffix },
      series: series.map((entry) => ({
        type: entry.type ?? "line",
        name: entry.name,
        color: entry.color,
        negativeColor,
        threshold: negativeColor === undefined ? undefined : (baseline ?? 0),
        ...(drawdown ? { threshold: 0, fillOpacity: 0.45, lineWidth: 1 } : {}),
        data: entry.points.map((point) => [toTimestamp(point.date), point.value]),
      })),
    }),
    [series, height, decimals, suffix, legend, baseline, negativeColor, drawdown, masked],
  );

  return <ChartFrame options={options} height={height} empty={series.every((entry) => entry.points.length === 0)} />;
}
