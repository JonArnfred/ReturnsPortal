import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";

export default function StatTile({ label, value, hint }: { label: string; value: ReactNode; hint?: ReactNode }) {
  return (
    <Paper variant="outlined" sx={{ px: 2, py: 1.5, minWidth: 0 }}>
      <Typography variant="caption" sx={{ color: "text.secondary", fontWeight: 600, display: "block" }}>
        {label}
      </Typography>
      <Typography component="div" sx={{ fontSize: "1.35rem", fontWeight: 600, fontVariantNumeric: "tabular-nums", lineHeight: 1.25 }}>
        {value}
      </Typography>
      {hint ? (
        <Typography variant="caption" sx={{ color: "text.secondary" }}>
          {hint}
        </Typography>
      ) : null}
    </Paper>
  );
}
