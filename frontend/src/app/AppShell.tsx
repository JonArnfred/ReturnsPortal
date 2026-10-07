import ArrowBackIosNewIcon from "@mui/icons-material/ArrowBackIosNew";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import VisibilityOffOutlinedIcon from "@mui/icons-material/VisibilityOffOutlined";
import VisibilityOutlinedIcon from "@mui/icons-material/VisibilityOutlined";
import AppBar from "@mui/material/AppBar";
import Box from "@mui/material/Box";
import Breadcrumbs from "@mui/material/Breadcrumbs";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Link from "@mui/material/Link";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import ToggleButton, { type ToggleButtonProps } from "@mui/material/ToggleButton";
import ToggleButtonGroup from "@mui/material/ToggleButtonGroup";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import { forwardRef, useState, type MouseEvent, type ReactNode } from "react";
import { Link as RouterLink, NavLink, useLocation, useNavigate } from "react-router-dom";
import ReportingPeriodNotice from "../components/ReportingPeriodNotice";
import { findNavItem, railSections, type NavItem } from "./navigation";
import { usePrivacy } from "./privacy";

export const TOP_BAR_HEIGHT = 48;
export const BREADCRUMB_HEIGHT = 40;
const RAIL_WIDTH = 96;

type AppShellProps = {
  title: string;
  /** For detail pages: the list page this one belongs to, shown in the breadcrumb and kept active in the rail. */
  parent?: { label: string; path: string };
  children: ReactNode;
};

/**
 * The app frame: a slim top bar with area menus, a narrow icon
 * rail on the left grouped by section, a breadcrumb strip, and the page content filling the rest.
 */
