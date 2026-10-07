import ClearIcon from "@mui/icons-material/Clear";
import SearchIcon from "@mui/icons-material/Search";
import IconButton from "@mui/material/IconButton";
import InputAdornment from "@mui/material/InputAdornment";
import TextField from "@mui/material/TextField";

type TableSearchProps = {
  value: string;
  /** Called on every keystroke; the caller decides when it applies (usually debounced). */
  onChange: (value: string) => void;
  /** Apply right away (Enter or the clear button). */
  onFlush?: () => void;
  placeholder?: string;
};

/** Search box shown above a table, for the row's security name or ticker. */
export default function TableSearch({ value, onChange, onFlush, placeholder = "Search security name or ticker" }: TableSearchProps) {
  return (
    <TextField
      size="small"
      placeholder={placeholder}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      onKeyDown={(event) => event.key === "Enter" && onFlush?.()}
      sx={{ width: 320, maxWidth: "100%" }}
      slotProps={{
        htmlInput: { "aria-label": "Search security" },
        input: {
          startAdornment: (
            <InputAdornment position="start">
              <SearchIcon fontSize="small" />
            </InputAdornment>
          ),
          endAdornment: value ? (
            <InputAdornment position="end">
              <IconButton
                size="small"
                aria-label="Clear search"
                onClick={() => {
                  onChange("");
                  onFlush?.();
                }}
              >
                <ClearIcon fontSize="small" />
              </IconButton>
            </InputAdornment>
          ) : null,
        },
      }}
    />
  );
}
