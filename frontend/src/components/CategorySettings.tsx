import { useEffect, useState } from "react";
import { Alert, Box, Button, Typography } from "@mui/material";
import { api, CategorySyncStatus } from "../api/client";
export function CategorySettings({ onSynced }: { onSynced: () => Promise<void> }) {
  const [status, setStatus] = useState<CategorySyncStatus>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => { api.categoryStatus().then(setStatus).catch((e) => setError(String(e))); }, []);
  return <Box sx={{ my: 2 }}>
    <Button variant="outlined" disabled={busy} onClick={async () => {
      setBusy(true); setError("");
      try { const result = await api.syncCategories(); setStatus(result); if (result.status === "success") await onSynced(); }
      catch (e) { setError(e instanceof Error ? e.message : String(e)); }
      finally { setBusy(false); }
    }}>{busy ? "Обновление категорий…" : "Обновить категории"}</Button>
    {status && <Typography variant="body2" sx={{ mt: 1 }}>Последняя успешная синхронизация: {status.last_success_at ? new Date(`${status.last_success_at}Z`).toLocaleString("ru-RU") : "ещё не выполнялась"}. Категорий: {status.category_count ?? 0}, разделов: {status.section_count ?? 0}.</Typography>}
    {(error || status?.last_error) && <Alert severity="error" sx={{ mt: 1 }}>{error || status?.last_error}</Alert>}
    {!!status?.unmatched_sections.length && <Box component="details" sx={{ mt: 1 }}>
      <Box component="summary" sx={{ cursor: "pointer", py: 1 }}>Разделы без категории ({status.unmatched_sections.length})</Box>
      <Box sx={{ maxHeight: 240, overflowY: "auto" }}>{status.unmatched_sections.map((item) => <Typography key={item.name} variant="body2" sx={{ overflowWrap: "anywhere" }}>{item.name} — {item.product_count}</Typography>)}</Box>
    </Box>}
  </Box>;
}
