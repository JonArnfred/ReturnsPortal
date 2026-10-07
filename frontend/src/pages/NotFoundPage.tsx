import Paper from "@mui/material/Paper";
import Typography from "@mui/material/Typography";
import AppShell from "../app/AppShell";

export default function NotFoundPage() {
  return (
    <AppShell title="Not found">
      <Paper variant="outlined" sx={{ p: 3, maxWidth: 720 }}>
        <Typography variant="h2">Page not found</Typography>
        <Typography variant="body2" color="text.secondary">
          The requested page does not exist.
        </Typography>
      </Paper>
    </AppShell>
  );
}
