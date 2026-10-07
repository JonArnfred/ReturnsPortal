import Highcharts from "highcharts";

/**
 * Shared Highcharts look, aligned with the MUI theme and the data-viz palette: thin marks,
 * hairline gridlines, text in text tokens, no credits, legend only when a chart opts in.
 */
export const SERIES_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
export const NEGATIVE_COLOR = "#d2392f";
export const POSITIVE_COLOR = "#0f8a4b";

let applied = false;

export function applyHighchartsTheme() {
  if (applied) return;
  applied = true;
  Highcharts.setOptions({
    colors: SERIES_COLORS,
    chart: {
      backgroundColor: "transparent",
      style: { fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif', fontSize: "12px" },
      spacing: [8, 8, 8, 8],
      animation: false,
      // Click and drag across the plot to zoom into a date range; "Reset zoom" appears top right.
      zooming: {
        type: "x",
        resetButton: {
          position: { align: "right", verticalAlign: "top", x: -4, y: 4 },
          theme: {
            fill: "#ffffff",
            stroke: "#c5ccd4",
            r: 4,
            style: { color: "#17202a", fontSize: "11px", fontWeight: "500" },
            states: { hover: { fill: "#f1f4f7" } },
          },
        },
      },
    },
    title: { text: undefined },
    credits: { enabled: false },
    accessibility: { enabled: false },
    legend: { enabled: false, itemStyle: { fontWeight: "500", color: "#17202a" } },
    xAxis: {
      lineColor: "#e1e5ea",
      tickColor: "#e1e5ea",
      gridLineWidth: 0,
      labels: { style: { color: "#5a6570", fontSize: "11px" } },
      crosshair: { color: "#9aa5b1", width: 1 },
    },
    yAxis: {
      title: { text: undefined },
      gridLineColor: "#eceff2",
      gridLineWidth: 1,
      labels: { style: { color: "#5a6570", fontSize: "11px" } },
    },
    tooltip: {
      backgroundColor: "#ffffff",
      borderColor: "#e1e5ea",
      borderRadius: 6,
      shadow: false,
      style: { color: "#17202a", fontSize: "12px" },
      xDateFormat: "%Y-%m-%d",
      shared: true,
    },
    plotOptions: {
      series: { animation: false, marker: { enabled: false, radius: 3, lineWidth: 2, lineColor: "#ffffff" }, states: { hover: { lineWidthPlus: 0 } } },
      line: { lineWidth: 2 },
      area: { lineWidth: 2, fillOpacity: 0.15 },
    },
    time: { timezone: "UTC" },
  });
}
