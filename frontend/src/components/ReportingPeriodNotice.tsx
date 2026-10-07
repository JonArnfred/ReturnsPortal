import Link from "@mui/material/Link";
import Typography from "@mui/material/Typography";
import { useEffect, useState } from "react";
import { Link as RouterLink, useLocation } from "react-router-dom";
import { fetchPortfolios, type PortfolioCard } from "../api/client";

/** Keep the active accounting boundary visible on activity and report pages. */
export default function ReportingPeriodNotice() {
  const location = useLocation();
  const [portfolios, setPortfolios] = useState<PortfolioCard[]>([]);
  // Fetched again on every page change: the dates may just have been changed on the Portfolios page.
  useEffect(() => {
    let cancelled = false;
    fetchPortfolios().then((payload) => {
      if (!cancelled) setPortfolios(payload.data);
    }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [location.pathname]);
  const id = Number(new URLSearchParams(location.search).get("portfolio") ?? 0);
  const visible = id ? portfolios.filter((p) => p.id === id) : portfolios;
  if (!visible.some((p) => p.reporting_start_date)) return null;
  return (
    <Typography variant="caption" color="text.secondary" component="div" sx={{ mb: 1 }}>
      Reporting: {visible.map((p) => `${p.name} — ${p.reporting_start_date ? `Since ${p.reporting_start_date}` : "Full history"}`).join(" · ")}
      {" · "}<Link component={RouterLink} to="/investments/portfolios">Change dates</Link>
    </Typography>
  );
}
