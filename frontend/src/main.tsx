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
  IconButton,
  InputAdornment,
  LinearProgress,
  List,
  MenuItem,
  Paper,
  Stack,
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
  Typography,
  createTheme,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import CloseIcon from "@mui/icons-material/Close";
import DeleteIcon from "@mui/icons-material/Delete";
import FilterListIcon from "@mui/icons-material/FilterList";
import RefreshIcon from "@mui/icons-material/Refresh";
import EditIcon from "@mui/icons-material/Edit";
import SearchIcon from "@mui/icons-material/Search";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import { api } from "./api/client";
import type {
  Meta,
  Notification,
  Product,
  ProductDetail,
  ProductType,
  XmlServerSetting,
  AutoImportState,
  ServiceLog,
  Warehouse,
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

const labels: Record<string, string> = {
  section: "Раздел",
  manufacturer: "Производитель",
  brand: "Бренд",
  manager: "Менеджер",
  country: "Страна",
  material: "Материал",
  color: "Цвет",
  product_type: "Вид товара",
  warehouse: "Склады",
};
const updateScriptPath = "/var/www/html/vr/update_vrcatalog.sh";
const clientsUrl = "https://kvasmix.ru/vr/clients/";
const formatMoscowDate = (value: string) =>
  new Date(value).toLocaleString("ru-RU", { timeZone: "Europe/Moscow" });
const getLogStage = (log: ServiceLog) =>
  log.message.match(/Этап:\n([^\n]+)/)?.[1] ?? log.event;

function App() {
  const initialParams = useMemo(() => new URLSearchParams(window.location.search), []);
  const multiFromUrl = (p: URLSearchParams) => {
    const result = Object.keys(labels).reduce<Record<string, string[]>>((values, key) => {
      const value = p.get(key === "product_type" ? "productType" : key);
      if (value) values[key] = value.split(",").filter(Boolean);
      return values;
    }, {});
    p.getAll("property").forEach((item) => {
      const [name, ...valueParts] = item.split(":");
      if (name && valueParts.length) (result[`property:${name}`] ??= []).push(valueParts.join(":"));
    });
    return result;
  };
  const fieldsFromUrl = (p: URLSearchParams) => ({ id: p.get("id") ?? "", name: p.get("name") ?? "", article: p.get("article") ?? "", availability: p.get("availability") ?? "all", quantityFrom: p.get("quantityFrom") ?? "", quantityTo: p.get("quantityTo") ?? "", priceFrom: p.get("priceFrom") ?? "", priceTo: p.get("priceTo") ?? "" });
  const [search, setSearch] = useState(initialParams.get("search") ?? "");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const filterLabels = useMemo(() => Object.keys(filters).reduce<Record<string, string>>((result, key) => {
    if (labels[key]) result[key] = labels[key];
    else if (key.startsWith("property:")) result[key] = key.slice("property:".length);
    return result;
  }, { ...labels }), [filters]);
  const [active, setActive] = useState<Record<string, string[]>>(() => multiFromUrl(initialParams));
  const [draftActive, setDraftActive] = useState<Record<string, string[]>>(() => multiFromUrl(initialParams));
  const [filterFields, setFilterFields] = useState(() => fieldsFromUrl(initialParams));
  const [draftFields, setDraftFields] = useState(() => fieldsFromUrl(initialParams));
  const [products, setProducts] = useState<Product[]>([]);
  const [meta, setMeta] = useState<Meta>({ product_count: 0 });
  const [loading, setLoading] = useState(false);
  const [catalogError, setCatalogError] = useState<string | null>(null);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [tab, setTab] = useState<"catalog" | "settings" | "notifications">("catalog");
  const [settingsTab, setSettingsTab] = useState<"settings" | "mappings" | "logs">("settings");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [logs, setLogs] = useState<ServiceLog[]>([]);
  const [expandedLogId, setExpandedLogId] = useState<number | null>(null);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [pagination, setPagination] = useState({ page: Number(initialParams.get("page")) || 1, pageSize: Number(initialParams.get("pageSize")) || 20, totalItems: 0, totalPages: 0 });
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [openFilterGroups, setOpenFilterGroups] = useState<Record<string, boolean>>({});
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
  useEffect(() => { Promise.all([api.meta(), api.filters(), api.unreadNotifications()]).then(([m, f, u]) => { setMeta(m); setFilters(f); setUnreadNotifications(u.count); }); }, []);
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
      if (values.length) next.set(parameter, values.join(",")); else next.delete(parameter);
    });
    Object.entries(draftFields).forEach(([key, value]) => {
      if (value && value !== "all") next.set(key, value.trim()); else next.delete(key);
    });
    next.delete("page");
    setActive(draftActive); setFilterFields(draftFields); replaceCatalogParams(next); setFiltersOpen(false);
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
      } else updateParams({ [key === "product_type" ? "productType" : key]: values.join(",") });
    } else {
      const updated = { ...filterFields, [key]: key === "availability" ? "all" : "" };
      setFilterFields(updated); setDraftFields(updated); updateParams({ [key]: null });
    }
  };
  const activeConditionCount = Object.values(active).reduce((sum, values) => sum + values.length, 0) + Object.entries(filterFields).filter(([, value]) => value && value !== "all").length;
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
  const deleteSelected = async () => {
    if (!selectedIds.length) return;
    await api.deleteProducts(selectedIds);
    reload();
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
  const openNotifications = async () => {
    setTab("notifications");
    setNotifications(await api.notifications());
    api
      .unreadNotifications()
      .then((result) => setUnreadNotifications(result.count));
  };
  const readNotification = async (id: number) => {
    await api.markNotificationRead(id);
    setNotifications(await api.notifications());
    api
      .unreadNotifications()
      .then((result) => setUnreadNotifications(result.count));
  };
  const readAllNotifications = async () => {
    await api.markAllNotificationsRead();
    setNotifications(await api.notifications());
    api
      .unreadNotifications()
      .then((result) => setUnreadNotifications(result.count));
  };

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
                setTab(value);
              }}
              textColor="primary"
              indicatorColor="primary"
              variant="scrollable"
            >
              <Tab value="catalog" label="Каталог" />
              <Tab value="clients" label="Контрагенты" />
              <Tab
                value="notifications"
                label={
                  <Box component="span" sx={{ position: "relative" }}>
                    Уведомления
                    {unreadNotifications > 0 && (
                      <Box
                        component="span"
                        sx={{
                          position: "absolute",
                          right: -10,
                          top: 0,
                          width: 8,
                          height: 8,
                          bgcolor: "error.main",
                          borderRadius: "50%",
                        }}
                      />
                    )}
                  </Box>
                }
                onClick={openNotifications}
              />
              <Tab value="settings" label="Настройки" />
            </Tabs>
          </Paper>

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
                spacing={0}
                alignItems="stretch"
              >
                <TextField
                  fullWidth
                  size="small"
                  placeholder="Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
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
                <Button
                  variant="outlined"
                  startIcon={<FilterListIcon />}
                  onClick={() => { setDraftActive(active); setDraftFields(filterFields); setFiltersOpen(true); }}
                  sx={{ ml: { md: 1 }, mt: { xs: 1, md: 0 }, whiteSpace: "nowrap" }}
                >
                  Фильтр{activeConditionCount ? ` (${activeConditionCount})` : ""}
                </Button>
                <Button
                  variant="contained"
                  startIcon={<UploadFileIcon />}
                  component="label"
                  sx={{
                    fontSize: 12,
                    whiteSpace: "nowrap",
                    px: 2,
                    ml: { md: "20px" },
                  }}
                >
                  Загрузить XML
                  <input
                    hidden
                    type="file"
                    accept=".xml"
                    onChange={(e) => upload(e.target.files?.[0])}
                  />
                </Button>
              </Stack>
            </Paper>
          )}

          {tab === "notifications" && (
            <Card>
              <CardContent>
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="center"
                  sx={{ mb: 2 }}
                >
                  <Box>
                    <Typography variant="h6">Уведомления</Typography>
                    <Typography color="text.secondary">
                      Отображаются только ошибки.
                    </Typography>
                  </Box>
                  <Button
                    variant="outlined"
                    disabled={!notifications.some((notification) => !notification.is_read)}
                    onClick={readAllNotifications}
                  >
                    Прочитать все
                  </Button>
                </Stack>
                <TableContainer>
                  <Table>
                    <TableHead>
                      <TableRow>
                        <TableCell>Дата</TableCell>
                        <TableCell>Заголовок</TableCell>
                        <TableCell>Описание</TableCell>
                        <TableCell>Статус</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {notifications.map((notification) => (
                        <TableRow
                          hover
                          key={notification.id}
                          onClick={() => readNotification(notification.id)}
                          sx={{
                            cursor: "pointer",
                            bgcolor: notification.is_read
                              ? "inherit"
                              : "rgba(239,68,68,.08)",
                            fontWeight: notification.is_read ? 400 : 800,
                          }}
                        >
                          <TableCell>
                            {formatMoscowDate(notification.created_at)}
                          </TableCell>
                          <TableCell>
                            <Typography
                              fontWeight={notification.is_read ? 400 : 800}
                            >
                              {notification.title}
                            </Typography>
                          </TableCell>
                          <TableCell sx={{ whiteSpace: "pre-line" }}>
                            {notification.message}
                          </TableCell>
                          <TableCell>
                            {notification.is_read ? "прочитано" : "новое"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </CardContent>
            </Card>
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
                        : openGeneralSettings()
                  }
                  sx={{ mb: 2 }}
                >
                  <Tab value="settings" label="Общие" />
                  <Tab value="mappings" label="Сопоставления" />
                  <Tab value="logs" label="Логи" />
                </Tabs>
                {settingsTab === "settings" && (
                  <Box>
                    <Typography variant="h6">Настройки</Typography>
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
                    <Typography variant="h6">Подключение к серверу XML</Typography>
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
                        <Typography>Дата: {formatMoscowDate(autoImportState.last_run_at)}</Typography>
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
                {settingsTab === "mappings" && (
                  <Box>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                      sx={{ mb: 2 }}
                    >
                      <Box>
                        <Typography variant="h6">Склады</Typography>
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
                    <Divider sx={{ my: 3 }} />
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      alignItems="center"
                      sx={{ mb: 2 }}
                    >
                      <Box>
                        <Typography variant="h6">Виды товаров</Typography>
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
                        {logs.map((log) => (
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
                      <Chip key={`${key}-${value}`} label={`${filterLabels[key]}: ${value}`} onDelete={() => removeFilter(key, value)} />
                    )))}
                    {Object.entries(filterFields).filter(([, value]) => value && value !== "all").map(([key, value]) => (
                      <Chip key={key} label={`${({ id: "ID", name: "Название", article: "Артикул", availability: "Наличие", quantityFrom: "Количество от", quantityTo: "Количество до", priceFrom: "Цена от", priceTo: "Цена до" } as Record<string, string>)[key]}: ${value === "in_stock" ? "В наличии" : value === "out_of_stock" ? "Нет в наличии" : value}`} onDelete={() => removeFilter(key)} />
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
              <TableContainer component={Card} sx={{ position: "relative" }}>
                {loading && <LinearProgress />}
                <Table aria-label="Список товаров">
                  <TableHead><TableRow>
                    <TableCell padding="checkbox"><Checkbox aria-label="Выбрать все товары на странице" checked={allSelected} indeterminate={selectedIds.length > 0 && !allSelected} onChange={toggleAll} /></TableCell>
                    <TableCell>Фото</TableCell>
                    {[ ["name", "Наименование"], ["article", "Артикул"], ["code", "Код"] ].map(([field, label]) => (
                      <TableCell key={field}><TableSortLabel active={(params.get("sort") ?? "id") === field} direction={params.get("sort") === field && params.get("order") === "desc" ? "desc" : "asc"} onClick={() => changeSort(field)}>{label}</TableSortLabel></TableCell>
                    ))}
                    <TableCell align="right"><TableSortLabel active={params.get("sort") === "price"} direction={params.get("sort") === "price" && params.get("order") === "desc" ? "desc" : "asc"} onClick={() => changeSort("price")}>Цена</TableSortLabel></TableCell>
                    <TableCell align="right"><TableSortLabel active={params.get("sort") === "quantity"} direction={params.get("sort") === "quantity" && params.get("order") === "desc" ? "desc" : "asc"} onClick={() => changeSort("quantity")}>Количество Авиаторов</TableSortLabel></TableCell>
                  </TableRow></TableHead>
                  <TableBody>
                    {!loading && products.length === 0 && <TableRow><TableCell colSpan={7} align="center" sx={{ py: 8 }}><Typography variant="h6">{activeConditionCount || search.trim() ? "По заданным условиям товары не найдены" : "Каталог пока пуст"}</Typography><Typography color="text.secondary">{activeConditionCount || search.trim() ? "Попробуйте изменить или сбросить фильтры" : "Загрузите XML-файл, чтобы добавить товары"}</Typography></TableCell></TableRow>}
                    {products.map((p) => (
                      <TableRow hover key={p.id} selected={selectedIds.includes(p.id)} onClick={() => api.product(p.id).then(setDetail)} sx={{ cursor: "pointer" }}>
                        <TableCell padding="checkbox"><Checkbox aria-label={`Выбрать ${p.name}`} checked={selectedIds.includes(p.id)} onClick={(e) => e.stopPropagation()} onChange={() => toggleSelected(p.id)} /></TableCell>
                        <TableCell>{p.images[0] ? <Box component="img" src={p.images[0].url} alt={p.name} sx={{ width: 56, height: 56, objectFit: "contain", borderRadius: 2, bgcolor: "#e0f2fe" }} /> : "—"}</TableCell>
                        <TableCell><Typography>{p.name}</Typography></TableCell><TableCell>{p.article ?? "—"}</TableCell><TableCell>{p.code}</TableCell>
                        <TableCell align="right" sx={{ minWidth: 180 }}>{visiblePrices(p).length ? visiblePrices(p).map((price) => <Typography key={price.price_type} variant="body2" sx={{ whiteSpace: "nowrap" }}>{price.price_type}: {price.value} руб.</Typography>) : "—"}</TableCell>
                        <TableCell align="right">{p.quantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <TablePagination component="div" count={pagination.totalItems} page={Math.max(0, pagination.page - 1)} onPageChange={(_, page) => updateParams({ page: page + 1 }, false)} rowsPerPage={pagination.pageSize} onRowsPerPageChange={(event) => updateParams({ pageSize: event.target.value })} rowsPerPageOptions={[20, 50, 100]} labelRowsPerPage="Строк на странице" labelDisplayedRows={({ from, to, count }) => `${from}–${to} из ${count}`} />
              </TableContainer>
              <Stack direction={{ xs: "column", sm: "row" }} spacing={1}>
                <Button href={api.exportUrl("xlsx", params)}>Экспорт Excel</Button>
                <Button color="error" variant="outlined" disabled={!selectedIds.length} onClick={deleteSelected}>Удалить выбранные</Button>
              </Stack>
            </Stack>
          )}
        </Container>

        <Drawer anchor="left" open={filtersOpen} onClose={() => setFiltersOpen(false)} PaperProps={{ sx: { width: { xs: "100%", sm: 420 }, p: 3 } }}>
          <Stack spacing={2} role="form" aria-label="Расширенный фильтр товаров">
            <Stack direction="row" justifyContent="space-between" alignItems="center"><Typography variant="h6">Фильтр товаров</Typography><IconButton aria-label="Закрыть фильтр" onClick={() => setFiltersOpen(false)}><CloseIcon /></IconButton></Stack>
            <TextField label="ID" type="number" value={draftFields.id} onChange={(e) => setDraftFields({ ...draftFields, id: e.target.value })} inputProps={{ min: 1 }} />
            <TextField label="Название" value={draftFields.name} onChange={(e) => setDraftFields({ ...draftFields, name: e.target.value })} />
            <TextField label="Артикул" value={draftFields.article} onChange={(e) => setDraftFields({ ...draftFields, article: e.target.value })} />
            <TextField select label="Наличие" value={draftFields.availability} onChange={(e) => setDraftFields({ ...draftFields, availability: e.target.value })}><MenuItem value="all">Все</MenuItem><MenuItem value="in_stock">В наличии</MenuItem><MenuItem value="out_of_stock">Нет в наличии</MenuItem></TextField>
            <Stack direction="row" spacing={1}><TextField fullWidth label="Количество от" type="number" value={draftFields.quantityFrom} onChange={(e) => setDraftFields({ ...draftFields, quantityFrom: e.target.value })} /><TextField fullWidth label="Количество до" type="number" value={draftFields.quantityTo} onChange={(e) => setDraftFields({ ...draftFields, quantityTo: e.target.value })} /></Stack>
            <Stack direction="row" spacing={1}><TextField fullWidth label="Цена от" type="number" value={draftFields.priceFrom} onChange={(e) => setDraftFields({ ...draftFields, priceFrom: e.target.value })} inputProps={{ min: 0 }} /><TextField fullWidth label="Цена до" type="number" value={draftFields.priceTo} onChange={(e) => setDraftFields({ ...draftFields, priceTo: e.target.value })} inputProps={{ min: 0 }} /></Stack>
            <Divider />
            {Object.entries(filterLabels).map(([key, label]) => <Box key={key}><Button fullWidth onClick={() => toggleFilterGroup(key)} sx={{ justifyContent: "space-between" }}>{label}<span>{openFilterGroups[key] ? "−" : "+"}</span></Button><Collapse in={!!openFilterGroups[key]} unmountOnExit><Stack direction="row" flexWrap="wrap" gap={1} sx={{ py: 1 }}>{(filters[key] ?? []).slice(0, 100).map((value) => <Chip key={value} clickable label={value} color={(draftActive[key] ?? []).includes(value) ? "primary" : "default"} variant={(draftActive[key] ?? []).includes(value) ? "filled" : "outlined"} onClick={() => toggleFilter(key, value)} />)}</Stack></Collapse></Box>)}
            {meta.errors && <Typography color="error">Ошибки импорта: {meta.errors}</Typography>}
            <Stack direction="row" spacing={1} sx={{ position: "sticky", bottom: 0, bgcolor: "background.paper", py: 1 }}><Button variant="contained" onClick={applyFilters}>Применить</Button><Button onClick={resetFilters}>Сбросить</Button><Button onClick={() => setFiltersOpen(false)}>Закрыть</Button></Stack>
          </Stack>
        </Drawer>
        <Drawer
          anchor="right"
          open={!!detail}
          onClose={() => setDetail(null)}
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
                    ["Материал", detail.material],
                    ["Цвет", detail.color],
                    ["Сертификат", detail.certificate],
                    ["Штрихкоды", detail.barcodes.map((b) => b.value).join(", ")],
                    ["Описание", detail.description],
                  ]
                    .filter(([, value]) => value)
                    .map(([label, value]) => (
                      <Typography key={label} sx={{ mt: label === "Описание" ? 1 : 0 }}>
                        <Box component="span" fontWeight={800}>
                          {label}:
                        </Box>{" "}
                        {value}
                      </Typography>
                    ))}
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
                {detail.analogs.length > 0 && (
                  <>
                    <Typography fontWeight={800}>Аналоги</Typography>
                    {detail.analogs.map((a) => (
                      <Typography key={a.code}>
                        {a.code} {a.name}
                      </Typography>
                    ))}
                  </>
                )}
              </Stack>
            )}
          </Box>
        </Drawer>
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
