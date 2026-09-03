import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  alpha,
  AppBar,
  Box,
  Button,
  Card,
  CardContent,
  Checkbox,
  Chip,
  Collapse,
  Container,
  CssBaseline,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  FormControlLabel,
  IconButton,
  InputAdornment,
  LinearProgress,
  List,
  MenuItem,
  Paper,
  Stack,
  Switch,
  Tab,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  TableSortLabel,
  Tabs,
  TextField,
  ThemeProvider,
  Tooltip,
  Typography,
  createTheme,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CloseIcon from "@mui/icons-material/Close";
import DeleteIcon from "@mui/icons-material/Delete";
import RefreshIcon from "@mui/icons-material/Refresh";
import EditIcon from "@mui/icons-material/Edit";
import SearchIcon from "@mui/icons-material/Search";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { api } from "./api/client";
import { BarcodeScanner } from "./components/BarcodeScanner";
import type {
  Meta,
  Product,
  ProductDetail,
  ProductType,
  XmlServerSetting,
  AutoImportState,
  ServiceLog,
  Warehouse,
  MailSetting,
  NotificationScenario,
  ScenarioRun,
  ScenarioSummary,
  NotificationHistory,
  DynamicAnalog,
  AnalogSelectionSetting,
} from "./types/catalog";

const theme = createTheme({
  palette: {
    mode: "light",
    primary: { main: "#0284c7" },
    secondary: { main: "#0369a1" },
    background: { default: "#f0f9ff", paper: "#ffffff" },
  },
  typography: {
    fontFamily: "Inter, Roboto, Arial, sans-serif",
    h4: { fontWeight: 800, letterSpacing: "-0.04em" },
    h6: { fontWeight: 800 },
  },
  shape: { borderRadius: 24 },
  components: {
    MuiCard: {
      styleOverrides: {
        root: {
          border: "1px solid rgba(2,132,199,0.14)",
          boxShadow: "0 16px 48px rgba(2,132,199,0.10)",
        },
      },
    },
    MuiButton: {
      defaultProps: { disableElevation: true },
      styleOverrides: {
        root: { borderRadius: 999, textTransform: "none", fontWeight: 700 },
      },
    },
    MuiTextField: { defaultProps: { variant: "outlined" } },
    MuiChip: {
      styleOverrides: { root: { borderRadius: 999, fontWeight: 600 } },
    },
  },
});

const SETTINGS_PASSWORD = "8852285";
const DELETE_PASSWORD = "8852285";

const exportMainColumns = [
  ["photo", "Фото"],
  ["article", "Артикул"],
  ["name", "Наименование"],
  ["section", "Раздел"],
  ["code", "Код"],
  ["product_type", "Вид товара"],
  ["manufacturer", "Производитель"],
  ["manager", "Менеджер"],
  ["marking_code", "Код маркировки"],
  ["material", "Материал"],
  ["certificate", "Сертификат"],
  ["barcodes", "Штрихкоды"],
] as const;
const exportPriceColumns = ["ЦенаОптовая", "ЦенаКорпоративная", "ЦенаРозничная"] as const;
const defaultExportColumns = ["code", "name", "section"];

const labels: Record<string, string> = {
  section: "Раздел",
  manufacturer: "Производитель",
  brand: "Бренд",
  manager: "Менеджер",
  country: "Страна",
  material: "Материал",
  color: "Цвет",
  barcode: "Штрихкод",
  product_type: "Вид товара",
  warehouse: "Склады",
};
const mainFilterOrder = [
  "Раздел", "Бренд", "Вид товара", "Склады", "Коллекция", "Менеджер",
  "Производитель", "Страна", "Комната", "Праздник", "Тематика",
  "HoReCa", "Выгружать на сайт", "Штрихкод",
];
const propertyFilterOrder = [
  "Материал", "Цвет", "Вкоробке", "Вид", "Вид ручки", "Высота",
  "Диаметр", "Для индукционных плит", "Единица измерения", "Код маркировки",
  "Количество ярусов", "Комплектность", "Литраж", "Маркировка Сатурн",
  "Материал основной", "Набор", "Назначение", "Наличие крышки",
  "Наличие основы", "Наличие подставки", "Наличие рисунка", "Наличие свистка",
  "Напиток", "Наполнитель", "Объем", "Особенности", "Покрытие", "Размер",
  "Серия", "Символ года", "ТВ товары", "Теги скидок", "Форм-фактор",
  "Форма", "Цифра",
];
type FilterFields = {
  code: string;
  article: string;
  name: string;
  inStockOnly: string;
  excludeYyy: string;
  onlyNew: string;
  availability: string;
  quantityFrom: string;
  quantityTo: string;
  priceFrom: string;
  priceTo: string;
  // Compatibility with an older deployed JSX revision; not rendered now.
  id?: string;
};
const filterFieldLabels: Partial<Record<keyof FilterFields, string>> = {
  code: "Код",
  article: "Артикул",
  name: "Название",
  inStockOnly: "Только в наличии",
  excludeYyy: "Исключить категорию ЯЯЯ",
  onlyNew: "Только новинки",
  availability: "Наличие",
  quantityFrom: "Количество от",
  quantityTo: "Количество до",
  priceFrom: "Цена от",
  priceTo: "Цена до",
};
const updateScriptPath = "/var/www/html/vr/vrcatalog/deploy/timeweb/update_vrcatalog.sh";
const clientsUrl = "https://kvasmix.ru/vr/clients/";
const formatMoscowDate = (value: string) =>
  new Date(value).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
const getLogStage = (log: ServiceLog) =>
  log.message.match(/Этап:\n([^\n]+)/)?.[1] ?? log.event;

const parseFilterValues = (value: string) => {
  const result: string[] = [];
  let current = "";
  let quoted = false;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    const nextChar = value[index + 1];
    if (char === '"') {
      if (quoted && nextChar === '"') {
        current += '"';
        index += 1;
      } else {
        quoted = !quoted;
      }
    } else if (char === "," && !quoted) {
      if (current.trim()) result.push(current.trim());
      current = "";
    } else {
      current += char;
    }
  }
  if (current.trim()) result.push(current.trim());
  return result;
};

