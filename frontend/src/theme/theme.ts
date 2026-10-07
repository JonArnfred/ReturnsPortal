import { createTheme } from "@mui/material/styles";

/**
 * Light theme. Dense by default: the app is mostly tables and charts.
 * Tokens follow the data-viz palette (blue accent, neutral surfaces).
 */
export const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#2a78d6", dark: "#1c5cab", light: "#6da7ec" },
    secondary: { main: "#1baf7a" },
    success: { main: "#0f8a4b" },
    error: { main: "#d2392f" },
    warning: { main: "#c98500" },
    background: { default: "#f4f5f7", paper: "#ffffff" },
    text: { primary: "#17202a", secondary: "#5a6570" },
    divider: "#e1e5ea",
  },
  shape: { borderRadius: 6 },
  typography: {
    fontFamily: 'Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    fontSize: 13,
    h1: { fontSize: "1.5rem", fontWeight: 600 },
    h2: { fontSize: "1.15rem", fontWeight: 600 },
    h3: { fontSize: "1rem", fontWeight: 600 },
    subtitle2: { fontWeight: 600 },
    body2: { fontSize: "0.8125rem" },
    caption: { fontSize: "0.72rem" },
  },
  components: {
    MuiButton: {
      defaultProps: { size: "small", disableElevation: true },
      styleOverrides: { root: { textTransform: "none", fontWeight: 600 } },
    },
    MuiTextField: { defaultProps: { size: "small" } },
    MuiFormControl: { defaultProps: { size: "small" } },
    MuiTableCell: {
      styleOverrides: {
        root: { padding: "5px 8px", fontSize: "0.78rem", lineHeight: 1.3, borderBottom: "1px solid #eceff2" },
        head: { fontWeight: 600, color: "#5a6570", background: "#fafbfc", whiteSpace: "nowrap" },
      },
    },
    MuiTooltip: { defaultProps: { arrow: true } },
    MuiPaper: { styleOverrides: { root: { backgroundImage: "none" } } },
  },
});
