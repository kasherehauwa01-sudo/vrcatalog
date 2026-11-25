import { Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, LinearProgress, Paper, Stack, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";

type Column = readonly [string, string];
type Props = {
  open: boolean; exporting: boolean; progress: number | null; message: string; error: string | null;
  columns: string[]; mainColumns: readonly Column[]; prices: readonly string[];
  warehouses: { code: string; name: string }[];
  onChange: (columns: string[]) => void; onDefaults: () => void;
  onClose: () => void; onDownload: () => void;
};

export function ExportColumnsDialog(props: Props) {
  const { columns, exporting } = props;
  const media: Column[] = [["photo", "Фото"], ["image_url", "Ссылка на фото"], ["site_url", "Ссылка на сайт"]];
  const groups = [
    { title: "Основные сведения", items: props.mainColumns.filter(([key]) => key !== "photo"), description: "Код, название и характеристики товара" },
    { title: "Фото и ссылки", items: media, description: "Фото встраивает миниатюру. Ссылка на фото открывает главное изображение, ссылка на сайт — поиск товара по коду на volgorost.ru." },
    { title: "Цены", items: props.prices.map((name): Column => [`price:${name}`, name]), description: "Выберите нужные виды цен" },
    { title: "Остатки на складах", items: props.warehouses.map((item): Column => [`stock:${item.code}`, item.name]), description: "Отдельная колонка для каждого выбранного склада" },
  ];
  const toggle = (key: string) => props.onChange(columns.includes(key) ? columns.filter((item) => item !== key) : [...columns, key]);
  return <Dialog fullScreen open={props.open} onClose={() => !exporting && props.onClose()} aria-labelledby="export-columns-title" PaperProps={{ sx: { bgcolor: "#f4f8fb", borderRadius: 0 } }}>
    <DialogTitle component="div" sx={{ bgcolor: "white", borderBottom: "1px solid", borderColor: "divider" }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ maxWidth: 1200, mx: "auto" }}>
        <Box><Typography id="export-columns-title" component="h2" variant="h5" fontWeight={800}>Колонки для Excel</Typography><Typography variant="body2" color="text.secondary">Выберите, что включить в файл</Typography></Box>
        <IconButton disabled={exporting} aria-label="Закрыть выбор колонок" onClick={props.onClose}><CloseIcon /></IconButton>
      </Stack>
    </DialogTitle>
    <DialogContent sx={{ p: { xs: 2, md: 3 } }}>
      <Stack spacing={2} sx={{ maxWidth: 1200, mx: "auto", py: 1 }}>
        {exporting && <Paper variant="outlined" sx={{ p: 2 }} role="status"><Typography sx={{ mb: 1 }}>{props.progress === null ? props.message : `Скачиваем файл: ${props.progress}%`}</Typography><LinearProgress variant={props.progress === null ? "indeterminate" : "determinate"} value={props.progress ?? 0} /></Paper>}
        {props.error && <Typography role="alert" color="error">{props.error}</Typography>}
        <Stack direction="row" gap={1} flexWrap="wrap">
          <Button disabled={exporting} onClick={props.onDefaults}>Стандартный набор</Button>
          <Button disabled={exporting || !columns.length} onClick={() => props.onChange([])}>Снять все</Button>
        </Stack>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2, alignItems: "start" }}>
          {groups.map(({ title, items, description }) => {
            const selected = items.filter(([key]) => columns.includes(key)).length;
            return <Paper key={title} variant="outlined" component="section" aria-label={title} sx={{ p: { xs: 2, md: 2.5 }, minWidth: 0 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1}>
                <Typography component="h3" variant="h6">{title}</Typography>
                <FormControlLabel sx={{ mr: 0, flexShrink: 0 }} label={`${selected}/${items.length}`} control={<Checkbox disabled={exporting || !items.length} checked={!!items.length && selected === items.length} indeterminate={selected > 0 && selected < items.length} inputProps={{ "aria-label": `Выбрать всю группу: ${title}` }} onChange={() => props.onChange(selected === items.length ? columns.filter((key) => !items.some(([item]) => item === key)) : [...new Set([...columns, ...items.map(([key]) => key)])])} />} />
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{description}</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: title === "Фото и ссылки" ? "1fr" : "1fr 1fr" }, columnGap: 2 }}>
                {items.map(([key, label]) => <FormControlLabel key={key} sx={{ minHeight: 44, mx: 0, overflowWrap: "anywhere" }} control={<Checkbox disabled={exporting} checked={columns.includes(key)} onChange={() => toggle(key)} />} label={label} />)}
              </Box>
              {!items.length && <Typography color="text.secondary">Нет доступных значений</Typography>}
              {title === "Фото и ссылки" && columns.includes("photo") && <Typography variant="body2" sx={{ mt: 1 }} color="text.secondary">Миниатюры увеличивают размер файла и время формирования. Для лёгкого файла достаточно ссылки на фото.</Typography>}
            </Paper>;
          })}
        </Box>
      </Stack>
    </DialogContent>
    <DialogActions sx={{ p: 2, bgcolor: "white", borderTop: "1px solid", borderColor: "divider" }}>
      <Stack direction={{ xs: "column", sm: "row" }} gap={1.5} alignItems={{ sm: "center" }} sx={{ width: "100%", maxWidth: 1200, mx: "auto" }}>
        <Typography role="status" sx={{ mr: { sm: "auto" } }}>Выбрано колонок: <strong>{columns.length}</strong>{!columns.length && ". Выберите хотя бы одну"}</Typography>
        <Stack direction="row" spacing={1}>
          <Button fullWidth variant="outlined" disabled={exporting} onClick={props.onClose}>Отмена</Button>
          <Button fullWidth variant="contained" disabled={!columns.length || exporting} onClick={props.onDownload} sx={{ minWidth: 160, whiteSpace: "nowrap" }}>{exporting ? "Формирование…" : "Скачать Excel"}</Button>
        </Stack>
      </Stack>
    </DialogActions>
  </Dialog>;
}