export default function AppShell({ title, parent, children }: AppShellProps) {
  const location = useLocation();
  const activePath = parent?.path ?? location.pathname;
  const current = findNavItem(activePath);

  return (
    <Box sx={{ display: "flex", flexDirection: "column", minHeight: "100vh", bgcolor: "background.default" }}>
      <TopBar />
      <Box sx={{ display: "flex", flex: 1, minHeight: 0 }}>
        <Rail activePath={activePath} />
        <Box component="main" sx={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column" }}>
          <BreadcrumbBar section={current?.section.label} parent={parent} title={title} />
          <Box sx={{ flex: 1, minHeight: 0, px: 2, pb: 2 }}>
            {(location.pathname.startsWith("/investments/") && location.pathname !== "/investments/portfolios"
              || location.pathname === "/reports/pnl" || location.pathname === "/data/reconciliation")
              ? <ReportingPeriodNotice /> : null}
            {children}
          </Box>
        </Box>
      </Box>
    </Box>
  );
}

function TopBar() {
  return (
    <AppBar
      position="sticky"
      elevation={0}
      sx={{ bgcolor: "#1f2a37", color: "#fff", borderBottom: "1px solid #101820" }}
    >
      {/* The border sits outside the toolbar, so it is taken off the height to keep TOP_BAR_HEIGHT exact. */}
      <Toolbar variant="dense" sx={{ minHeight: TOP_BAR_HEIGHT - 1, gap: 1.5, px: { xs: 1.5, md: 2 } }}>
        <Link
          component={RouterLink}
          to="/"
          underline="none"
          sx={{ color: "inherit", display: "flex", alignItems: "baseline", gap: 0.75, mr: 1.5 }}
        >
          <Typography sx={{ fontWeight: 700, letterSpacing: 0.2 }}>Returns Portal</Typography>
        </Link>
        <Box sx={{ display: "flex", gap: 0.5, flex: 1, overflowX: "auto" }}>
          {railSections.map((area) =>
            area.items.length === 1 ? (
              <TopLink key={area.label} label={area.label} item={area.items[0]} />
            ) : (
              <TopMenu key={area.label} label={area.label} items={area.items} />
            ),
          )}
        </Box>
        <AmountsToggle />
      </Toolbar>
    </AppBar>
  );
}

/** ToggleButtonGroup injects props into its children, so the tooltip wrapper has to pass them on. */
const TooltipToggleButton = forwardRef<HTMLButtonElement, ToggleButtonProps & { title: string }>(function TooltipToggleButton(
  { title, ...props },
  ref,
) {
  return (
    <Tooltip title={title}>
      <ToggleButton ref={ref} {...props} />
    </Tooltip>
  );
});

/** Show or hide every figure that reveals the size of the holdings; see `app/privacy.tsx`. */
function AmountsToggle() {
  const { hidden, setHidden } = usePrivacy();
  return (
    <ToggleButtonGroup
      exclusive
      size="small"
      value={hidden ? "hidden" : "shown"}
      onChange={(_event, value: "shown" | "hidden" | null) => value && setHidden(value === "hidden")}
      aria-label="Amount visibility"
      sx={{
        "& .MuiToggleButton-root": {
          color: "#9fb0c0",
          borderColor: "rgba(255,255,255,0.18)",
          px: 0.75,
          py: 0.25,
          "&:hover": { bgcolor: "rgba(255,255,255,0.08)" },
          "&.Mui-selected": { color: "#fff", bgcolor: "rgba(255,255,255,0.18)" },
          "&.Mui-selected:hover": { bgcolor: "rgba(255,255,255,0.24)" },
        },
      }}
    >
      <TooltipToggleButton value="shown" title="Show amounts" aria-label="Show amounts">
        <VisibilityOutlinedIcon sx={{ fontSize: 18 }} />
      </TooltipToggleButton>
      <TooltipToggleButton value="hidden" title="Hide amounts" aria-label="Hide amounts">
        <VisibilityOffOutlinedIcon sx={{ fontSize: 18 }} />
      </TooltipToggleButton>
    </ToggleButtonGroup>
  );
}

const topButtonSx = {
  color: "#dce3ea",
  px: 1.25,
  minWidth: 0,
  fontWeight: 500,
  "&:hover": { bgcolor: "rgba(255,255,255,0.08)" },
  "&.active": { bgcolor: "rgba(255,255,255,0.14)", color: "#fff" },
};

function TopLink({ label, item }: { label: string; item: NavItem }) {
  return (
    <Button component={NavLink} to={item.path} end sx={topButtonSx}>
      {label}
    </Button>
  );
}

function TopMenu({ label, items }: { label: string; items: NavItem[] }) {
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const active = items.some((item) => item.path === location.pathname);
  return (
    <>
      <Button
        onClick={(event: MouseEvent<HTMLElement>) => setAnchor(event.currentTarget)}
        endIcon={<ExpandMoreIcon sx={{ fontSize: 16, ml: -0.5 }} />}
        className={active ? "active" : undefined}
        sx={topButtonSx}
      >
        {label}
      </Button>
      <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
        {items.map((item) => (
          <MenuItem
            key={item.path}
            dense
            selected={item.path === location.pathname}
            onClick={() => {
              setAnchor(null);
              navigate(item.path);
            }}
          >
            {item.label}
          </MenuItem>
        ))}
      </Menu>
    </>
  );
}

function Rail({ activePath }: { activePath: string }) {
  return (
    <Box
      component="nav"
      aria-label="Sections"
      sx={{
        width: RAIL_WIDTH,
        flexShrink: 0,
        bgcolor: "background.paper",
        borderRight: "1px solid",
        borderColor: "divider",
        position: "sticky",
        top: TOP_BAR_HEIGHT,
        height: `calc(100vh - ${TOP_BAR_HEIGHT}px)`,
        overflowY: "auto",
        py: 0.5,
      }}
    >
      {railSections.map((section) => (
        <Box key={section.label} sx={{ mb: 1 }}>
          {section.items.length === 1 && section.items[0].label === section.label ? (
            <Box sx={{ pt: 1 }} />
          ) : (
            <Typography
              variant="caption"
              sx={{ display: "block", px: 1, pt: 1, pb: 0.25, color: "text.secondary", fontWeight: 600, letterSpacing: 0.4 }}
            >
              {section.label}
            </Typography>
          )}
          {section.items.map((item) => {
            const Icon = item.icon;
            const active = item.path === activePath;
            return (
              <Box
                key={item.path}
                component={RouterLink}
                to={item.path}
                sx={{
                  display: "flex",
                  flexDirection: "column",
                  alignItems: "center",
                  gap: 0.25,
                  py: 0.75,
                  mx: 0.5,
                  borderRadius: 1,
                  color: active ? "primary.dark" : "text.secondary",
                  bgcolor: active ? "rgba(42,120,214,0.10)" : "transparent",
                  textDecoration: "none",
                  "&:hover": { bgcolor: active ? "rgba(42,120,214,0.14)" : "rgba(23,32,42,0.05)" },
                }}
              >
                <Icon sx={{ fontSize: 22 }} />
                <Typography sx={{ fontSize: 11, lineHeight: 1.1, textAlign: "center" }}>{item.label}</Typography>
              </Box>
            );
          })}
        </Box>
      ))}
    </Box>
  );
}

function BreadcrumbBar({ section, parent, title }: { section?: string; parent?: { label: string; path: string }; title: string }) {
  const navigate = useNavigate();
  return (
    <Box
      sx={{
        display: "flex",
        alignItems: "center",
        gap: 1,
        height: BREADCRUMB_HEIGHT,
        px: 2,
        flexShrink: 0,
      }}
    >
      <IconButton size="small" onClick={() => navigate(-1)} aria-label="Back">
        <ArrowBackIosNewIcon sx={{ fontSize: 13 }} />
      </IconButton>
      <Breadcrumbs sx={{ "& .MuiBreadcrumbs-separator": { mx: 0.75 } }}>
        {section && section !== title ? (
          <Typography variant="body2" color="text.secondary">
            {section}
          </Typography>
        ) : null}
        {parent ? (
          <Link component={RouterLink} to={parent.path} variant="body2" underline="hover" color="text.secondary">
            {parent.label}
          </Link>
        ) : null}
        <Typography variant="body2" color="text.primary" sx={{ fontWeight: 600 }}>
          {title}
        </Typography>
      </Breadcrumbs>
    </Box>
  );
}
