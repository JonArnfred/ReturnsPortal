import FirstPageIcon from "@mui/icons-material/FirstPage";
import KeyboardArrowLeftIcon from "@mui/icons-material/KeyboardArrowLeft";
import KeyboardArrowRightIcon from "@mui/icons-material/KeyboardArrowRight";
import LastPageIcon from "@mui/icons-material/LastPage";
import Box from "@mui/material/Box";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Paper from "@mui/material/Paper";
import Select from "@mui/material/Select";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TableSortLabel from "@mui/material/TableSortLabel";
import Typography from "@mui/material/Typography";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useSearchParams } from "react-router-dom";

export type Column<Row> = {
  key: string;
  header: ReactNode;
  render: (row: Row) => ReactNode;
  align?: "left" | "right" | "center";
  /** Row field to sort by; omit for a non-sortable column. */
  sortKey?: keyof Row;
  minWidth?: number;
  noWrap?: boolean;
};

export type SortState = { orderBy: string; order: "asc" | "desc" };

const PER_PAGE_OPTIONS = [50, 100, 200, 500];
/** Bottom padding of the page content in `AppShell` plus the table's own bottom border, in pixels. */
const BELOW_TABLE = 17;

/**
 * URL-as-state table: `page`, `per_page`, `order_by`, `order` live in the query string, so a view
 * is shareable and the server can do the paging later without changing the component.
 */
export function useTableParams(defaultOrderBy: string, defaultOrder: "asc" | "desc" = "desc") {
  const [params, setParams] = useSearchParams();
  const page = Math.max(1, Number(params.get("page") ?? "1") || 1);
  const perPage = Number(params.get("per_page") ?? "100") || 100;
  const orderBy = params.get("order_by") ?? defaultOrderBy;
  const order = (params.get("order") === "asc" ? "asc" : params.get("order") === "desc" ? "desc" : defaultOrder) as
    | "asc"
    | "desc";

  function update(next: Record<string, string | null>) {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value === null || value === "") merged.delete(key);
      else merged.set(key, value);
    }
    setParams(merged);
  }

  return {
    page,
    perPage,
    sort: { orderBy, order } as SortState,
    setPage: (nextPage: number) => update({ page: String(nextPage) }),
    setPerPage: (nextPerPage: number) => update({ per_page: String(nextPerPage), page: "1" }),
    setSort: (nextOrderBy: string) =>
      update({
        order_by: nextOrderBy,
        order: nextOrderBy === orderBy ? (order === "desc" ? "asc" : "desc") : "desc",
        page: "1",
      }),
  };
}

export function sortRows<Row>(rows: Row[], sort: SortState): Row[] {
  const key = sort.orderBy as keyof Row;
  const direction = sort.order === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    const left = a[key];
    const right = b[key];
    if (left === right) return 0;
    if (left === null || left === undefined) return 1;
    if (right === null || right === undefined) return -1;
    return (left < right ? -1 : 1) * direction;
  });
}

type DataTableProps<Row> = {
  columns: Column<Row>[];
  rows: Row[];
  total: number;
  rowKey: (row: Row) => string;
  page: number;
  perPage: number;
  sort: SortState;
  onPageChange: (page: number) => void;
  onPerPageChange: (perPage: number) => void;
  onSortChange: (orderBy: string) => void;
  /**
   * Height of everything above the table's scroll area, used for the server render and the first paint. After
   * mount the table measures its own position, so this only needs to be roughly right.
   */
  offsetTop?: number;
  /** Fill the parent flex container instead of sizing from the viewport; for panes in `SplitView` or a page-height flex column (see `ReturnsPage`). */
  fill?: boolean;
  /** Makes rows clickable; `selectedKey` highlights the row whose key matches. */
  onRowClick?: (row: Row) => void;
  selectedKey?: string;
};

