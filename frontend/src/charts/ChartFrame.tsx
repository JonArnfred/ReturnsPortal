import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Highcharts from "highcharts";
import { HighchartsReact } from "highcharts-react-official";
import { useEffect, useState } from "react";
import { applyHighchartsTheme } from "./theme";

/** Milliseconds since the epoch for an ISO date, at UTC midnight. */
export function toTimestamp(date: string) {
  return Date.UTC(Number(date.slice(0, 4)), Number(date.slice(5, 7)) - 1, Number(date.slice(8, 10)));
}

/**
 * Highcharts needs a window, so the server renders a fixed-height placeholder and the client
 * draws the chart after mount. Both first renders are identical, which keeps hydration clean.
 */
export default function ChartFrame({ options, height, empty }: { options: Highcharts.Options; height: number; empty: boolean }) {
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    applyHighchartsTheme();
    setMounted(true);
  }, []);

  if (empty) {
    return (
      <Typography variant="body2" color="text.secondary">
        No data.
      </Typography>
    );
  }
  return (
    <Box sx={{ height, width: "100%" }}>
      {mounted ? <HighchartsReact highcharts={Highcharts} options={options} /> : null}
    </Box>
  );
}