const serializeFilterValues = (values: string[]) =>
  values
    .map((value) =>
      /[",\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value,
    )
    .join(",");

function App() {
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const multiFromUrl = (p: URLSearchParams) => {
    const result = Object.keys(labels).reduce<Record<string, string[]>>((values, key) => {
      const value = p.get(key === "product_type" ? "productType" : key);
      if (value) values[key] = parseFilterValues(value);
      return values;
    }, {});
    p.getAll("property").forEach((item) => {
      const [name, ...valueParts] = item.split(":");
      if (name && valueParts.length) (result[`property:${name}`] ??= []).push(valueParts.join(":"));
    });
    return result;
  };
  const fieldsFromUrl = (p: URLSearchParams): FilterFields => ({ code: p.get("code") ?? "", article: p.get("article") ?? "", name: p.get("name") ?? "", inStockOnly: p.get("inStockOnly") ?? "true", excludeYyy: p.get("excludeYyy") ?? "true", onlyNew: p.get("onlyNew") ?? "false", availability: p.get("availability") ?? "all", quantityFrom: p.get("quantityFrom") ?? "", quantityTo: p.get("quantityTo") ?? "", priceFrom: p.get("priceFrom") ?? "", priceTo: p.get("priceTo") ?? "" });
  const [search, setSearch] = useState(initialParams.get("search") ?? "");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [propertyOptions, setPropertyOptions] = useState<Record<string, string[]>>({});
  const filterLabels = useMemo(() => Object.keys(filters).reduce<Record<string, string>>((result, key) => {
    if (labels[key]) result[key] = labels[key];
    else if (key.startsWith("property:")) result[key] = key.slice("property:".length);
    return result;
  }, { ...labels }), [filters]);
  const filterLabel = (key: string) =>
    filterLabels[key] ?? (key.startsWith("property:") ? key.slice("property:".length) : key);
  const [active, setActive] = useState<Record<string, string[]>>(() => multiFromUrl(initialParams));
  const [draftActive, setDraftActive] = useState<Record<string, string[]>>(() => multiFromUrl(initialParams));
  const [filterFields, setFilterFields] = useState(() => fieldsFromUrl(initialParams));
  const [draftFields, setDraftFields] = useState(() => fieldsFromUrl(initialParams));
  const [products, setProducts] = useState<Product[]>([]);
  const [meta, setMeta] = useState<Meta>({ product_count: 0 });
  const [loading, setLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [tab, setTab] = useState<"catalog" | "settings">("catalog");
  const [settingsPasswordOpen, setSettingsPasswordOpen] = useState(false);
  const [settingsPassword, setSettingsPassword] = useState("");
  const [settingsPasswordError, setSettingsPasswordError] = useState(false);
  const [settingsUnlocked, setSettingsUnlocked] = useState(false);
  const [settingsTab, setSettingsTab] = useState<"settings" | "mappings" | "mail" | "scenarios" | "analogs" | "logs">("settings");
  const [openSettingsGroups, setOpenSettingsGroups] = useState<Record<string, boolean>>({});
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deletePasswordError, setDeletePasswordError] = useState(false);
  const [exportDialogOpen, setExportDialogOpen] = useState(false);
  const [exportColumns, setExportColumns] = useState<string[]>(defaultExportColumns);
  const [exportWarehouses, setExportWarehouses] = useState<Warehouse[]>([]);
  const [logs, setLogs] = useState<ServiceLog[]>([]);
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);
  const [pagination, setPagination] = useState({ page: Number(initialParams.get("page")) || 1, pageSize: Number(initialParams.get("pageSize")) || 100, totalItems: 0, totalPages: 0 });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [propertyPickerOpen, setPropertyPickerOpen] = useState(false);
  const [openCharacteristicGroups, setOpenCharacteristicGroups] = useState<Record<string, boolean>>({});
  const [openFilterGroups, setOpenFilterGroups] = useState<Record<string, boolean>>({});
  const [filterValueSearch, setFilterValueSearch] = useState<Record<string, string>>({});
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [productTypes, setProductTypes] = useState<ProductType[]>([]);
  const [warehouseCodes, setWarehouseCodes] = useState<string[]>([]);
  const [warehouseDialogOpen, setWarehouseDialogOpen] = useState(false);
  const [warehouseForm, setWarehouseForm] = useState<{ id?: number; code: string; name: string }>({ code: "", name: "" });
  const [productTypeDialogOpen, setProductTypeDialogOpen] = useState(false);
  const [productTypeForm, setProductTypeForm] = useState<{ id?: number; code: string; name: string }>({ code: "", name: "" });
  const [xmlServerForm, setXmlServerForm] = useState<XmlServerSetting | null>(null);
  const [autoImportState, setAutoImportState] = useState<AutoImportState | null>(null);
  const [ftpTestMessage, setFtpTestMessage] = useState<string | null>(null);
  const [manualImportMessage, setManualImportMessage] = useState<string | null>(null);
  const [mailForm, setMailForm] = useState<MailSetting | null>(null);
  const [scenarioForm, setScenarioForm] = useState<NotificationScenario | null>(null);
  const [scenarioList, setScenarioList] = useState<ScenarioSummary[]>([]);
  const [selectedScenario, setSelectedScenario] = useState<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyRows, setHistoryRows] = useState<NotificationHistory[]>([]);
  const [historySearch, setHistorySearch] = useState("");
  const [historyStatus, setHistoryStatus] = useState("all");
  const [testMailOpen, setTestMailOpen] = useState(false);
  const [testEmail, setTestEmail] = useState("");
  const [mailMessage, setMailMessage] = useState<string | null>(null);
  const [scenarioResult, setScenarioResult] = useState<ScenarioRun | null>(null);
  const [analogSettings, setAnalogSettings] = useState<AnalogSelectionSetting | null>(null);
  const [dynamicAnalogs, setDynamicAnalogs] = useState<DynamicAnalog[]>([]);
  const [analogsLoading, setAnalogsLoading] = useState(false);
  const [allAnalogs, setAllAnalogs] = useState<DynamicAnalog[]>([]);
  const [allAnalogsOpen, setAllAnalogsOpen] = useState(false);
  const [allAnalogsLoading, setAllAnalogsLoading] = useState(false);
  const [analogReason, setAnalogReason] = useState<DynamicAnalog | null>(null);
  const [queryVersion, setQueryVersion] = useState(0);
  const params = useMemo(() => new URLSearchParams(window.location.search), [queryVersion]);
  const replaceCatalogParams = (next: URLSearchParams) => {
    const query = next.toString();
    window.history.replaceState(null, "", `${window.location.pathname}${query ? `?${query}` : ""}`);
    setQueryVersion((value) => value + 1);
  };
  const updateParams = (changes: Record<string, string | number | null>, resetPage = true) => {
    const next = new URLSearchParams(window.location.search);
    Object.entries(changes).forEach(([key, value]) => {
      const normalized = String(value ?? "").trim();
      if (normalized && normalized !== "all") next.set(key, normalized); else next.delete(key);
    });
    if (resetPage) next.delete("page");
    replaceCatalogParams(next);
  };
  const reload = async () => {
    setLoading(true); setCatalogError(null);
    try {
      const result = await api.searchProducts(params);
      setProducts(result.items); setPagination(result.pagination); setSelectedIds([]);
    } catch (error) { setCatalogError(error instanceof Error ? error.message : "Не удалось получить товары"); }
    finally { setLoading(false); }
  };
  useEffect(() => { reload(); }, [params.toString()]);
  useEffect(() => { Promise.all([api.meta(), api.filters()]).then(([m, f]) => { setMeta(m); setFilters(f); setPropertyOptions(f); }); }, []);
  useEffect(() => {
    const timer = window.setTimeout(() => {
      const normalized = search.trim();
      const currentSearch = new URLSearchParams(window.location.search).get("search") ?? "";
      if (normalized !== currentSearch) updateParams({ search: normalized });
    }, 400);
    return () => window.clearTimeout(timer);
  }, [search]);
  useEffect(() => {
    const restore = () => {
      const restored = new URLSearchParams(window.location.search);
      const restoredActive = multiFromUrl(restored); const restoredFields = fieldsFromUrl(restored);
      setSearch(restored.get("search") ?? ""); setActive(restoredActive); setDraftActive(restoredActive); setFilterFields(restoredFields); setDraftFields(restoredFields); setQueryVersion((value) => value + 1);
    };
    window.addEventListener("popstate", restore); return () => window.removeEventListener("popstate", restore);
  }, []);
  useEffect(() => {
    if (tab === "settings" && settingsTab === "settings") {
      openGeneralSettings();
    }
  }, [tab, settingsTab]);
  const upload = async (file?: File) => {
    if (!file) return;
    setLoading(true);
    setUploadError(null);
    try {
      setMeta(await api.upload(file));
      reload();
    } catch (error) {
      setUploadError(
        error instanceof Error ? error.message : "Не удалось загрузить XML",
      );
    } finally {
      setLoading(false);
    }
  };
  const copy = (value?: string) =>
    value && navigator.clipboard.writeText(value);
  const closeSettingsPassword = () => {
    setSettingsPasswordOpen(false);
    setSettingsPassword("");
    setSettingsPasswordError(false);
  };
  const openSettings = () => {
    if (settingsUnlocked) {
      setTab("settings");
      return;
    }
    setSettingsPasswordOpen(true);
  };
  const unlockSettings = () => {
    if (settingsPassword !== SETTINGS_PASSWORD) {
      setSettingsPasswordError(true);
      return;
    }
    setSettingsUnlocked(true);
    closeSettingsPassword();
    setTab("settings");
  };
  const allSelected =
    products.length > 0 && selectedIds.length === products.length;
  const toggleSelected = (id: number) =>
    setSelectedIds((ids) =>
      ids.includes(id) ? ids.filter((item) => item !== id) : [...ids, id],
    );
  const toggleFilter = (key: string, value: string) =>
    setDraftActive((current) => {
      const values = current[key] ?? [];
      return {
        ...current,
        [key]: values.includes(value)
          ? values.filter((item) => item !== value)
          : [...values, value],
      };
    });
  const applyFilters = () => {
    const next = new URLSearchParams(window.location.search);
    next.delete("property");
    Object.keys(filterLabels).forEach((key) => {
      if (key.startsWith("property:")) {
        (draftActive[key] ?? []).forEach((value) => next.append("property", `${key.slice(9)}:${value}`));
        return;
      }
      const parameter = key === "product_type" ? "productType" : key;
      const values = draftActive[key] ?? [];
      if (values.length) next.set(parameter, serializeFilterValues(values)); else next.delete(parameter);
    });
    Object.entries(draftFields).forEach(([key, value]) => {
      if (value && value !== "all") next.set(key, value.trim()); else next.delete(key);
    });
    next.delete("page");
    setActive(draftActive); setFilterFields(draftFields); replaceCatalogParams(next); setFiltersOpen(false);
  };
  const applyFiltersOnEnter = (event: React.KeyboardEvent) => {
    if (event.key !== "Enter") return;
    event.preventDefault();
    applyFilters();
  };
  const resetFilters = () => {
    const emptyFields = fieldsFromUrl(new URLSearchParams());
    setDraftActive({}); setActive({}); setDraftFields(emptyFields); setFilterFields(emptyFields);
    const next = new URLSearchParams(window.location.search);
    [...Object.keys(labels), "productType", "property", ...Object.keys(emptyFields)].forEach((key) => next.delete(key));
    next.delete("page"); replaceCatalogParams(next);
  };
  const removeFilter = (key: string, value?: string) => {
    if (key in filterLabels) {
      const values = (active[key] ?? []).filter((item) => item !== value);
      const updated = { ...active, [key]: values }; setActive(updated); setDraftActive(updated);
      if (key.startsWith("property:")) {
        const next = new URLSearchParams(window.location.search); next.delete("property");
        Object.entries(updated).filter(([activeKey]) => activeKey.startsWith("property:")).forEach(([activeKey, activeValues]) => activeValues.forEach((item) => next.append("property", `${activeKey.slice(9)}:${item}`)));
        next.delete("page"); replaceCatalogParams(next);
      } else updateParams({ [key === "product_type" ? "productType" : key]: serializeFilterValues(values) });
    } else {
      const resetValue = key === "availability" ? "all" : ["inStockOnly", "excludeYyy", "onlyNew"].includes(key) ? "false" : "";
      const updated = { ...filterFields, [key]: resetValue };
      setFilterFields(updated); setDraftFields(updated); updateParams({ [key]: resetValue || null });
    }
  };
  const isActiveFilterField = ([key, value]: [string, string | undefined]) =>
    Boolean(value && value !== "all" && !(["inStockOnly", "excludeYyy", "onlyNew"].includes(key) && value === "false"));
  const activeConditionCount = Object.values(active).reduce((sum, values) => sum + values.length, 0) + Object.entries(filterFields).filter(isActiveFilterField).length;
  const searchableFilterLabels = new Set(["Раздел", "Производитель", "Бренд", "Материал", "Коллекция", "Штрихкод"]);
  const entriesForOrder = (options: Record<string, string[]>, order: string[]) => {
    const entries = Object.entries(options).map(([key, values]) => ({
      key,
      values,
      label: labels[key] ?? (key.startsWith("property:") ? key.slice("property:".length) : key),
    }));
    return order.flatMap((wantedLabel) => {
      const match = entries.find(({ label }) => label.toLocaleLowerCase("ru-RU") === wantedLabel.toLocaleLowerCase("ru-RU"));
      return match ? [match] : [];
    });
  };
  const mainFilterEntries = entriesForOrder(filters, mainFilterOrder);
  const propertyFilterEntries = entriesForOrder(propertyOptions, propertyFilterOrder);
  const openPropertyPicker = async () => {
    const dependentParams = new URLSearchParams();
    dependentParams.set("inStockOnly", draftFields.inStockOnly);
    mainFilterEntries.forEach(({ key }) => {
      const values = draftActive[key] ?? [];
      if (!values.length) return;
      if (key.startsWith("property:")) {
        values.forEach((value) => dependentParams.append("property", `${key.slice("property:".length)}:${value}`));
      } else {
        dependentParams.set(key === "product_type" ? "productType" : key, serializeFilterValues(values));
      }
    });
    setPropertyOptions(await api.filters(dependentParams));
    setPropertyPickerOpen(true);
  };
  const visibleFilterValues = (key: string, options = filters) => {
    const searchValue = (filterValueSearch[key] ?? "").trim().toLocaleLowerCase("ru-RU");
    return (options[key] ?? [])
      .filter((value) => !searchValue || value.toLocaleLowerCase("ru-RU").includes(searchValue))
      .slice(0, 100);
  };
  const productProperty = (product: ProductDetail, names: string[]) => {
    const normalizeName = (name: string) =>
      name.toLocaleLowerCase("ru-RU").replace(/[\s_-]+/g, "");
    const wanted = new Set(names.map(normalizeName));
    return product.properties.find(
      (property) => wanted.has(normalizeName(property.name)) && property.value?.trim(),
    );
  };
  const productPropertyValue = (product: ProductDetail, names: string[]) =>
    productProperty(product, names)?.value?.trim();
  const productPropertyFilter = (product: ProductDetail, names: string[]) => {
    const property = productProperty(product, names);
    return property ? `property:${property.name.trim()}` : undefined;
  };
  const paramsForDetailFilter = (key: string, value: string) => {
    const next = new URLSearchParams();
    if (filterFields.inStockOnly === "true") next.set("inStockOnly", "true");
    if (key.startsWith("property:")) {
      next.append("property", `${key.slice("property:".length)}:${value}`);
    } else {
      next.set(key === "product_type" ? "productType" : key, serializeFilterValues([value]));
    }
    return next;
  };
  const catalogFilterUrl = (key: string, value: string) => {
    const next = paramsForDetailFilter(key, value);
    const query = next.toString();
    return `${window.location.pathname}${query ? `?${query}` : ""}`;
  };
  const openCatalogFilter = (key: string, value: string) => {
    const next = paramsForDetailFilter(key, value);
    const nextActive = multiFromUrl(next);
    const nextFields = fieldsFromUrl(next);
    setDetail(null);
    setTab("catalog");
    setActive(nextActive);
    setDraftActive(nextActive);
    setFilterFields(nextFields);
    setDraftFields(nextFields);
    replaceCatalogParams(next);
  };
  const clickableDetailFilters: Record<string, string> = {
    Раздел: "section",
    "Вид товара": "product_type",
    Производитель: "manufacturer",
    Менеджер: "manager",
    Бренд: "brand",
    "Код маркировки": "property:Код маркировки",
    Коллекция: "property:Коллекция",
  };
  const renderDetailValue = (label: string, value: string, propertyFilter?: string) => {
    const filterKey = propertyFilter ?? clickableDetailFilters[label];
    if (!filterKey) return value;
    return (
      <Box
        component="a"
        href={catalogFilterUrl(filterKey, value)}
        onClick={(event) => {
          event.preventDefault();
          openCatalogFilter(filterKey, value);
        }}
        sx={{
          color: "primary.main",
          fontWeight: 700,
          textDecoration: "none",
          "&:hover": { textDecoration: "underline" },
        }}
      >
        {value}
      </Box>
    );
  };
  const changeSort = (field: string) => {
    const currentSort = params.get("sort");
    updateParams({ sort: field, order: currentSort === field && params.get("order") === "asc" ? "desc" : "asc" });
  };
  const toggleFilterGroup = (key: string) =>
    setOpenFilterGroups((current) => ({
      ...current,
      [key]: !current[key],
    }));
  const toggleAll = () =>
    setSelectedIds(allSelected ? [] : products.map((product) => product.id));
  const closeDeleteDialog = () => {
    setDeleteDialogOpen(false);
    setDeletePassword("");
    setDeletePasswordError(false);
  };
  const deleteSelected = async () => {
    if (!selectedIds.length) return;
    if (deletePassword !== DELETE_PASSWORD) {
      setDeletePasswordError(true);
      return;
    }
    await api.deleteProducts(selectedIds);
    closeDeleteDialog();
    reload();
  };
  const openExportDialog = async () => {
    setExportColumns(defaultExportColumns);
    setExportWarehouses(await api.warehouses());
    setExportDialogOpen(true);
  };
  const toggleExportColumn = (column: string) => {
    setExportColumns((current) =>
      current.includes(column) ? current.filter((item) => item !== column) : [...current, column],
    );
  };
  const downloadExcel = () => {
    const exportParams = new URLSearchParams(params);
    exportParams.delete("column");
    exportColumns.forEach((column) => exportParams.append("column", column));
    window.location.href = api.exportUrl("xlsx", exportParams);
    setExportDialogOpen(false);
  };
  const openLogs = async () => {
    setSettingsTab("logs");
    setLogs(await api.logs());
  };
  const openGeneralSettings = async () => {
    setSettingsTab("settings");
    setXmlServerForm(await api.xmlServerSettings());
    setAutoImportState(await api.autoImportState());
  };
  const openMappings = async () => {
    setSettingsTab("mappings");
    setWarehouses(await api.warehouses());
    setWarehouseCodes((await api.warehouseCodes()).codes);
    setProductTypes(await api.productTypes());
  };
  const openMailSettings = async () => {
    setSettingsTab("mail");
    setMailForm(await api.mailSettings());
  };
  const openScenarios = async () => {
    setSettingsTab("scenarios");
    setScenarioList(await api.notificationScenarios());
    setSelectedScenario(null);
    setScenarioForm(null);
  };
  const openAnalogSettings = async () => {
    setSettingsTab("analogs");
    setAnalogSettings(await api.analogSelectionSettings());
  };
  const openProduct = async (id: number) => {
    setAllAnalogsOpen(false);
    setDynamicAnalogs([]);
    setAnalogsLoading(true);
    setDetail(await api.product(id));
    try {
      setDynamicAnalogs(await api.productAnalogs(id));
    } finally {
      setAnalogsLoading(false);
    }
  };
  const openProductByBarcode = async (barcode: string) => {
    const result = await api.searchProducts(new URLSearchParams({
      barcode,
      inStockOnly: "false",
      excludeYyy: "false",
      pageSize: "20",
    }));
    const product = result.items[0];
    if (!product) return false;
    await openProduct(product.id);
    return true;
  };
  const openAllAnalogs = async () => {
    if (!detail) return;
    setAllAnalogs([]);
    setAllAnalogsOpen(true);
    setAllAnalogsLoading(true);
    try {
      setAllAnalogs(await api.productAnalogs(detail.id, true));
    } finally {
      setAllAnalogsLoading(false);
    }
  };
  const movePrimaryProperty = (index: number, direction: -1 | 1) => {
    if (!analogSettings) return;
    const target = index + direction;
    if (target < 0 || target >= analogSettings.primary_properties.length) return;
    const values = [...analogSettings.primary_properties];
    [values[index], values[target]] = [values[target], values[index]];
    setAnalogSettings({ ...analogSettings, primary_properties: values });
  };
  const openScenarioCard = async (code: string) => {
    setSelectedScenario(code);
    if (code === "monthly_promotion") setScenarioForm(await api.monthlyPromotionScenario());
  };
  const loadHistory = async (search = historySearch, status = historyStatus) => {
    if (!selectedScenario) return;
    setHistoryRows(await api.notificationHistory(selectedScenario, search, status));
  };
  const openWarehouseDialog = (warehouse?: Warehouse) => {
    setWarehouseForm(
      warehouse
        ? { id: warehouse.id, code: warehouse.code, name: warehouse.name }
        : { code: "", name: "" },
    );
    setWarehouseDialogOpen(true);
  };
  const saveWarehouse = async () => {
    if (!warehouseForm.code || !warehouseForm.name) return;
    if (warehouseForm.id)
      await api.updateWarehouse(warehouseForm.id, {
        code: warehouseForm.code,
        name: warehouseForm.name,
      });
    else
      await api.createWarehouse({
        code: warehouseForm.code,
        name: warehouseForm.name,
      });
    setWarehouseDialogOpen(false);
    await openMappings();
    reload();
  };
  const removeWarehouse = async (id: number) => {
    await api.deleteWarehouse(id);
    await openMappings();
    reload();
  };
  const openProductTypeDialog = (productType?: ProductType) => {
    setProductTypeForm(
      productType
        ? { id: productType.id, code: productType.code, name: productType.name }
        : { code: "", name: "" },
    );
    setProductTypeDialogOpen(true);
  };
  const saveProductType = async () => {
    if (!productTypeForm.code || !productTypeForm.name) return;
    if (productTypeForm.id)
      await api.updateProductType(productTypeForm.id, {
        code: productTypeForm.code,
        name: productTypeForm.name,
      });
    else
      await api.createProductType({
        code: productTypeForm.code,
        name: productTypeForm.name,
      });
    setProductTypeDialogOpen(false);
    await openMappings();
    reload();
  };
  const removeProductType = async (id: number) => {
    await api.deleteProductType(id);
    await openMappings();
    reload();
  };
  const visiblePrices = (product: Product) => product.prices;


  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <Box
        sx={{
          minHeight: "100vh",
          background:
            "radial-gradient(circle at top left, #e0f2fe 0, #f0f9ff 42%, #ffffff 100%)",
        }}
      >
        <AppBar
          position="sticky"
          color="transparent"
          elevation={0}
          sx={{
            backdropFilter: "blur(20px)",
            borderBottom: "1px solid",
            borderColor: alpha("#0284c7", 0.14),
          }}
        >
          {loading && <LinearProgress />}
        </AppBar>

        {tab === "catalog" && selectedIds.length > 0 && (
          <Button
            color="error"
            variant="contained"
            startIcon={<DeleteIcon />}
            onClick={() => setDeleteDialogOpen(true)}
            sx={{ position: "fixed", top: 16, right: 24, zIndex: (muiTheme) => muiTheme.zIndex.modal - 1 }}
          >
            Удалить выбранные ({selectedIds.length})
          </Button>
        )}

        {tab === "catalog" && <BarcodeScanner onDetected={openProductByBarcode} />}

        <Container maxWidth="xl" sx={{ py: { xs: 2, md: 4 } }}>
          {uploadError && (
            <Card sx={{ mb: 3 }}>
              <CardContent>
                <Typography color="error">{uploadError}</Typography>
              </CardContent>
            </Card>
          )}

          <Paper
            sx={{
              mb: 3,
              px: 1,
              bgcolor: alpha("#ffffff", 0.78),
              border: "1px solid rgba(2,132,199,.14)",
            }}
            elevation={0}
          >
            <Tabs
              value={tab}
              onChange={(_, value) => {
                if (value === "clients") {
                  window.location.href = clientsUrl;
                  return;
                }
                if (value === "settings") {
                  openSettings();
                  return;
                }
                setTab(value);
              }}
              textColor="primary"
              indicatorColor="primary"
              variant="scrollable"
            >
              <Tab value="catalog" label="Каталог" />
              <Tab value="clients" label="Контрагенты" />
              <Tab value="settings" label="Настройки" />
            </Tabs>
          </Paper>

          <Dialog open={settingsPasswordOpen} onClose={closeSettingsPassword} maxWidth="xs" fullWidth>
            <DialogTitle>Доступ к настройкам</DialogTitle>
            <DialogContent>
              <TextField
                autoFocus
                fullWidth
                type="password"
                label="Пароль"
                value={settingsPassword}
                error={settingsPasswordError}
                helperText={settingsPasswordError ? "Неверный пароль" : "Введите пароль для доступа к вкладке"}
                onChange={(event) => {
                  setSettingsPassword(event.target.value);
                  setSettingsPasswordError(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") unlockSettings();
                }}
                sx={{ mt: 1 }}
              />
            </DialogContent>
            <DialogActions>
              <Button onClick={closeSettingsPassword}>Отмена</Button>
              <Button variant="contained" onClick={unlockSettings}>Войти</Button>
            </DialogActions>
          </Dialog>

          <Dialog open={testMailOpen} onClose={() => setTestMailOpen(false)} maxWidth="xs" fullWidth>
            <DialogTitle>Тест уведомлений</DialogTitle>
            <DialogContent><TextField autoFocus fullWidth label="Email получателя" value={testEmail} onChange={(event) => setTestEmail(event.target.value)} sx={{ mt: 1 }} /></DialogContent>
            <DialogActions>
              <Button onClick={() => setTestMailOpen(false)}>Отмена</Button>
              <Button variant="contained" onClick={async () => { try { const result = await api.sendTestMail(testEmail); setMailMessage(result.message); setMailForm(await api.mailSettings()); } catch (error) { setMailMessage(error instanceof Error ? error.message : "Ошибка отправки"); } finally { setTestMailOpen(false); } }}>Отправить</Button>
            </DialogActions>
          </Dialog>

          <Dialog open={historyOpen} onClose={() => setHistoryOpen(false)} fullWidth maxWidth="lg">
            <DialogTitle>История уведомлений</DialogTitle>
            <DialogContent>
              <Stack direction={{ xs: "column", sm: "row" }} gap={1} sx={{ my: 1 }}>
                <TextField fullWidth label="Поиск по получателю" value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") loadHistory(); }} />
                <TextField select label="Статус" value={historyStatus} onChange={async (event) => { setHistoryStatus(event.target.value); await loadHistory(historySearch, event.target.value); }} sx={{ minWidth: 190 }}>
                  <MenuItem value="all">Все</MenuItem><MenuItem value="sent">Отправлено</MenuItem><MenuItem value="error">Ошибка</MenuItem>
                </TextField>
                <Button onClick={() => loadHistory()}>Найти</Button>
              </Stack>
              <TableContainer><Table size="small">
                <TableHead><TableRow><TableCell>Дата и время</TableCell><TableCell>Получатели</TableCell><TableCell>Тема</TableCell><TableCell>Текст письма</TableCell><TableCell>Статус</TableCell></TableRow></TableHead>
                <TableBody>{historyRows.map((row) => <TableRow key={row.id}>
                  <TableCell sx={{ whiteSpace: "nowrap" }}>{new Date(row.sent_at).toLocaleString("ru-RU")}</TableCell>
                  <TableCell>{row.recipients.join(", ")}</TableCell><TableCell>{row.subject}</TableCell>
                  <TableCell><Box sx={{ maxHeight: 220, overflow: "auto" }} dangerouslySetInnerHTML={{ __html: row.body_html }} /></TableCell>
                  <TableCell>{row.status === "sent" ? "Отправлено" : <><Typography color="error">Ошибка отправки</Typography><Typography variant="caption">{row.error_message}</Typography></>}</TableCell>
                </TableRow>)}</TableBody>
              </Table></TableContainer>
            </DialogContent>
            <DialogActions><Button onClick={() => setHistoryOpen(false)}>Закрыть</Button></DialogActions>
          </Dialog>

          <Dialog open={deleteDialogOpen} onClose={closeDeleteDialog} maxWidth="xs" fullWidth>
            <DialogTitle>Подтверждение удаления</DialogTitle>
            <DialogContent>
              <Typography sx={{ mb: 2 }}>
                Вы действительно хотите удалить выбранные товары ({selectedIds.length})? Это действие нельзя отменить.
              </Typography>
              <TextField
                autoFocus
                fullWidth
                type="password"
                label="Пароль"
                value={deletePassword}
                error={deletePasswordError}
                helperText={deletePasswordError ? "Неверный пароль" : "Введите пароль для подтверждения удаления"}
                onChange={(event) => {
                  setDeletePassword(event.target.value);
                  setDeletePasswordError(false);
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") deleteSelected();
                }}
              />
            </DialogContent>
            <DialogActions>
              <Button onClick={closeDeleteDialog}>Отмена</Button>
              <Button color="error" variant="contained" onClick={deleteSelected}>
                Подтвердить удаление
              </Button>
            </DialogActions>
          </Dialog>

          <Dialog open={exportDialogOpen} onClose={() => setExportDialogOpen(false)} maxWidth="sm" fullWidth>
            <DialogTitle>Выберите колонки для Excel</DialogTitle>
            <DialogContent>
              <Typography variant="h6" sx={{ mt: 1 }}>Основные</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" } }}>
                {exportMainColumns.map(([key, label]) => (
                  <FormControlLabel
                    key={key}
                    control={<Checkbox checked={exportColumns.includes(key)} onChange={() => toggleExportColumn(key)} />}
                    label={label}
                  />
                ))}
              </Box>
              <Divider sx={{ my: 2 }} />
              <Typography variant="h6">Цены</Typography>
              <Stack>
                {exportPriceColumns.map((price) => {
                  const key = `price:${price}`;
                  return <FormControlLabel key={key} control={<Checkbox checked={exportColumns.includes(key)} onChange={() => toggleExportColumn(key)} />} label={price} />;
                })}
              </Stack>
              <Divider sx={{ my: 2 }} />
              <Typography variant="h6">Остатки на складах</Typography>
              <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" } }}>
                {exportWarehouses.map((warehouse) => {
                  const key = `stock:${warehouse.code}`;
                  return <FormControlLabel key={key} control={<Checkbox checked={exportColumns.includes(key)} onChange={() => toggleExportColumn(key)} />} label={warehouse.name} />;
                })}
              </Box>
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setExportDialogOpen(false)}>Отмена</Button>
              <Button variant="contained" disabled={!exportColumns.length} onClick={downloadExcel}>Скачать Excel</Button>
            </DialogActions>
          </Dialog>

          {tab === "catalog" && (
            <Paper
              sx={{
                mb: 3,
                p: 1,
                bgcolor: alpha("#ffffff", 0.78),
                border: "1px solid rgba(2,132,199,.14)",
              }}
              elevation={0}
            >
              <Stack
                direction={{ xs: "column", md: "row" }}
                spacing={1}
                alignItems="stretch"
              >
                {!filtersOpen && (
                  <TextField
                    fullWidth
                    size="small"
                    placeholder="Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onClick={() => {
                      setDraftActive(active);
                      setDraftFields(filterFields);
                      setFiltersOpen(true);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") updateParams({ search: search.trim() });
                    }}
                    aria-label="Поиск товаров"
                    InputProps={{
                      startAdornment: <SearchIcon color="action" sx={{ mr: 1 }} />,
                      endAdornment: search ? (
                        <InputAdornment position="end">
                          <IconButton aria-label="Очистить поиск" onClick={() => { setSearch(""); updateParams({ search: null }); }}>
                            <CloseIcon />
                          </IconButton>
                        </InputAdornment>
                      ) : undefined,
                    }}
                    sx={{
                      flex: 1,
                      "& .MuiOutlinedInput-root": {
                        bgcolor: alpha("#ffffff", 0.86),
                        borderRadius: 999,
                      },
                    }}
                  />
                )}
              </Stack>
              <Collapse in={filtersOpen} unmountOnExit>
                <Paper
                  variant="outlined"
                  sx={{ mt: 1, p: { xs: 1.5, sm: 2 }, maxHeight: "70vh", overflowY: "auto" }}
                >
                  <Stack spacing={2} role="form" aria-label="Расширенный фильтр товаров">
                    <Stack direction="row" justifyContent="space-between" alignItems="center">
                      <Typography variant="h6">Фильтр товаров</Typography>
                      <IconButton aria-label="Закрыть фильтр" onClick={() => setFiltersOpen(false)}>
                        <CloseIcon />
                      </IconButton>
                    </Stack>
                    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", md: "repeat(3, 1fr)" }, gap: 1.5 }}>
                      <TextField autoFocus label="Поиск по коду" value={draftFields.code} onKeyDown={applyFiltersOnEnter} onChange={(event) => setDraftFields({ ...draftFields, code: event.target.value })} />
                      <TextField label="Поиск по артикулу" value={draftFields.article} onKeyDown={applyFiltersOnEnter} onChange={(event) => setDraftFields({ ...draftFields, article: event.target.value })} />
                      <TextField label="Поиск по наименованию" value={draftFields.name} onKeyDown={applyFiltersOnEnter} onChange={(event) => setDraftFields({ ...draftFields, name: event.target.value })} />
                    </Box>
                    <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
                      <FormControlLabel
                        control={<Switch checked={draftFields.inStockOnly !== "false"} onChange={(event) => setDraftFields({ ...draftFields, inStockOnly: event.target.checked ? "true" : "false" })} />}
                        label="Показывать только в наличии"
                      />
                      <FormControlLabel
                        control={<Switch checked={draftFields.excludeYyy !== "false"} onChange={(event) => setDraftFields({ ...draftFields, excludeYyy: event.target.checked ? "true" : "false" })} />}
                        label="Исключить категорию ЯЯЯ"
                      />
                    </Stack>
                    {mainFilterEntries.map(({ key, label }) => (
                      <Box key={key}>
                        <Button fullWidth onClick={() => toggleFilterGroup(key)} sx={{ justifyContent: "space-between" }}>
                          {label}
                          <Box component="span" aria-hidden>{openFilterGroups[key] ? "−" : "+"}</Box>
                        </Button>
                        <Collapse in={!!openFilterGroups[key]} unmountOnExit>
                          {searchableFilterLabels.has(label) && (
                            <TextField fullWidth size="small" label={`Поиск: ${label}`} value={filterValueSearch[key] ?? ""} onChange={(event) => setFilterValueSearch((current) => ({ ...current, [key]: event.target.value }))} sx={{ mt: 1 }} />
                          )}
                          <Stack direction="row" flexWrap="wrap" gap={1} sx={{ py: 1 }}>
                            {visibleFilterValues(key).map((value) => (
                              <Chip key={value} clickable label={value} color={(draftActive[key] ?? []).includes(value) ? "primary" : "default"} variant={(draftActive[key] ?? []).includes(value) ? "filled" : "outlined"} onClick={() => toggleFilter(key, value)} />
                            ))}
                            {visibleFilterValues(key).length === 0 && <Typography variant="body2" color="text.secondary">Значения не найдены</Typography>}
                          </Stack>
                        </Collapse>
                      </Box>
                    ))}
                    <Button variant="outlined" onClick={openPropertyPicker}>Подобрать по характеристикам</Button>
                    {meta.errors && <Typography color="error">Ошибки импорта: {meta.errors}</Typography>}
                    <Stack direction="row" spacing={1} flexWrap="wrap">
                      <Button variant="contained" onClick={applyFilters}>Применить</Button>
                      <Button onClick={resetFilters}>Сбросить</Button>
                      <Button onClick={() => setFiltersOpen(false)}>Закрыть</Button>
                    </Stack>
                  </Stack>
                </Paper>
              </Collapse>
            </Paper>
          )}

          {tab === "settings" && (
            <Card sx={{ maxWidth: 1000 }}>
              <CardContent>
                <Tabs
                  value={settingsTab}
                  onChange={(_, value) =>
                    value === "logs"
                      ? openLogs()
                      : value === "mappings"
                        ? openMappings()
                        : value === "mail"
                          ? openMailSettings()
                          : value === "scenarios"
                            ? openScenarios()
                            : value === "analogs"
                              ? openAnalogSettings()
                            : openGeneralSettings()
                  }
                  sx={{ mb: 2 }}
                >
                  <Tab value="settings" label="Общие" />
                  <Tab value="mappings" label="Сопоставления" />
                  <Tab value="mail" label="Почта" />
                  <Tab value="scenarios" label="Сценарии" />
                  <Tab value="analogs" label="Подбор аналогов" />
                  <Tab value="logs" label="Логи" />
                </Tabs>
                {settingsTab === "settings" && (
                  <Box>
                    <Typography variant="h6">Настройки</Typography>
                    <Button
                      variant="contained"
                      startIcon={<UploadFileIcon />}
                      component="label"
                      sx={{ mt: 2 }}
                    >
                      Загрузить XML
                      <input
                        hidden
                        type="file"
                        accept=".xml"
                        onChange={(event) => upload(event.target.files?.[0])}
                      />
                    </Button>
                    <Typography color="text.secondary" sx={{ mt: 1, mb: 2 }}>
                      Путь к скрипту обновления каталога на сервере. Нажмите на
                      иконку, чтобы скопировать значение.
                    </Typography>
                    <TextField
                      fullWidth
                      label="Скрипт обновления"
                      value={updateScriptPath}
                      InputProps={{
                        readOnly: true,
                        endAdornment: (
                          <InputAdornment position="end">
                            <IconButton
                              aria-label="Скопировать путь к скрипту обновления"
                              onClick={() => copy(updateScriptPath)}
                            >
                              <ContentCopyIcon />
                            </IconButton>
                          </InputAdornment>
                        ),
                      }}
                    />
                    <Divider sx={{ my: 3 }} />
                    <Button
                      fullWidth
                      onClick={() => setOpenSettingsGroups((current) => ({ ...current, xml: !current.xml }))}
                      sx={{ justifyContent: "space-between", fontSize: 18 }}
                    >
                      Подключение к серверу XML
                      <Box component="span" aria-hidden>{openSettingsGroups.xml ? "−" : "+"}</Box>
                    </Button>
                    <Collapse in={!!openSettingsGroups.xml} unmountOnExit>
                      {xmlServerForm && (
                        <Stack spacing={2} sx={{ mt: 2 }}>
                        <TextField
                          select
                          label="Протокол"
                          value={xmlServerForm.protocol}
                          onChange={(e) =>
                            setXmlServerForm({ ...xmlServerForm, protocol: e.target.value })
                          }
                        >
                          <MenuItem value="FTP">FTP</MenuItem>
                        </TextField>
                        <TextField
                          label="Хост"
                          value={xmlServerForm.host}
                          onChange={(e) =>
                            setXmlServerForm({ ...xmlServerForm, host: e.target.value })
                          }
                        />
                        <TextField
                          label="Порт"
                          type="number"
                          value={xmlServerForm.port}
                          onChange={(e) =>
                            setXmlServerForm({ ...xmlServerForm, port: Number(e.target.value) })
                          }
                        />
                        <TextField
                          label="Логин"
                          value={xmlServerForm.username}
                          onChange={(e) =>
                            setXmlServerForm({ ...xmlServerForm, username: e.target.value })
                          }
                        />
                        <TextField
                          label="Пароль"
                          type="password"
                          value={xmlServerForm.password}
                          onChange={(e) =>
                            setXmlServerForm({ ...xmlServerForm, password: e.target.value })
                          }
                        />
                        <TextField
                          label="Каталог для XML"
                          value={xmlServerForm.xml_dir}
                          onChange={(e) =>
                            setXmlServerForm({ ...xmlServerForm, xml_dir: e.target.value })
                          }
                        />
                        <TextField
                          label="Количество попыток подключения"
                          type="number"
                          value={xmlServerForm.connection_attempts}
                          inputProps={{ min: 1, max: 10 }}
                          onChange={(e) => setXmlServerForm({ ...xmlServerForm, connection_attempts: Number(e.target.value) })}
                        />
                        <TextField
                          label="Задержка между попытками (секунды)"
                          type="number"
                          value={xmlServerForm.retry_delay_seconds}
                          inputProps={{ min: 0, max: 60 }}
                          onChange={(e) => setXmlServerForm({ ...xmlServerForm, retry_delay_seconds: Number(e.target.value) })}
                        />
                        <Stack direction="row" gap={1} flexWrap="wrap">
                          <Button
                            variant="contained"
                            onClick={async () => {
                              const saved = await api.updateXmlServerSettings(xmlServerForm);
                              setXmlServerForm(saved);
                            }}
                          >
                            Сохранить подключение
                          </Button>
                          <Button
                            variant="outlined"
                            onClick={async () => {
                              await api.updateXmlServerSettings(xmlServerForm);
                              const result = await api.testXmlServerSettings();
                              setFtpTestMessage(result.message);
                            }}
                          >
                            Проверить подключение
                          </Button>
                        </Stack>
                        {ftpTestMessage && (
                          <Typography sx={{ whiteSpace: "pre-line" }}>{ftpTestMessage}</Typography>
                        )}
                        </Stack>
                      )}
                    </Collapse>
                    <Divider sx={{ my: 3 }} />
                    <Typography variant="h6">Автоматическая загрузка XML</Typography>
                    <Stack direction="row" gap={1} flexWrap="wrap" sx={{ mt: 2 }}>
                      <Button
                        variant="contained"
                        onClick={async () => {
                          const result = await api.runAutoImportNow();
                          setManualImportMessage(
                            result.started
                              ? "Принудительный импорт XML запущен."
                              : "Импорт уже выполняется.",
                          );
                          setAutoImportState(await api.autoImportState());
                        }}
                      >
                        Запустить импорт
                      </Button>
                    </Stack>
                    {manualImportMessage && (
                      <Typography sx={{ mt: 1 }}>{manualImportMessage}</Typography>
                    )}
                    <Typography fontWeight={800} sx={{ mt: 2 }}>
                      Статус автозагрузки
                    </Typography>
                    <Typography>
                      {autoImportState?.is_running
                        ? "🟢 Работает"
                        : autoImportState?.status === "error"
                          ? "⚠ Ошибка"
                          : autoImportState?.status === "stopped"
                            ? "🔴 Остановлена"
                            : "🟢 Работает"}
                    </Typography>
                    <Typography fontWeight={800} sx={{ mt: 2 }}>
                      Последняя автозагрузка
                    </Typography>
                    {autoImportState?.last_run_at ? (
                      <Stack spacing={0.5} sx={{ mt: 1 }}>
                        <Typography>Дата: {autoImportState.last_run_at}</Typography>
                        <Typography>Статус: {autoImportState.status === "error" ? "Ошибка" : "Успешно"}</Typography>
                        <Typography>Обработано файлов: {autoImportState.processed_files}</Typography>
                        <Typography>Успешно: {autoImportState.successful_files}</Typography>
                        <Typography>Ошибок: {autoImportState.failed_files}</Typography>
                        {autoImportState.last_error && (
                          <Typography sx={{ whiteSpace: "pre-line" }}>Причина: {autoImportState.last_error}</Typography>
                        )}
                      </Stack>
                    ) : (
                      <Typography sx={{ mt: 1 }}>Автозагрузка еще не выполнялась.</Typography>
                    )}
                  </Box>
                )}
                {settingsTab === "mail" && mailForm && (
                  <Stack spacing={2}>
                    <Typography variant="h6">Почта</Typography>
                    <Typography>Статус подключения: {mailForm.connection_status === "connected" ? "Подключено" : mailForm.connection_status === "error" ? "Ошибка" : "Нет соединения"}</Typography>
                    <Typography>Последнее успешное соединение: {mailForm.last_success_at ?? "—"}</Typography>
                    <Typography>Последнее отправленное письмо: {mailForm.last_sent_at ?? "—"}</Typography>
                    {mailForm.last_error && <Typography color="error">{mailForm.last_error}</Typography>}
                    <TextField label="SMTP сервер" value={mailForm.smtp_host} onChange={(event) => setMailForm({ ...mailForm, smtp_host: event.target.value })} />
                    <TextField label="SMTP порт" type="number" value={mailForm.smtp_port} onChange={(event) => setMailForm({ ...mailForm, smtp_port: Number(event.target.value) })} />
                    <TextField select label="Шифрование" value={mailForm.encryption} onChange={(event) => setMailForm({ ...mailForm, encryption: event.target.value as MailSetting["encryption"] })}>
                      <MenuItem value="none">Без шифрования</MenuItem><MenuItem value="starttls">STARTTLS</MenuItem><MenuItem value="ssl">SSL/TLS</MenuItem>
                    </TextField>
                    <TextField label="Логин" value={mailForm.username} onChange={(event) => setMailForm({ ...mailForm, username: event.target.value })} />
                    <TextField label={mailForm.password_configured ? "Пароль (оставьте пустым, чтобы не менять)" : "Пароль"} type="password" value={mailForm.password ?? ""} onChange={(event) => setMailForm({ ...mailForm, password: event.target.value })} />
                    <TextField label="Имя отправителя" value={mailForm.sender_name} onChange={(event) => setMailForm({ ...mailForm, sender_name: event.target.value })} />
                    <TextField label="Email отправителя" value={mailForm.sender_email} onChange={(event) => setMailForm({ ...mailForm, sender_email: event.target.value })} />
                    <Stack direction="row" gap={1} flexWrap="wrap">
                      <Button variant="contained" onClick={async () => { const saved = await api.updateMailSettings(mailForm); setMailForm(saved); setMailMessage(saved.connection_status === "connected" ? "Настройки сохранены, подключение проверено." : saved.last_error ?? "Не удалось подключиться."); }}>Проверять соединение и сохранить</Button>
                      <Button variant="outlined" onClick={() => setTestMailOpen(true)}>Тест уведомлений</Button>
                    </Stack>
                    {mailMessage && <Typography>{mailMessage}</Typography>}
                  </Stack>
                )}
                {settingsTab === "scenarios" && (
                  <Stack spacing={2}>
                    <Typography variant="h6">Сценарии</Typography>
                    {!selectedScenario && scenarioList.map((scenario) => (
                      <Paper key={scenario.code} variant="outlined" onClick={() => openScenarioCard(scenario.code)} sx={{ p: 2, cursor: "pointer" }}>
                        <Stack direction="row" alignItems="center" justifyContent="space-between">
                          <Typography fontWeight={800}>{scenario.name}</Typography>
                          <Switch checked={scenario.enabled} onClick={(event) => event.stopPropagation()} onChange={async (event) => { const updated = await api.toggleNotificationScenario(scenario.code, event.target.checked); setScenarioList((current) => current.map((item) => item.code === updated.code ? updated : item)); }} />
                        </Stack>
                      </Paper>
                    ))}
                    {selectedScenario === "monthly_promotion" && scenarioForm && <>
                      <Button onClick={() => { setSelectedScenario(null); setScenarioForm(null); }}>← К списку сценариев</Button>
                      <Typography variant="h6">Акция месяца</Typography>
                      <TextField label="Время отправки" type="time" value={scenarioForm.send_time} onChange={(event) => setScenarioForm({ ...scenarioForm, send_time: event.target.value })} InputLabelProps={{ shrink: true }} />
                      <Typography fontWeight={700}>Получатели</Typography>
                      {scenarioForm.recipients.map((email, index) => (
                        <Stack key={index} direction="row" gap={1}>
                          <TextField fullWidth label={`Email ${index + 1}`} value={email} onChange={(event) => setScenarioForm({ ...scenarioForm, recipients: scenarioForm.recipients.map((item, itemIndex) => itemIndex === index ? event.target.value : item) })} />
                          <Button color="error" onClick={() => setScenarioForm({ ...scenarioForm, recipients: scenarioForm.recipients.filter((_, itemIndex) => itemIndex !== index) })}>Удалить</Button>
                        </Stack>
                      ))}
                      <Button variant="outlined" onClick={() => setScenarioForm({ ...scenarioForm, recipients: [...scenarioForm.recipients, ""] })}>Добавить получателя</Button>
                      <Stack direction="row" gap={1} flexWrap="wrap">
                        <Button variant="contained" onClick={async () => setScenarioForm(await api.updateMonthlyPromotionScenario(scenarioForm))}>Сохранить</Button>
                        <Button variant="outlined" onClick={async () => setScenarioResult(await api.runMonthlyPromotion())}>Отправить сейчас</Button>
                        <Button onClick={async () => setScenarioResult(await api.previewMonthlyPromotion())}>Предпросмотр</Button>
                        <Button onClick={async () => { setHistoryOpen(true); await loadHistory(); }}>История уведомлений</Button>
                      </Stack>
                      {scenarioResult && <Typography>Статус: {scenarioResult.status}; изменений: {scenarioResult.changes}; писем: {scenarioResult.sent}</Typography>}
                      {scenarioResult?.html && <Paper variant="outlined" sx={{ p: 2 }} dangerouslySetInnerHTML={{ __html: scenarioResult.html }} />}
                    </>}
                  </Stack>
                )}
                {settingsTab === "analogs" && analogSettings && (
                  <Stack spacing={2}>
                    <Typography variant="h6">Подбор аналогов</Typography>
                    <Typography color="text.secondary">
                      Порядок основных характеристик определяет их вес при расчёте похожести.
                      Остальные характеристики не участвуют в расчёте процента совпадения.
                    </Typography>
                    <Typography fontWeight={800}>Основные характеристики</Typography>
                    <Stack spacing={1}>
                      {analogSettings.primary_properties.map((property, index) => (
                        <Paper key={property} variant="outlined" sx={{ p: 1 }}>
                          <Stack direction="row" alignItems="center" gap={1}>
                            <Typography sx={{ flex: 1 }}>{index + 1}. {property}</Typography>
                            <Button size="small" disabled={index === 0} onClick={() => movePrimaryProperty(index, -1)}>Выше</Button>
                            <Button size="small" disabled={index === analogSettings.primary_properties.length - 1} onClick={() => movePrimaryProperty(index, 1)}>Ниже</Button>
                            <Button size="small" color="error" onClick={() => setAnalogSettings({ ...analogSettings, primary_properties: analogSettings.primary_properties.filter((item) => item !== property) })}>Убрать</Button>
                          </Stack>
                        </Paper>
                      ))}
                    </Stack>
                    <TextField
                      select
                      label="Добавить характеристику"
                      value=""
                      onChange={(event) => setAnalogSettings({ ...analogSettings, primary_properties: [...analogSettings.primary_properties, event.target.value] })}
                    >
                      <MenuItem value="" disabled>Выберите характеристику</MenuItem>
                      {analogSettings.available_properties.filter((item) => !analogSettings.primary_properties.includes(item)).map((property) => (
                        <MenuItem key={property} value={property}>{property}</MenuItem>
                      ))}
                    </TextField>
                    <TextField label="Минимальный процент похожести" type="number" inputProps={{ min: 0, max: 100 }} value={analogSettings.minimum_similarity} onChange={(event) => setAnalogSettings({ ...analogSettings, minimum_similarity: Number(event.target.value) })} />
                    <TextField label="Максимальное количество аналогов" type="number" inputProps={{ min: 1, max: 50 }} value={analogSettings.maximum_analogs} onChange={(event) => setAnalogSettings({ ...analogSettings, maximum_analogs: Number(event.target.value) })} />
                    <Button variant="contained" onClick={async () => setAnalogSettings(await api.updateAnalogSelectionSettings(analogSettings))}>Сохранить</Button>
                  </Stack>
                )}
                {settingsTab === "mappings" && (
                  <Box>
                    <Button
                      fullWidth
                      onClick={() => setOpenSettingsGroups((current) => ({ ...current, warehouses: !current.warehouses }))}
                      sx={{ justifyContent: "space-between", fontSize: 18 }}
                    >
                      Склады
                      <Box component="span" aria-hidden>{openSettingsGroups.warehouses ? "−" : "+"}</Box>
                    </Button>
                    <Collapse in={!!openSettingsGroups.warehouses} unmountOnExit>
                      <Box sx={{ mt: 2 }}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                      sx={{ mb: 2 }}
                    >
                      <Box>
                        <Typography color="text.secondary">
                          Задайте имя для кода склада из XML, чтобы в карточке
                          товара показывалось понятное название.
                        </Typography>
                      </Box>
                      <Button
                        variant="contained"
                        onClick={() => openWarehouseDialog()}
                      >
                        Добавить склад
                      </Button>
                    </Stack>
                    <TableContainer>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>Код</TableCell>
                            <TableCell>Имя</TableCell>
                            <TableCell align="right">Действия</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {warehouses.map((warehouse) => (
                            <TableRow key={warehouse.id}>
                              <TableCell>{warehouse.code}</TableCell>
                              <TableCell>{warehouse.name}</TableCell>
                              <TableCell align="right">
                                <IconButton
                                  aria-label="Редактировать склад"
                                  onClick={() => openWarehouseDialog(warehouse)}
                                >
                                  <EditIcon />
                                </IconButton>
                                <IconButton
                                  aria-label="Удалить склад"
                                  color="error"
                                  onClick={() => removeWarehouse(warehouse.id)}
                                >
                                  <DeleteIcon />
                                </IconButton>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                      </Box>
                    </Collapse>
                    <Divider sx={{ my: 3 }} />
                    <Button
                      fullWidth
                      onClick={() => setOpenSettingsGroups((current) => ({ ...current, productTypes: !current.productTypes }))}
                      sx={{ justifyContent: "space-between", fontSize: 18 }}
                    >
                      Виды товаров
                      <Box component="span" aria-hidden>{openSettingsGroups.productTypes ? "−" : "+"}</Box>
                    </Button>
                    <Collapse in={!!openSettingsGroups.productTypes} unmountOnExit>
                      <Box sx={{ mt: 2 }}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                      sx={{ mb: 2 }}
                    >
                      <Box>
                        <Typography color="text.secondary">
                          Задайте наименование для кода вида товара из XML, чтобы в карточке товара показывалось понятное название.
                        </Typography>
                      </Box>
                      <Button
                        variant="contained"
                        onClick={() => openProductTypeDialog()}
                        sx={{ whiteSpace: "nowrap" }}
                      >
                        Добавить вид
                      </Button>
                    </Stack>
                    <TableContainer>
                      <Table size="small">
                        <TableHead>
                          <TableRow>
                            <TableCell>Вид товара</TableCell>
                            <TableCell>Код</TableCell>
                            <TableCell align="right">Действия</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {productTypes.map((productType) => (
                            <TableRow key={productType.id}>
                              <TableCell>{productType.name}</TableCell>
                              <TableCell>{productType.code}</TableCell>
                              <TableCell align="right">
                                <IconButton
                                  aria-label="Редактировать вид товара"
                                  onClick={() => openProductTypeDialog(productType)}
                                >
                                  <EditIcon />
                                </IconButton>
                                <IconButton
                                  aria-label="Удалить вид товара"
                                  color="error"
                                  onClick={() => removeProductType(productType.id)}
                                >
                                  <DeleteIcon />
                                </IconButton>
                              </TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                      </Box>
                    </Collapse>
                  </Box>
                )}
                {settingsTab === "logs" && (
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Дата</TableCell>
                          <TableCell>Уровень</TableCell>
                          <TableCell>Этап</TableCell>
                          <TableCell>Тип ошибки</TableCell>
                          <TableCell>Сообщение</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {logs.filter((log) => log.level === "error").map((log) => (
                          <React.Fragment key={log.id}>
                            <TableRow
                              hover={!!log.traceback}
                              onClick={() =>
                                log.traceback &&
                                setExpandedLogId((current) =>
                                  current === log.id ? null : log.id,
                                )
                              }
                              sx={{ cursor: log.traceback ? "pointer" : "default" }}
                            >
                              <TableCell>
                                {formatMoscowDate(log.created_at)}
                              </TableCell>
                              <TableCell>
                                <Chip
                                  size="small"
                                  color={
                                    log.level === "error"
                                      ? "error"
                                      : log.level === "warning"
                                        ? "warning"
                                        : "primary"
                                  }
                                  label={log.level}
                                />
                              </TableCell>
                              <TableCell>{getLogStage(log)}</TableCell>
                              <TableCell>{log.error_type ?? "—"}</TableCell>
                              <TableCell sx={{ whiteSpace: "pre-line" }}>
                                {log.message}
                                {log.traceback && (
                                  <Typography color="primary" variant="caption" display="block">
                                    {expandedLogId === log.id
                                      ? "Скрыть traceback"
                                      : "Показать traceback"}
                                  </Typography>
                                )}
                              </TableCell>
                            </TableRow>
                            {expandedLogId === log.id && log.traceback && (
                              <TableRow>
                                <TableCell colSpan={5}>
                                  <Paper variant="outlined" sx={{ p: 2, bgcolor: "#f8fafc" }}>
                                    <Typography component="pre" sx={{ m: 0, whiteSpace: "pre-wrap" }}>
                                      {log.traceback}
                                    </Typography>
                                  </Paper>
                                </TableCell>
                              </TableRow>
                            )}
                          </React.Fragment>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </CardContent>
            </Card>
          )}

          {tab === "catalog" && (
            <Stack spacing={2}>
              {activeConditionCount > 0 && (
                <Paper variant="outlined" sx={{ p: 1.5 }}>
                  <Stack direction="row" gap={1} flexWrap="wrap" alignItems="center">
                    <Typography variant="body2" fontWeight={700}>Активные условия:</Typography>
                    {Object.entries(active).flatMap(([key, values]) => values.map((value) => (
                      <Chip key={`${key}-${value}`} label={`${filterLabel(key)}: ${value}`} onDelete={() => removeFilter(key, value)} />
                    )))}
                    {Object.entries(filterFields).filter(isActiveFilterField).map(([key, value]) => (
                      <Chip key={key} label={`${filterFieldLabels[key as keyof FilterFields]}: ${value === "in_stock" ? "В наличии" : value === "out_of_stock" ? "Нет в наличии" : value === "true" ? "Да" : value}`} onDelete={() => removeFilter(key)} />
                    ))}
                    <Button size="small" onClick={resetFilters}>Очистить все</Button>
                  </Stack>
                </Paper>
              )}
              {catalogError && (
                <Paper variant="outlined" sx={{ p: 2 }}>
                  <Typography color="error">{catalogError}</Typography>
                  <Button startIcon={<RefreshIcon />} onClick={reload}>Повторить</Button>
                </Paper>
              )}
              <Stack direction="row" justifyContent="space-between" alignItems="center" spacing={2}>
                <Typography color="text.secondary" fontWeight={700}>
                  Найдено товаров: {pagination.totalItems}
                </Typography>
                <Button onClick={openExportDialog} sx={{ whiteSpace: "nowrap" }}>Скачать Excel</Button>
              </Stack>
              <TableContainer component={Card} sx={{ position: "relative" }}>
                {loading && <LinearProgress />}
                <Table aria-label="Список товаров">
                  <TableHead><TableRow>
                    <TableCell padding="checkbox"><Checkbox aria-label="Выбрать все товары на странице" checked={allSelected} indeterminate={selectedIds.length > 0 && !allSelected} onChange={toggleAll} /></TableCell>
                    <TableCell>Фото</TableCell>
                    {[ ["name", "Наименование"], ["article", "Артикул"], ["code", "Код"] ].map(([field, label]) => (
                      <TableCell key={field}><TableSortLabel active={params.get("sort") === field} direction={params.get("sort") === field && params.get("order") === "desc" ? "desc" : "asc"} onClick={() => changeSort(field)}>{label}</TableSortLabel></TableCell>
                    ))}
                    <TableCell align="right"><TableSortLabel active={params.get("sort") === "price"} direction={params.get("sort") === "price" && params.get("order") === "desc" ? "desc" : "asc"} onClick={() => changeSort("price")}>Цена</TableSortLabel></TableCell>
                    <TableCell align="right"><TableSortLabel active={params.get("sort") === "quantity"} direction={params.get("sort") === "quantity" && params.get("order") === "desc" ? "desc" : "asc"} onClick={() => changeSort("quantity")}>Количество Авиаторов</TableSortLabel></TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {!loading && products.length === 0 && <TableRow><TableCell colSpan={7} align="center" sx={{ py: 8 }}><Typography variant="h6">{activeConditionCount || search.trim() ? "По заданным условиям товары не найдены" : "Каталог пока пуст"}</Typography><Typography color="text.secondary">{activeConditionCount || search.trim() ? "Попробуйте изменить или сбросить фильтры" : "Загрузите XML-файл, чтобы добавить товары"}</Typography></TableCell></TableRow>}
                    {products.map((p) => (
                      <TableRow hover key={p.id} selected={selectedIds.includes(p.id)} onClick={() => openProduct(p.id)} sx={{ cursor: "pointer" }}>
                        <TableCell padding="checkbox"><Checkbox aria-label={`Выбрать ${p.name}`} checked={selectedIds.includes(p.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggleSelected(p.id)} /></TableCell>
                        <TableCell>
                          {p.images[0] ? (
                            <Box sx={{ position: "relative", width: 56, height: 56 }}>
                              <Box component="img" src={p.images[0].url} alt={p.name} sx={{ width: 56, height: 56, objectFit: "contain", borderRadius: 2, bgcolor: "#e0f2fe" }} />
                              {p.is_new && (
                                <Tooltip title="Новинка" arrow>
                                  <Box
                                    component="span"
                                    aria-label="Новинка"
                                    sx={{ position: "absolute", top: -3, right: -3, width: 12, height: 12, borderRadius: "50%", bgcolor: "#facc15", border: "2px solid #fff", boxShadow: "0 2px 5px rgba(15,23,42,.35)" }}
                                  />
                                </Tooltip>
                              )}
                            </Box>
                          ) : "—"}
                        </TableCell>
                        <TableCell><Typography>{p.name}</Typography></TableCell><TableCell>{p.article ?? "—"}</TableCell><TableCell>{p.code}</TableCell>
                        <TableCell align="right" sx={{ minWidth: 180 }}>{visiblePrices(p).length ? visiblePrices(p).map((price) => <Typography key={price.price_type} variant="body2" sx={{ whiteSpace: "nowrap" }}>{price.price_type}: {price.value} руб.</Typography>) : "—"}</TableCell>
                        <TableCell align="right">{p.quantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <TablePagination component="div" count={pagination.totalItems} page={Math.max(0, pagination.page - 1)} onPageChange={(_, page) => updateParams({ page: page + 1 }, false)} rowsPerPage={pagination.pageSize} onRowsPerPageChange={(event) => updateParams({ pageSize: event.target.value })} rowsPerPageOptions={[20, 50, 100]} labelRowsPerPage="Строк на странице" labelDisplayedRows={({ from, to, count }) => `${from}–${to} из ${count}`} />
              </TableContainer>
            </Stack>
          )}
        </Container>

        <Dialog
          open={propertyPickerOpen}
          onClose={() => setPropertyPickerOpen(false)}
          fullWidth
          maxWidth="md"
        >
          <DialogTitle>Подобрать по характеристикам</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
              {propertyFilterEntries.length === 0 && (
                <Typography color="text.secondary">
                  Для товаров, выбранных основными фильтрами, дополнительные свойства не найдены.
                </Typography>
              )}
              {propertyFilterEntries.map(({ key, label }) => (
                <Box key={key}>
                  <Button
                    fullWidth
                    onClick={() => setOpenCharacteristicGroups((current) => ({
                      ...current,
                      [key]: !current[key],
                    }))}
                    sx={{ justifyContent: "space-between" }}
                  >
                    {label}
                    <Box component="span" aria-hidden>
                      {openCharacteristicGroups[key] ? "−" : "+"}
                    </Box>
                  </Button>
                  <Collapse in={!!openCharacteristicGroups[key]} unmountOnExit>
                    <Stack direction="row" flexWrap="wrap" gap={1} sx={{ py: 1 }}>
                      {visibleFilterValues(key, propertyOptions).map((value) => (
                        <Chip
                          key={value}
                          clickable
                          label={value}
                          color={(draftActive[key] ?? []).includes(value) ? "primary" : "default"}
                          variant={(draftActive[key] ?? []).includes(value) ? "filled" : "outlined"}
                          onClick={() => toggleFilter(key, value)}
                        />
                      ))}
                    </Stack>
                  </Collapse>
                </Box>
              ))}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setPropertyPickerOpen(false)}>Готово</Button>
          </DialogActions>
        </Dialog>
        <Drawer
          anchor="right"
          open={!!detail}
          onClose={() => { setDetail(null); setDynamicAnalogs([]); setAnalogReason(null); }}
          PaperProps={{
            sx: { borderTopLeftRadius: 28, borderBottomLeftRadius: 28 },
          }}
        >
          <Box sx={{ width: { xs: "100vw", sm: 620 }, p: 3 }}>
            {detail && (
              <Stack spacing={2}>
                <Typography variant="h5" fontWeight={900}>
                  {detail.name}
                </Typography>
                {detail.images.length ? (
                  <Stack spacing={1.25}>
                    <Box
                      component="img"
                      src={detail.images[0].url}
                      alt={detail.name}
                      onClick={() => setImagePreviewUrl(detail.images[0].url)}
                      sx={{
                        width: "100%",
                        maxHeight: 260,
                        objectFit: "contain",
                        borderRadius: 4,
                        bgcolor: "#e0f2fe",
                        cursor: "zoom-in",
                      }}
                    />
                    {detail.images.length > 1 && (
                      <Stack direction="row" gap={1} flexWrap="wrap">
                        {detail.images.map((image) => (
                          <Box
                            component="img"
                            key={image.order}
                            src={image.url}
                            alt={`${detail.name} — фото ${image.order}`}
                            onClick={() => setImagePreviewUrl(image.url)}
                            sx={{
                              width: 64,
                              height: 64,
                              objectFit: "contain",
                              borderRadius: 2,
                              bgcolor: "#e0f2fe",
                              cursor: "zoom-in",
                              border: "1px solid rgba(2,132,199,.18)",
                            }}
                          />
                        ))}
                      </Stack>
                    )}
                  </Stack>
                ) : (
                  <Paper
                    variant="outlined"
                    sx={{
                      height: 180,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      bgcolor: "#e0f2fe",
                      color: "text.secondary",
                    }}
                  >
                    <Typography>Изображение отсутствует</Typography>
                  </Paper>
                )}
                {detail.stocks.length > 0 && (
                  <>
                    <Typography fontWeight={800}>Остатки по складам</Typography>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>Склад</TableCell>
                          <TableCell align="right">Остаток</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {detail.stocks.map((s) => (
                          <TableRow key={s.warehouse}>
                            <TableCell>{s.warehouse_name ?? s.warehouse}</TableCell>
                            <TableCell align="right">{s.quantity}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </>
                )}
                <Paper variant="outlined" sx={{ p: 2 }}>
                  {[
                    ["Код", detail.code],
                    ["Артикул", detail.article],
                    ["Раздел", detail.section],
                    ["Вид товара", detail.product_type_name ?? detail.product_type],
                    ["Производитель", detail.manufacturer],
                    ["Менеджер", detail.manager],
                    ["Бренд", detail.brand],
                    ["Код маркировки", productPropertyValue(detail, ["Код маркировки"]), productPropertyFilter(detail, ["Код маркировки"])],
                    ["Коллекция", productPropertyValue(detail, ["Коллекция"]), productPropertyFilter(detail, ["Коллекция"])],
                    ["Материал", detail.material],
                    ["Цвет", detail.color],
                    ["Сертификат", detail.certificate],
                    ["Штрихкоды", detail.barcodes.map((b) => b.value).join(", ")],
                  ]
                    .filter(([, value]) => value)
                    .map(([label, value, propertyFilter]) => {
                      const characteristicLabel = String(label);
                      return (
                        <Typography key={characteristicLabel}>
                          <Box component="span" fontWeight={800}>
                            {characteristicLabel}:
                          </Box>{" "}
                          {renderDetailValue(characteristicLabel, String(value), propertyFilter)}
                        </Typography>
                      );
                    })}
                </Paper>
                <Paper
                  variant="outlined"
                  sx={{ p: 2, bgcolor: (currentTheme) => alpha(currentTheme.palette.primary.main, 0.04) }}
                >
                  <Stack spacing={1}>
                    <Box>
                      <Typography variant="caption" color="text.secondary" fontWeight={700}>
                        Дата появления товара:
                      </Typography>
                      <Typography>{detail.created_at}</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary" fontWeight={700}>
                        Новинка:
                      </Typography>
                      <Typography>{detail.is_new ? "Да" : "Нет"}</Typography>
                    </Box>
                    <Box>
                      <Typography variant="caption" color="text.secondary" fontWeight={700}>
                        Дата обновления:
                      </Typography>
                      <Typography>{detail.updated_at}</Typography>
                    </Box>
                  </Stack>
                </Paper>
                {detail.properties.some((p) =>
                  p.name === "Вид товара" || p.name === "ВидТовара"
                    ? Boolean(detail.product_type_name ?? p.value)
                    : Boolean(p.value),
                ) && (
                  <>
                    <Typography fontWeight={800}>Характеристики</Typography>
                    {detail.properties
                      .map((p) => ({
                        ...p,
                        displayValue:
                          p.name === "Вид товара" || p.name === "ВидТовара"
                            ? detail.product_type_name ?? p.value
                            : p.value,
                      }))
                      .filter((p) => p.displayValue)
                      .map((p, index) => (
                        <Typography key={`${p.property_code ?? p.name}-${index}`}>
                          <Box component="span" fontWeight={800}>
                            {p.name}:
                          </Box>{" "}
                          {p.displayValue}
                        </Typography>
                      ))}
                  </>
                )}
                {detail.prices.length > 0 && (
                  <>
                    <Typography fontWeight={800}>Цены</Typography>
                    {detail.prices.map((p) => (
                      <Typography key={p.price_type} sx={{ whiteSpace: "nowrap" }}>
                        {p.price_type}: {p.value} руб.
                      </Typography>
                    ))}
                  </>
                )}
                <>
                  <Stack direction="row" justifyContent="space-between" alignItems="center">
                    <Typography fontWeight={800}>Аналоги</Typography>
                    {!analogsLoading && (
                      <Button variant="text" size="small" onClick={openAllAnalogs}>Смотреть все</Button>
                    )}
                  </Stack>
                  {analogsLoading && <LinearProgress />}
                  {!analogsLoading && dynamicAnalogs.length === 0 && (
                    <Typography color="text.secondary">Подходящие аналоги не найдены</Typography>
                  )}
                  {dynamicAnalogs.length > 0 && (
                    <Stack direction="row" gap={1.5} sx={{ overflowX: "auto", pb: 1 }}>
                      {dynamicAnalogs.map((analog) => (
                        <Card key={analog.id} variant="outlined" sx={{ minWidth: 210, maxWidth: 210, flex: "0 0 auto" }}>
                          <CardContent>
                            <Box
                              onClick={() => openProduct(analog.id)}
                              sx={{ cursor: "pointer" }}
                            >
                              {analog.image_url ? (
                                <Box component="img" src={analog.image_url} alt={analog.name} sx={{ width: "100%", height: 110, objectFit: "contain", bgcolor: "#f0f9ff", borderRadius: 2 }} />
                              ) : (
                                <Box sx={{ height: 110, display: "flex", alignItems: "center", justifyContent: "center", bgcolor: "#f0f9ff", borderRadius: 2 }}>Нет фото</Box>
                              )}
                              <Typography variant="caption" color="text.secondary">{analog.article ?? analog.code}</Typography>
                              <Typography fontWeight={700} sx={{ minHeight: 48 }}>{analog.name}</Typography>
                              <Typography color="primary" fontWeight={800}>{analog.similarity}% совпадения</Typography>
                              <Typography>{analog.retail_price != null ? `${analog.retail_price} руб.` : "Цена не указана"}</Typography>
                            </Box>
                            <Button size="small" sx={{ mt: 1 }} onClick={() => setAnalogReason(analog)}>Почему выбран</Button>
                          </CardContent>
                        </Card>
                      ))}
                    </Stack>
                  )}
                </>
              </Stack>
            )}
          </Box>
        </Drawer>
        <Dialog open={allAnalogsOpen} onClose={() => setAllAnalogsOpen(false)} fullWidth maxWidth="lg">
          <DialogTitle>Все аналоги</DialogTitle>
          <DialogContent>
            {allAnalogsLoading && <LinearProgress />}
            {!allAnalogsLoading && allAnalogs.length === 0 && (
              <Typography color="text.secondary" sx={{ pt: 1 }}>Подходящие аналоги не найдены</Typography>
            )}
            {allAnalogs.length > 0 && (
              <Box sx={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(210px, 1fr))", gap: 1.5, pt: 1 }}>
                {allAnalogs.map((analog) => (
                  <Card key={analog.id} variant="outlined">
                    <CardContent>
                      <Box onClick={() => openProduct(analog.id)} sx={{ cursor: "pointer" }}>
                        {analog.image_url ? (
                          <Box component="img" src={analog.image_url} alt={analog.name} sx={{ width: "100%", height: 140, objectFit: "contain", bgcolor: "#f0f9ff", borderRadius: 2 }} />
                        ) : (
                          <Box sx={{ height: 140, display: "flex", alignItems: "center", justifyContent: "center", bgcolor: "#f0f9ff", borderRadius: 2 }}>Нет фото</Box>
                        )}
                        <Typography variant="caption" color="text.secondary">{analog.article ?? analog.code}</Typography>
                        <Typography fontWeight={700} sx={{ minHeight: 48 }}>{analog.name}</Typography>
                        <Typography color="primary" fontWeight={800}>{analog.similarity}% совпадения</Typography>
                        <Typography>{analog.retail_price != null ? `${analog.retail_price} руб.` : "Цена не указана"}</Typography>
                      </Box>
                      <Button size="small" sx={{ mt: 1 }} onClick={() => setAnalogReason(analog)}>Почему выбран</Button>
                    </CardContent>
                  </Card>
                ))}
              </Box>
            )}
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setAllAnalogsOpen(false)}>Закрыть</Button>
          </DialogActions>
        </Dialog>
        <Dialog open={!!analogReason} onClose={() => setAnalogReason(null)} fullWidth maxWidth="sm">
          <DialogTitle>Почему выбран аналог</DialogTitle>
          <DialogContent>
            {analogReason && <Stack spacing={2} sx={{ pt: 1 }}>
              <Typography fontWeight={800}>{analogReason.name} — {analogReason.similarity}%</Typography>
              <Box>
                <Typography fontWeight={800}>Совпало</Typography>
                {analogReason.matched.length ? analogReason.matched.map((item) => (
                  <Typography key={item.name}>• <Box component="span" fontWeight={700}>{item.name}:</Box> {item.original_value} | {item.analog_value}</Typography>
                )) : <Typography color="text.secondary">Нет совпавших характеристик</Typography>}
              </Box>
              <Box>
                <Typography fontWeight={800}>Не совпало</Typography>
                {analogReason.unmatched.length ? analogReason.unmatched.map((item) => (
                  <Typography key={item.name}>• <Box component="span" fontWeight={700}>{item.name}:</Box> {item.original_value} | {item.analog_value}</Typography>
                )) : <Typography color="text.secondary">Все характеристики совпали</Typography>}
              </Box>
            </Stack>}
          </DialogContent>
          <DialogActions><Button onClick={() => setAnalogReason(null)}>Закрыть</Button></DialogActions>
        </Dialog>
        <Dialog
          open={productTypeDialogOpen}
          onClose={() => setProductTypeDialogOpen(false)}
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>
            {productTypeForm.id ? "Редактировать Вид товара" : "Добавить вид"}
          </DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                required
                label="Код Вида товара"
                placeholder="Например: 1"
                value={productTypeForm.code}
                onChange={(e) =>
                  setProductTypeForm((current) => ({
                    ...current,
                    code: e.target.value,
                  }))
                }
              />
              <TextField
                required
                label="Наименование"
                value={productTypeForm.name}
                onChange={(e) =>
                  setProductTypeForm((current) => ({
                    ...current,
                    name: e.target.value,
                  }))
                }
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setProductTypeDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="contained"
              disabled={!productTypeForm.code || !productTypeForm.name}
              onClick={saveProductType}
            >
              Сохранить
            </Button>
          </DialogActions>
        </Dialog>
        <Dialog
          open={warehouseDialogOpen}
          onClose={() => setWarehouseDialogOpen(false)}
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>
            {warehouseForm.id ? "Редактировать склад" : "Добавить склад"}
          </DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ mt: 1 }}>
              <TextField
                select
                required
                label="Код склада"
                value={warehouseForm.code}
                onChange={(e) =>
                  setWarehouseForm((current) => ({
                    ...current,
                    code: e.target.value,
                  }))
                }
              >
                {warehouseCodes.map((code) => (
                  <MenuItem key={code} value={code}>
                    {code}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                required
                label="Имя склада"
                value={warehouseForm.name}
                onChange={(e) =>
                  setWarehouseForm((current) => ({
                    ...current,
                    name: e.target.value,
                  }))
                }
              />
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button onClick={() => setWarehouseDialogOpen(false)}>
              Отмена
            </Button>
            <Button
              variant="contained"
              disabled={!warehouseForm.code || !warehouseForm.name}
              onClick={saveWarehouse}
            >
              Сохранить
            </Button>
          </DialogActions>
        </Dialog>
        <Dialog
          open={!!imagePreviewUrl}
          onClose={() => setImagePreviewUrl(null)}
          maxWidth={false}
          fullWidth
          PaperProps={{
            sx: { bgcolor: "rgba(15,23,42,.94)", boxShadow: "none" },
          }}
        >
          <DialogContent
            sx={{
              minHeight: "90vh",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              p: 2,
              position: "relative",
            }}
          >
            <Button
              variant="contained"
              onClick={() => setImagePreviewUrl(null)}
              sx={{ position: "absolute", top: 16, right: 16 }}
            >
              Закрыть
            </Button>
            {imagePreviewUrl && detail && detail.images.length > 1 && (
              <>
                <Button
                  variant="contained"
                  onClick={() => {
                    const currentIndex = detail.images.findIndex(
                      (image) => image.url === imagePreviewUrl,
                    );
                    const previousIndex = currentIndex <= 0
                      ? detail.images.length - 1
                      : currentIndex - 1;
                    setImagePreviewUrl(detail.images[previousIndex].url);
                  }}
                  sx={{
                    position: "absolute",
                    left: 16,
                    top: "50%",
                    transform: "translateY(-50%)",
                  }}
                >
                  Назад
                </Button>
                <Button
                  variant="contained"
                  onClick={() => {
                    const currentIndex = detail.images.findIndex(
                      (image) => image.url === imagePreviewUrl,
                    );
                    const nextIndex = currentIndex >= detail.images.length - 1
                      ? 0
                      : currentIndex + 1;
                    setImagePreviewUrl(detail.images[nextIndex].url);
                  }}
                  sx={{
                    position: "absolute",
                    right: 16,
                    top: "50%",
                    transform: "translateY(-50%)",
                  }}
                >
                  Вперёд
                </Button>
              </>
            )}
            {imagePreviewUrl && (
              <Box
                component="img"
                src={imagePreviewUrl}
                alt="Увеличенное изображение товара"
                sx={{
                  maxWidth: { xs: "100%", md: "calc(100% - 180px)" },
                  maxHeight: "86vh",
                  objectFit: "contain",
                }}
              />
            )}
          </DialogContent>
        </Dialog>
      </Box>
    </ThemeProvider>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
