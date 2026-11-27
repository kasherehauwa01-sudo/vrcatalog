import { Alert, Radio, RadioGroup, TextField, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, IconButton, LinearProgress, MenuItem, Paper, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";

type Column = readonly [string, string];
export type ExportOptions = {
  promotion_type: string; adjustment: boolean; adjustment_percent: string;
  group_categories: boolean; group_folders: boolean; promotion: boolean;
  order_form: boolean; zip_categories: boolean;
  markup: boolean; markup_percent: string; markup_column: boolean;
  stock_filter: boolean; stock_warehouses: string[]; stock_comparison: "more" | "less"; stock_limit: string;
};
export const defaultExportOptions: ExportOptions = {
  promotion_type: "", adjustment: false, adjustment_percent: "", markup: false, markup_percent: "", markup_column: false,
  stock_filter: false, stock_warehouses: [], stock_comparison: "less", stock_limit: "",
  group_categories: false, group_folders: false, promotion: false, order_form: false, zip_categories: false,
};
type Props = {
  options: ExportOptions; onOptionsChange: (options: ExportOptions) => void;
  open: boolean; exporting: boolean; progress: number | null; message: string; error: string | null;
  columns: string[]; mainColumns: readonly Column[]; prices: readonly string[];
  warehouses: { code: string; name: string }[];
  onChange: (columns: string[]) => void; onDefaults: () => void;
  onClose: () => void; onDownload: () => void;
};

export function ExportColumnsDialog(props: Props) {
  const { columns, exporting, options } = props;
  const validMarkup = !options.markup || (options.markup_percent.trim() !== "" && Number.isFinite(Number(options.markup_percent.replace(",", "."))));
  const validStock = !options.stock_filter || (
    options.stock_warehouses.length > 0 && options.stock_warehouses.every((code) => props.warehouses.some((warehouse) => warehouse.code === code))
    && /^\d+$/.test(options.stock_limit.trim()) && Number(options.stock_limit) <= 2147483647
  );
  const singlePrice = options.promotion || options.order_form || options.adjustment || options.markup || options.markup_column;
  const columnCount = columns.length + (props.options.promotion ? 2 - columns.filter((key) => key.startsWith("price:")).length : 0) + (props.options.order_form ? 2 : 0) + (props.options.adjustment ? 1 : 0) + (options.markup_column ? 1 : 0);
  const validPrice = columns.filter((key) => key.startsWith("price:")).length === 1;
  const validPercent = props.options.adjustment_percent.trim() !== "" && Number.isFinite(Number(props.options.adjustment_percent.replace(",", ".")));
  const missingType = props.options.promotion && !props.options.promotion_type;
  type ToggleKey = "group_categories" | "group_folders" | "promotion" | "order_form" | "zip_categories" | "adjustment" | "markup" | "markup_column" | "stock_filter";
  const setOption = (key: ToggleKey, checked: boolean) => {
    props.onOptionsChange({ ...props.options, [key]: checked, ...(key === "promotion" && checked ? { promotion_type: "" } : {}) });
    if (checked && (key === "promotion" || key === "order_form" || key === "adjustment" || key === "markup" || key === "markup_column")) {
      // Each form activation requires an explicit price choice.
      const next = columns.filter((item) => !item.startsWith("price:"));
      if (key === "order_form" && !next.includes("site_url")) next.push("site_url");
      props.onChange(next);
    }
  };
  const layoutOptions: [ToggleKey, string, string][] = [
    ["group_categories", "Формировать по категориям", "Строки с названием категории и подкатегории перед товарами."],
    ["group_folders", "Формировать по группам", "Папки и вложенные папки перед товарами. Можно сочетать с категориями."],
    ["promotion", "Форма для акции месяца", "Только товары выбранного вида: «Акция месяца» или «Надо продать». В конце — новая и предыдущая цена выбранного типа."],
    ["order_form", "Форма для заказа", "В конце — поле «Заказ» и формула суммы. С акцией используется новая цена. Только один вид цены."],
    ["adjustment", "Скидка / Наценка", "Колонка «Ваша цена»: выбранная цена с учётом процента. Плюс — наценка, минус — скидка."],
    ["markup", "Показывать товар с наценкой больше", "Наценка считается от закупочной цены к одному выбранному виду продажной цены."],
    ["markup_column", "Наценка", "Добавляет в файл процент наценки относительно закупочной цены."],
    ["stock_filter", "Показывать только товар с остатком", "Остаток должен соответствовать условию на каждом выбранном складе."],
    ["zip_categories", "По всем категориям (zip)", "Отдельный Excel для каждой подкатегории из текущей выборки, в одном ZIP-архиве."],
  ];
  const media: Column[] = [["photo", "Фото"], ["image_url", "Ссылка на фото"], ["site_url", "Ссылка на сайт"]];
  const groups = [
    { title: "Основные сведения", items: props.mainColumns.filter(([key]) => key !== "photo"), description: "Код, название и характеристики товара" },
    { title: "Фото и ссылки", items: media, description: "Фото встраивает миниатюру. Ссылка на фото открывает главное изображение, ссылка на сайт открывает товар на volgorost.ru по его коду." },
    { title: "Цены", items: [...props.prices.map((name): Column => [`price:${name}`, name]), ["purchase_price", "ЦенаЗакупочная"] as Column], description: "Выберите нужные виды цен" },
    { title: "Остатки на складах", items: props.warehouses.map((item): Column => [`stock:${item.code}`, item.name]), description: "Отдельная колонка для каждого выбранного склада" },
  ];
  const toggle = (key: string) => {
    if (singlePrice && key.startsWith("price:")) {
      props.onChange([...columns.filter((item) => !item.startsWith("price:")), ...(columns.includes(key) ? [] : [key])]);
      return;
    }
    props.onChange(columns.includes(key) ? columns.filter((item) => item !== key) : [...columns, key]);
  };
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
        <Paper variant="outlined" component="section" aria-label="Формат таблицы" sx={{ p: 2.5 }}>
          <Typography component="h3" variant="h6">Формат таблицы</Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>Настройки применяются ко всей выборке. Формы и группировки можно сочетать.</Typography>
          <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 1 }}>
            {layoutOptions.map(([key, label, hint]) => <Box key={key}>
              <FormControlLabel sx={{ m: 0, minHeight: 44 }} label={label} control={<Checkbox disabled={exporting} checked={props.options[key]} onChange={(_, checked) => setOption(key, checked)} />} />
              {key === "adjustment" && <TextField label="Процент скидки / наценки" size="small" placeholder="Например, -10 или 15" value={props.options.adjustment_percent} disabled={exporting || !props.options.adjustment} onChange={(event) => props.onOptionsChange({ ...props.options, adjustment_percent: event.target.value })} inputProps={{ inputMode: "decimal" }} error={props.options.adjustment && !validPercent} sx={{ my: 1, ml: 5.25, maxWidth: "80%" }} />}
              {key === "markup" && options.markup && <TextField label="Порог наценки, %" size="small" value={options.markup_percent} disabled={exporting} onChange={(event) => props.onOptionsChange({ ...options, markup_percent: event.target.value })} inputProps={{ inputMode: "decimal" }} error={!validMarkup} sx={{ my: 1, ml: 5.25, maxWidth: "80%" }} />}
              {key === "stock_filter" && options.stock_filter && <Stack spacing={1} sx={{ my: 1, ml: 5.25 }}>
                <Stack direction={{ xs: "column", sm: "row" }} gap={1}>
                  <ToggleButtonGroup exclusive size="small" aria-label="Сравнение остатка" value={options.stock_comparison} disabled={exporting} onChange={(_, value: ExportOptions["stock_comparison"] | null) => {
                    if (value) props.onOptionsChange({ ...options, stock_comparison: value });
                  }}>
                    <ToggleButton value="more">Больше</ToggleButton>
                    <ToggleButton value="less">Меньше</ToggleButton>
                  </ToggleButtonGroup>
                  <TextField label="Остаток, шт." size="small" value={options.stock_limit} disabled={exporting} inputProps={{ inputMode: "numeric" }} onChange={(event) => props.onOptionsChange({ ...options, stock_limit: event.target.value })} />
                </Stack>
                <TextField id="export-stock-warehouses" select label="Склады для отбора" size="small" value={options.stock_warehouses} disabled={exporting || !props.warehouses.length}
                  onChange={(event) => {
                    const selected: string | string[] = event.target.value;
                    props.onOptionsChange({ ...options, stock_warehouses: typeof selected === "string" ? [selected] : selected });
                  }}
                  SelectProps={{
                    multiple: true,
                    renderValue: (value) => props.warehouses.filter(({ code }) => (value as string[]).includes(code)).map(({ name }) => name).join(", "),
                  }}>
                  {props.warehouses.map(({ code, name }) => <MenuItem key={code} value={code}>
                    <Checkbox checked={options.stock_warehouses.includes(code)} tabIndex={-1} disableRipple inputProps={{ "aria-hidden": true }} />{name}
                  </MenuItem>)}
                </TextField>
                <Typography variant="body2" color="text.secondary">«Меньше» включает порог. Остатки менее 1 шт. исключаются.</Typography>
              </Stack>}
              {key === "promotion" && props.options.promotion && <RadioGroup aria-label="Вид товара для формы акции" value={props.options.promotion_type} onChange={(_, value) => props.onOptionsChange({ ...props.options, promotion_type: value })} sx={{ ml: 5.25 }}>
                {["Акция месяца", "Надо продать"].map((name) => <FormControlLabel key={name} value={name} control={<Radio disabled={exporting} />} label={name} />)}
              </RadioGroup>}
              <Typography variant="body2" color="text.secondary" sx={{ ml: 5.25 }}>{hint}</Typography>
            </Box>)}
          </Box>
          {singlePrice && <Typography role="status" sx={{ mt: 2 }}>Выберите один вид продажной цены в блоке «Цены». Закупочную цену можно добавить отдельной колонкой.</Typography>}
        </Paper>
        <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" }, gap: 2, alignItems: "start" }}>
          {groups.map(({ title, items, description }) => {
            const selected = items.filter(([key]) => columns.includes(key)).length;
            return <Paper key={title} variant="outlined" component="section" aria-label={title} sx={{ p: { xs: 2, md: 2.5 }, minWidth: 0 }}>
              <Stack direction="row" justifyContent="space-between" alignItems="center" gap={1}>
                <Typography component="h3" variant="h6">{title}</Typography>
                {!(singlePrice && title === "Цены") && <FormControlLabel sx={{ mr: 0, flexShrink: 0 }} label={`${selected}/${items.length}`} control={<Checkbox disabled={exporting || !items.length} checked={!!items.length && selected === items.length} indeterminate={selected > 0 && selected < items.length} inputProps={{ "aria-label": `Выбрать всю группу: ${title}` }} onChange={() => props.onChange(selected === items.length ? columns.filter((key) => !items.some(([item]) => item === key)) : [...new Set([...columns, ...items.map(([key]) => key)])])} />} />}
              </Stack>
              <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>{description}</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: title === "Фото и ссылки" ? "1fr" : "1fr 1fr" }, columnGap: 2 }}>
                {items.map(([key, label]) => <FormControlLabel key={key} sx={{ minHeight: 44, mx: 0, overflowWrap: "anywhere" }}
                  control={<Checkbox disabled={exporting} checked={columns.includes(key)} onChange={() => toggle(key)} />} label={label} />)}
              </Box>
              {!items.length && <Typography color="text.secondary">Нет доступных значений</Typography>}
              {title === "Фото и ссылки" && columns.includes("photo") && <Typography variant="body2" sx={{ mt: 1 }} color="text.secondary">Миниатюры увеличивают размер файла и время формирования. Для лёгкого файла достаточно ссылки на фото.</Typography>}
            </Paper>;
          })}
        </Box>
      </Stack>
    </DialogContent>
    <DialogActions sx={{ p: 2, bgcolor: "white", borderTop: "1px solid", borderColor: "divider" }}>
      <Stack direction={{ xs: "column", sm: "row" }} gap={1.5} alignItems={{ sm: "center" }} flexWrap="wrap" sx={{ width: "100%", maxWidth: 1200, mx: "auto" }}>
        {missingType && <Alert severity="warning">Выберите вид товара: «Акция месяца» или «Надо продать».</Alert>}
        {props.options.adjustment && !validPercent && <Alert severity="warning">Введите процент скидки / наценки.</Alert>}
        {singlePrice && !validPrice && <Alert severity="warning" sx={{ flexShrink: 0 }}>Выберите один тип продажной цены в блоке «Цены», чтобы скачать файл.</Alert>}
        {!validMarkup && <Alert severity="warning">Введите порог наценки в процентах.</Alert>}
        {!validStock && <Alert severity="warning">Выберите хотя бы один склад и укажите целое количество для отбора по остатку.</Alert>}
        <Typography role="status" sx={{ mr: { sm: "auto" } }}>Выбрано колонок: <strong>{columnCount}</strong>{!columns.length && ". Выберите хотя бы одну"}</Typography>
        <Stack direction="row" spacing={1}>
          <Button fullWidth variant="outlined" disabled={exporting} onClick={props.onClose}>Отмена</Button>
          <Button fullWidth variant="contained" disabled={!columns.length || exporting || (singlePrice && !validPrice) || missingType || !validMarkup || !validStock || (props.options.adjustment && !validPercent)} onClick={props.onDownload} sx={{ minWidth: 160, whiteSpace: "nowrap" }}>{exporting ? "Формирование…" : (props.options.zip_categories ? "Скачать ZIP" : "Скачать Excel")}</Button>
        </Stack>
      </Stack>
    </DialogActions>
  </Dialog>;
}
