import Box from "@mui/material/Box";
import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import type { ReactNode } from "react";
import { BREADCRUMB_HEIGHT, TOP_BAR_HEIGHT } from "../app/AppShell";

/** Bottom padding of the page content in `AppShell`, in pixels. */
const CONTENT_BOTTOM_PADDING = 16;

type SplitViewProps = {
  /** Master pane, typically a `DataTable` in `fill` mode. */
  left: ReactNode;
  /** Detail pane. `null` shows `placeholder` instead. */
  right: ReactNode;
  /** Shown in the right pane while nothing is selected. */
  placeholder?: ReactNode;
  /** Width of the left pane in pixels on wide screens; the right pane takes the rest. */
  leftWidth?: number;
  /** Fix the right pane instead and let the left pane take the rest. Wins over `leftWidth`. */
  rightWidth?: number;
  /** Height of everything above the split on the page, so it can fill the rest of the viewport. */
  offsetTop?: number;
};

/**
 * Master-detail layout: two panes side by side that together fill the remaining viewport
 * height, each scrolling on its own. Below the `md` breakpoint they stack, and the page scrolls
 * instead. Children are expected to be flex-friendly (`minHeight: 0`, `overflow: auto`).
 */
export default function SplitView({
  left,
  right,
  placeholder = "Select a row to see details.",
  leftWidth = 480,
  rightWidth,
  offsetTop = 0,
}: SplitViewProps) {
  const height = `calc(100vh - ${TOP_BAR_HEIGHT + BREADCRUMB_HEIGHT + CONTENT_BOTTOM_PADDING + offsetTop}px)`;
  const fixed = (width: number) => ({
    flex: { xs: "0 0 auto", md: `0 0 ${width}px` },
    maxWidth: { xs: "none", md: width },
  });
  const flexible = { flex: "1 1 auto" };
  const pane = { minWidth: 0, minHeight: 0, display: "flex", flexDirection: "column" } as const;
  return (
    <Box
      sx={{
        display: "flex",
        gap: 1.5,
        alignItems: "stretch",
        minWidth: 0,
        flexDirection: { xs: "column", md: "row" },
        height: { xs: "auto", md: height },
      }}
    >
      <Box sx={{ ...pane, ...(rightWidth === undefined ? fixed(leftWidth) : flexible) }}>{left}</Box>
      <Box sx={{ ...pane, ...(rightWidth === undefined ? flexible : fixed(rightWidth)) }}>
        {right ?? (
          <Paper variant="outlined" sx={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", p: 4, minHeight: 160 }}>
            <Typography variant="body2" color="text.secondary">
              {placeholder}
            </Typography>
          </Paper>
        )}
      </Box>
    </Box>
  );
}
