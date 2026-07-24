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
  Tabs,
  TextField,
  ThemeProvider,
  Toolbar,
  Typography,
  createTheme,
} from "@mui/material";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteIcon from "@mui/icons-material/Delete";
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

function App() {
  const [search, setSearch] = useState("");
  const [filters, setFilters] = useState<Record<string, string[]>>({});
  const [active, setActive] = useState<Record<string, string[]>>({});
  const [products, setProducts] = useState<Product[]>([]);
  const [meta, setMeta] = useState<Meta>({ product_count: 0 });
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [tab, setTab] = useState<"catalog" | "settings" | "notifications">(
    "catalog",
  );
  const [settingsTab, setSettingsTab] = useState<
    "settings" | "mappings" | "logs"
  >("settings");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [logs, setLogs] = useState<ServiceLog[]>([]);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [unreadNotifications, setUnreadNotifications] = useState(0);
  const [filteredCount, setFilteredCount] = useState(0);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [warehouses, setWarehouses] = useState<Warehouse[]>([]);
  const [productTypes, setProductTypes] = useState<ProductType[]>([]);
  const [warehouseCodes, setWarehouseCodes] = useState<string[]>([]);
  const [warehouseDialogOpen, setWarehouseDialogOpen] = useState(false);
  const [warehouseForm, setWarehouseForm] = useState<{
    id?: number;
    code: string;
    name: string;
  }>({ code: "", name: "" });
  const [productTypeDialogOpen, setProductTypeDialogOpen] = useState(false);
  const [productTypeForm, setProductTypeForm] = useState<{
    id?: number;
    code: string;
    name: string;
  }>({ code: "", name: "" });
  const [xmlServerForm, setXmlServerForm] = useState<XmlServerSetting | null>(null);
  const [autoImportState, setAutoImportState] = useState<AutoImportState | null>(null);
  const [ftpTestMessage, setFtpTestMessage] = useState<string | null>(null);
  const params = useMemo(() => {
    const p = new URLSearchParams({ search });
    Object.entries(active).forEach(
      ([k, v]) => v.length && p.set(k, v.join(",")),
    );
    return p;
  }, [search, active]);
  const reload = () => {
    api.products(params).then((items) => {
      setProducts(items);
      setSelectedIds([]);
    });
    api.productCount(params).then((result) => setFilteredCount(result.count));
    api.meta().then(setMeta);
    api.filters().then(setFilters);
    api
      .unreadNotifications()
      .then((result) => setUnreadNotifications(result.count));
  };
  useEffect(reload, [params]);
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
    setActive((current) => {
      const values = current[key] ?? [];
      return {
        ...current,
        [key]: values.includes(value)
          ? values.filter((item) => item !== value)
          : [...values, value],
      };
    });
  const resetFilters = () => setActive({});
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
          <Toolbar sx={{ gap: 2, py: 1, justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              startIcon={<UploadFileIcon />}
              component="label"
              sx={{ fontSize: 12, whiteSpace: "nowrap", px: 2 }}
            >
              Загрузить XML
              <input
                hidden
                type="file"
                accept=".xml"
                onChange={(e) => upload(e.target.files?.[0])}
              />
            </Button>
          </Toolbar>
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
              <TextField
                fullWidth
                size="small"
                placeholder="Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                InputProps={{
                  startAdornment: <SearchIcon color="action" sx={{ mr: 1 }} />,
                }}
                sx={{
                  "& .MuiOutlinedInput-root": {
                    bgcolor: alpha("#ffffff", 0.86),
                    borderRadius: 999,
                  },
                }}
              />
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
                            {new Date(notification.created_at).toLocaleString()}
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
                        <Typography>Дата: {new Date(autoImportState.last_run_at).toLocaleString()}</Typography>
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
                          <TableCell>Событие</TableCell>
                          <TableCell>Сообщение</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {logs.map((log) => (
                          <TableRow key={log.id}>
                            <TableCell>
                              {new Date(log.created_at).toLocaleString()}
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
                            <TableCell>{log.event}</TableCell>
                            <TableCell>{log.message}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                )}
              </CardContent>
            </Card>
          )}

          {tab === "catalog" && (
            <Stack
              direction={{ xs: "column", md: "row" }}
              spacing={3}
              alignItems="flex-start"
            >
              <Card
                sx={{
                  width: { xs: "100%", md: 304 },
                  flexShrink: 0,
                  position: { md: "sticky" },
                  top: 96,
                }}
              >
                <CardContent>
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    alignItems="center"
                  >
                    <Typography variant="h6">Фильтры</Typography>
                    <Chip size="small" color="primary" label={filteredCount} />
                  </Stack>
                  <Button sx={{ mt: 1 }} size="small" onClick={resetFilters}>
                    Сбросить фильтры
                  </Button>
                  {meta.errors && (
                    <Typography sx={{ mt: 1 }} color="error">
                      Ошибки импорта: {meta.errors}
                    </Typography>
                  )}
                  <Divider sx={{ my: 2 }} />
                  <List disablePadding>
                    {Object.entries(labels).map(([key, label]) => (
                      <Box key={key} sx={{ mb: 2 }}>
                        <Typography
                          variant="subtitle2"
                          color="text.secondary"
                          sx={{ mb: 1 }}
                        >
                          {label}
                        </Typography>
                        <Stack direction="row" flexWrap="wrap" gap={1}>
                          {(filters[key] ?? []).slice(0, 24).map((v) => (
                            <Chip
                              clickable
                              color={
                                (active[key] ?? []).includes(v)
                                  ? "primary"
                                  : "default"
                              }
                              variant={
                                (active[key] ?? []).includes(v)
                                  ? "filled"
                                  : "outlined"
                              }
                              key={v}
                              label={v}
                              onClick={() => toggleFilter(key, v)}
                            />
                          ))}
                        </Stack>
                      </Box>
                    ))}
                  </List>
                  <Divider sx={{ my: 2 }} />
                  <Stack spacing={1}>
                    <Button href={api.exportUrl("xlsx", params)}>
                      Экспорт Excel
                    </Button>
                    <Button
                      color="error"
                      variant="outlined"
                      disabled={!selectedIds.length}
                      onClick={deleteSelected}
                    >
                      Удалить выбранные
                    </Button>
                  </Stack>
                </CardContent>
              </Card>

              <TableContainer component={Card} sx={{ flex: 1 }}>
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableCell padding="checkbox">
                        <Checkbox
                          checked={allSelected}
                          indeterminate={selectedIds.length > 0 && !allSelected}
                          onChange={toggleAll}
                        />
                      </TableCell>
                      <TableCell>Фото</TableCell>
                      <TableCell>Наименование</TableCell>
                      <TableCell>Артикул</TableCell>
                      <TableCell>Код</TableCell>
                      <TableCell align="right">Цена</TableCell>
                      <TableCell align="right">Количество Авиаторов</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {products.map((p) => (
                      <TableRow
                        hover
                        key={p.id}
                        selected={selectedIds.includes(p.id)}
                        onClick={() => api.product(p.id).then(setDetail)}
                        sx={{ cursor: "pointer" }}
                      >
                        <TableCell padding="checkbox">
                          <Checkbox
                            checked={selectedIds.includes(p.id)}
                            onClick={(e) => e.stopPropagation()}
                            onChange={() => toggleSelected(p.id)}
                          />
                        </TableCell>
                        <TableCell>
                          {p.images[0] ? (
                            <Box
                              component="img"
                              src={p.images[0].url}
                              alt={p.name}
                              sx={{
                                width: 56,
                                height: 56,
                                objectFit: "contain",
                                borderRadius: 2,
                                bgcolor: "#e0f2fe",
                              }}
                            />
                          ) : (
                            "—"
                          )}
                        </TableCell>
                        <TableCell>
                          <Typography>{p.name}</Typography>
                        </TableCell>
                        <TableCell>{p.article ?? "—"}</TableCell>
                        <TableCell>{p.code}</TableCell>
                        <TableCell align="right" sx={{ minWidth: 180 }}>
                          {visiblePrices(p).length
                            ? visiblePrices(p).map((price) => (
                                <Typography
                                  key={price.price_type}
                                  variant="body2"
                                  sx={{ whiteSpace: "nowrap" }}
                                >
                                  {price.price_type}: {price.value} руб.
                                </Typography>
                              ))
                            : "—"}
                        </TableCell>
                        <TableCell align="right">{p.quantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Stack>
          )}
        </Container>

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