export default function DataTable<Row>({
  columns,
  rows,
  total,
  rowKey,
  page,
  perPage,
  sort,
  onPageChange,
  onPerPageChange,
  onSortChange,
  offsetTop = 140,
  fill = false,
  onRowClick,
  selectedKey,
}: DataTableProps<Row>) {
  const lastPage = Math.max(1, Math.ceil(total / perPage));
  const from = total === 0 ? 0 : (page - 1) * perPage + 1;
  const to = Math.min(page * perPage, total);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [measuredTop, setMeasuredTop] = useState<number | null>(null);

  // Size the scroll area from where it actually sits, so the table ends at the bottom of the viewport whatever
  // the page puts above it. Re-measured after every render (content above often arrives with the data), on
  // viewport resizes, and when anything on the page changes size (alerts, wrapping toolbars).
  const measure = useCallback(() => {
    const element = scrollRef.current;
    if (element && !fill) setMeasuredTop(Math.round(element.getBoundingClientRect().top + window.scrollY));
  }, [fill]);
  useEffect(measure);
  useEffect(() => {
    if (fill) return undefined;
    window.addEventListener("resize", measure);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(document.body);
    return () => {
      window.removeEventListener("resize", measure);
      observer?.disconnect();
    };
  }, [fill, measure]);
  const scrollSx = fill
    ? { flex: 1, minHeight: 0 }
    : { maxHeight: `calc(100vh - ${measuredTop === null ? offsetTop : measuredTop + BELOW_TABLE}px)` };

  return (
    <Paper variant="outlined" sx={{ display: "flex", flexDirection: "column", minWidth: 0, ...(fill ? { flex: 1, minHeight: 0 } : {}) }}>
      <Box sx={{ display: "flex", alignItems: "center", justifyContent: "flex-end", gap: 1, px: 1, py: 0.5 }}>
        <Typography variant="body2" color="text.secondary" sx={{ fontVariantNumeric: "tabular-nums" }}>
          {from} - {to} of {total.toLocaleString("en-US")}
        </Typography>
        <IconButton size="small" disabled={page <= 1} onClick={() => onPageChange(1)} aria-label="First page">
          <FirstPageIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" disabled={page <= 1} onClick={() => onPageChange(page - 1)} aria-label="Previous page">
          <KeyboardArrowLeftIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" disabled={page >= lastPage} onClick={() => onPageChange(page + 1)} aria-label="Next page">
          <KeyboardArrowRightIcon fontSize="small" />
        </IconButton>
        <IconButton size="small" disabled={page >= lastPage} onClick={() => onPageChange(lastPage)} aria-label="Last page">
          <LastPageIcon fontSize="small" />
        </IconButton>
        <Select
          size="small"
          value={perPage}
          onChange={(event) => onPerPageChange(Number(event.target.value))}
          renderValue={(value) => `Show items per page: ${value}`}
          sx={{ ml: 1, fontSize: "0.78rem", "& .MuiSelect-select": { py: 0.5 } }}
        >
          {PER_PAGE_OPTIONS.map((option) => (
            <MenuItem key={option} value={option} dense>
              {option}
            </MenuItem>
          ))}
        </Select>
      </Box>
      <TableContainer ref={scrollRef} sx={scrollSx}>
        <Table stickyHeader size="small">
          <TableHead>
            <TableRow>
              {columns.map((column) => (
                <TableCell key={column.key} align={column.align ?? "left"} sx={{ minWidth: column.minWidth }}>
                  {column.sortKey ? (
                    <TableSortLabel
                      active={sort.orderBy === String(column.sortKey)}
                      direction={sort.orderBy === String(column.sortKey) ? sort.order : "desc"}
                      onClick={() => onSortChange(String(column.sortKey))}
                    >
                      {column.header}
                    </TableSortLabel>
                  ) : (
                    column.header
                  )}
                </TableCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row) => (
              <TableRow
                key={rowKey(row)}
                hover
                selected={selectedKey !== undefined && rowKey(row) === selectedKey}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                sx={onRowClick ? { cursor: "pointer" } : undefined}
              >
                {columns.map((column) => (
                  <TableCell key={column.key} align={column.align ?? "left"} sx={{ verticalAlign: "top", whiteSpace: column.noWrap ? "nowrap" : undefined }}>
                    {column.render(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={columns.length} align="center" sx={{ py: 4, color: "text.secondary" }}>
                  No rows match the current filters.
                </TableCell>
              </TableRow>
            ) : null}
          </TableBody>
        </Table>
      </TableContainer>
    </Paper>
  );
}
