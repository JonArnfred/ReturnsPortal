import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import FilterListIcon from "@mui/icons-material/FilterList";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Paper from "@mui/material/Paper";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { useState, type ReactNode } from "react";

const FILTER_PANEL_WIDTH = 220;

type FilterPanelProps = {
  children: ReactNode;
  /** Back to the page's default: the saved one when it exists, else the built-in one. */
  onReset: () => void;
  /** Store the filters as they are now as the page's default. */
  onSaveDefault?: () => void;
  savedDefault?: { exists: boolean; busy?: boolean; error?: string | null; onClear: () => void };
};

/**
 * Collapsible filter sidebar for table pages. Filter values are owned by the page and apply as
 * they change; this component only provides the frame, the collapse toggle, and the action row.
 */
export default function FilterPanel({ children, onReset, onSaveDefault, savedDefault }: FilterPanelProps) {
  const [open, setOpen] = useState(true);

  if (!open) {
    return (
      <Paper variant="outlined" sx={{ width: 40, flexShrink: 0, display: "flex", justifyContent: "center", pt: 0.5, alignSelf: "flex-start" }}>
        <Tooltip title="Show filters" placement="right">
          <IconButton size="small" onClick={() => setOpen(true)} aria-label="Show filters">
            <FilterListIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Paper>
    );
  }

  return (
    <Paper
      variant="outlined"
      sx={{ width: FILTER_PANEL_WIDTH, flexShrink: 0, display: "flex", flexDirection: "column", alignSelf: "flex-start" }}
    >
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "space-between", pl: 1.5, pr: 0.5, py: 0.5 }}>
        <Typography variant="subtitle2">Filters</Typography>
        <IconButton size="small" onClick={() => setOpen(false)} aria-label="Hide filters">
          <ChevronLeftIcon fontSize="small" />
        </IconButton>
      </Box>
      <Stack spacing={1.5} sx={{ px: 1.5, py: 1 }}>
        {children}
      </Stack>
      <Box sx={{ display: "flex", gap: 0.75, px: 1.5, py: 1, borderTop: "1px solid", borderColor: "divider" }}>
        <Tooltip title={savedDefault?.exists ? "Back to your saved default" : "Back to the built-in default"}>
          <Button variant="outlined" color="inherit" onClick={onReset}>
            Reset
          </Button>
        </Tooltip>
        {onSaveDefault ? (
          <Tooltip title="Save the current filters as this page's default">
            <span style={{ marginLeft: "auto" }}>
              <Button variant="contained" disabled={savedDefault?.busy} onClick={onSaveDefault}>
                Default
              </Button>
            </span>
          </Tooltip>
        ) : null}
      </Box>
      {savedDefault?.exists ? (
        <Box sx={{ px: 1.5, pb: 1 }}>
          <Tooltip title="Forget the saved default and go back to the built-in one">
            <span>
              <Button size="small" color="inherit" disabled={savedDefault.busy} onClick={savedDefault.onClear} sx={{ px: 0.5, minWidth: 0 }}>
                Clear saved default
              </Button>
            </span>
          </Tooltip>
        </Box>
      ) : null}
      {savedDefault?.error ? (
        <Typography variant="caption" color="error" sx={{ px: 1.5, pb: 1 }}>
          {savedDefault.error}
        </Typography>
      ) : null}
    </Paper>
  );
}

export function FilterField({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box>
      <Typography variant="caption" sx={{ display: "block", mb: 0.5, color: "text.secondary", fontWeight: 600 }}>
        {label}
      </Typography>
      {children}
    </Box>
  );
}
