import { useEffect, useRef, useState } from "react";
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { api, type AccessDevice, type DeviceDetails, type DevicePackage } from "../api/client";

type Mode = "issue" | "edit" | "replace" | "revoke" | "confirm" | "cancel";
const titles: Record<Mode, string> = {
  issue: "Выпустить сертификат", edit: "Редактировать устройство",
  replace: "Подготовить замену", revoke: "Заблокировать устройство",
  confirm: "Подтвердить замену", cancel: "Отменить замену",
};
const statusLabels = { active: "Активен", revoked: "Заблокирован", expired: "Истёк", pending: "Ожидает активации" };
const emptyDetails = { name: "", owner: "", comment: "" };
const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "short", timeStyle: "short", timeZone: "Europe/Moscow" });
const displayDate = (value: string | null) => value ? dateFormat.format(new Date(value)) : "—";

export function DeviceAccess() {
  const [devices, setDevices] = useState<AccessDevice[] | null>(null);
  const [listError, setListError] = useState("");
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [dialog, setDialog] = useState<{ mode: Mode; device?: AccessDevice } | null>(null);
  const [details, setDetails] = useState<DeviceDetails>(emptyDetails);
  const [operationId, setOperationId] = useState("");
  const inFlight = useRef(false);
  const mounted = useRef(true);
  const [installationConfirmed, setInstallationConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [issued, setIssued] = useState<(DevicePackage & { replacement: boolean }) | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [copied, setCopied] = useState(false);
  const [secretError, setSecretError] = useState("");
  const [closeConfirmation, setCloseConfirmation] = useState(false);
  const issuedRef = useRef<typeof issued>(null);
  const copyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const downloadUrls = useRef(new Set<string>());
  const cleanupDownloads = () => { downloadUrls.current.forEach((url) => URL.revokeObjectURL(url)); downloadUrls.current.clear(); };
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; issuedRef.current = null; cleanupDownloads(); if (copyTimer.current) clearTimeout(copyTimer.current); };
  }, []);

  const load = async () => {
    setListError("");
    try {
      setDevices(await api.accessDevices());
    } catch (failure) {
      setListError(failure instanceof Error ? failure.message : "Не удалось загрузить устройства");
    }
  };

  useEffect(() => { void load(); }, []);

  const close = () => {
    setOperationId("");
    setDialog(null);
  };

  const open = (mode: Mode, device?: AccessDevice) => {
    setError("");
    if (mode === "issue" || mode === "replace") {
      try { setOperationId(Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join("")); }
      catch { setOperationId(""); setError("Не удалось начать безопасный выпуск. Обновите страницу."); }
    }
    setInstallationConfirmed(false);
    setDetails(device ? { name: device.name, owner: device.owner, comment: device.comment } : emptyDetails);
    setDialog({ mode, device });
  };

  const save = async () => {
    if (!dialog || inFlight.current) return;
    inFlight.current = true;
    const { mode, device } = dialog;
    setSaving(true);
    setError("");
    try {
      if (mode === "issue" || mode === "replace") {
        const operation = { operation_id: operationId };
        const result = await api.downloadDevicePackage(
          mode === "issue" ? "issue-package" : `${device?.id}/replacements/prepare`,
          mode === "issue" ? { ...details, ...operation } : operation,
        );
        if (!mounted.current) return;
        const value = { ...result, replacement: mode === "replace" };
        issuedRef.current = value;
        setIssued(value);
        setShowPassword(false); setCopied(false); setSecretError(""); setCloseConfirmation(false);
      } else if (mode === "edit") {
        await api.saveAccessDevice(String(device?.id), details, "PATCH");
      } else {
        const action = mode === "revoke" ? `${device?.id}/revoke`
          : `${device?.replaces_id}/replacements/${device?.id}/${mode}`;
        await api.saveAccessDevice(action);
      }
      close();
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Не удалось сохранить изменения");
      // Keep the same operation ID: a lost response must not mint another package.
      if (mode === "issue" || mode === "replace") setError(
        "Выпуск не подтверждён: " + (failure instanceof Error ? failure.message : "ошибка сети")
        + " Проверьте список устройств. Повтор этой операции не создаст второй сертификат, если первый уже выпущен.");
    } finally {
      inFlight.current = false;
      setSaving(false);
      void load();
    }
  };

  const clearIssued = () => {
    issuedRef.current = null;
    setIssued(null); setShowPassword(false); setCopied(false); setSecretError(""); setCloseConfirmation(false);
    if (copyTimer.current) clearTimeout(copyTimer.current);
    cleanupDownloads();
  };
  const copyPassword = async () => {
    const current = issuedRef.current;
    if (!current) return;
    setSecretError("");
    try {
      await navigator.clipboard.writeText(current.password);
      if (issuedRef.current !== current) return;
      setCopied(true);
      if (copyTimer.current) clearTimeout(copyTimer.current);
      copyTimer.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      if (issuedRef.current === current) setSecretError("Не удалось скопировать пароль. Покажите его и скопируйте вручную.");
    }
  };
  const download = () => {
    if (!issued) return;
    setSecretError("");
    let url: string | undefined;
    let link: HTMLAnchorElement | undefined;
    try {
      url = URL.createObjectURL(issued.file);
      downloadUrls.current.add(url);
      link = document.createElement("a");
      link.href = url; link.download = issued.filename;
      document.body.appendChild(link); link.click();
      const savedUrl = url;
      window.setTimeout(() => { URL.revokeObjectURL(savedUrl); downloadUrls.current.delete(savedUrl); }, 1000);
    } catch {
      if (url) { URL.revokeObjectURL(url); downloadUrls.current.delete(url); }
      setSecretError("Не удалось начать скачивание. Повторите попытку, не закрывая окно.");
    } finally { link?.remove(); }
  };

  const term = search.trim().toLocaleLowerCase("ru-RU");
  const visible = (devices ?? []).filter((device) =>
    (!status || device.status === status) &&
    [device.name, device.owner, device.common_name, device.fingerprint].some((value) => value.toLocaleLowerCase("ru-RU").includes(term)));
  const needsPackage = dialog?.mode === "issue" || dialog?.mode === "replace";
  const needsDetails = dialog?.mode === "issue" || dialog?.mode === "edit";
  const pendingOriginalIds = new Set(devices?.filter((device) => device.awaiting_activation).map((device) => device.replaces_id));

  return <Stack spacing={2}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
      <Box><Typography variant="h6">Доступы устройств</Typography><Typography color="text.secondary" variant="body2">Клиентские сертификаты VR Catalog</Typography></Box>
      <Stack direction={{ xs: "column", sm: "row" }} gap={1}>
        <Button variant="contained" onClick={() => open("issue")}>{titles.issue}</Button>
      </Stack>
    </Stack>
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Stack direction={{ xs: "column", sm: "row" }} gap={2}>
        <TextField size="small" label="Устройство, владелец или сертификат" value={search} onChange={(event) => setSearch(event.target.value)} sx={{ minWidth: { sm: 300 } }} />
        <TextField select size="small" label="Статус" value={status} onChange={(event) => setStatus(event.target.value)} sx={{ minWidth: 160 }}>
          <MenuItem value="">Все</MenuItem>
          {Object.entries(statusLabels).map(([value, label]) => <MenuItem key={value} value={value}>{label}</MenuItem>)}
        </TextField>
      </Stack>
    </Paper>
    {listError ? <Alert severity="error" action={<Button onClick={load}>Повторить</Button>}>{listError}</Alert>
      : devices === null ? <LinearProgress aria-label="Загрузка устройств" />
      : <TableContainer component={Paper} variant="outlined">
        <Table size="small" aria-label="Сертификаты устройств">
          <TableHead><TableRow>{["Устройство", "Владелец", "Сертификат", "Действует до (МСК)", "Статус", "Последний доступ (МСК)", "Действия"].map((label) => <TableCell key={label}>{label}</TableCell>)}</TableRow></TableHead>
          <TableBody>
            {!visible.length && <TableRow><TableCell colSpan={7}>Устройства не найдены</TableCell></TableRow>}
            {visible.map((device) => <TableRow key={device.id}>
              <TableCell><Typography variant="body2" fontWeight={700}>{device.name}</Typography>{device.comment && <Typography variant="caption" color="text.secondary">{device.comment}</Typography>}</TableCell>
              <TableCell>{device.owner}</TableCell>
              <TableCell><Typography variant="body2">{device.common_name}</Typography><Typography variant="caption" title={device.fingerprint}>{device.fingerprint.slice(0, 16)}…</Typography></TableCell>
              <TableCell>{displayDate(device.expires_at)}</TableCell>
              <TableCell><Chip size="small" color={device.status === "active" ? "success" : "default"} label={statusLabels[device.status]} /></TableCell>
              <TableCell>{displayDate(device.last_seen_at)}</TableCell>
              <TableCell><Stack direction="row" flexWrap="wrap" gap={0.5}>
                {device.awaiting_activation ? <>
                  {device.status === "pending" &&
                    <Button size="small" onClick={() => open("confirm", device)}>Подтвердить замену</Button>}
                  <Button size="small" color="error" onClick={() => open("cancel", device)}>Отменить замену</Button>
                </> : <>
                  <Button size="small" onClick={() => open("edit", device)}>Редактировать</Button>
                  {device.status !== "revoked" && <Button size="small" disabled={pendingOriginalIds.has(device.id)} onClick={() => open("replace", device)}>Перевыпустить</Button>}
                  {device.status !== "revoked" && <Button size="small" color="error" onClick={() => open("revoke", device)}>Заблокировать</Button>}
                </>}
                {device.crl_pending && <Button size="small" onClick={() => open("confirm", device)}>Повторить подтверждение</Button>}
              </Stack></TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </TableContainer>}
    <Dialog open={!!dialog} onClose={saving ? undefined : close} fullWidth maxWidth="sm">
      <DialogTitle>{dialog && titles[dialog.mode]}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {dialog?.mode === "revoke" && <Typography>Заблокировать доступ для «{dialog.device?.name}»? Для восстановления доступа потребуется новый сертификат.</Typography>}
        {dialog?.mode === "replace" && <Alert severity="info">Старый сертификат сохранит доступ, пока вы явно не подтвердите замену.</Alert>}
        {dialog?.mode === "cancel" && <Typography>Отменённый сертификат больше нельзя активировать. Исходный сертификат сохранит свой статус.</Typography>}
        {dialog?.mode === "confirm" && (dialog.device?.crl_pending
          ? <Alert severity="warning">Замена уже применена. Повтор подтвердит публикацию списка отзыва.</Alert>
          : <><Alert severity="warning">Установите новый сертификат и проверьте, что он доступен в Windows и браузере. До активации он не открывает каталог. Подтвердите замену со второго разрешённого устройства.</Alert>
            <FormControlLabel label="Новый сертификат установлен и проверен в хранилище устройства" control={<Checkbox checked={installationConfirmed} onChange={(_, checked) => setInstallationConfirmed(checked)} />} /></>)}
        {needsDetails && <>
          <TextField required label="Устройство" value={details.name} onChange={(event) => setDetails({ ...details, name: event.target.value })} inputProps={{ maxLength: 160 }} />
          <TextField required label="Владелец" value={details.owner} onChange={(event) => setDetails({ ...details, owner: event.target.value })} inputProps={{ maxLength: 160 }} />
          <TextField multiline label="Комментарий" value={details.comment} onChange={(event) => setDetails({ ...details, comment: event.target.value })} inputProps={{ maxLength: 500 }} />
        </>}
      </Stack></DialogContent>
      <DialogActions>
        <Button disabled={saving} onClick={close}>Отмена</Button>
        <Button variant="contained" color={dialog?.mode === "revoke" ? "error" : "primary"} onClick={save}
          disabled={saving || Boolean(needsDetails && (!details.name.trim() || !details.owner.trim())) || (needsPackage && !operationId) || (dialog?.mode === "confirm" && !dialog.device?.crl_pending && !installationConfirmed)}
        >{saving ? "Сохраняем…" : dialog?.mode === "edit" ? "Сохранить" : dialog && titles[dialog.mode]}</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={!!issued} onClose={() => setCloseConfirmation(true)} fullWidth maxWidth="sm" aria-labelledby="issued-title">
      <DialogTitle id="issued-title">Сертификат выпущен</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        <Typography>Сертификат готов к установке. Скачайте файл и сохраните пароль.</Typography>
        <Typography>Устройство: <strong>{issued?.device.name}</strong></Typography>
        <Alert severity="warning">Пароль показывается только сейчас. Сохраните его в надёжном месте. После закрытия окна восстановить пароль будет невозможно.</Alert>
        <TextField label="Пароль PKCS12" type={showPassword ? "text" : "password"} value={issued?.password ?? ""} autoComplete="off" InputProps={{ readOnly: true }} />
        <Stack direction="row" gap={1} flexWrap="wrap">
          <Button onClick={() => setShowPassword((value) => !value)}>{showPassword ? "Скрыть пароль" : "Показать пароль"}</Button>
          <Button onClick={copyPassword}>{copied ? "Скопировано" : "Скопировать пароль"}</Button>
        </Stack>
        {secretError && <Alert severity="error">{secretError}</Alert>}
        <Typography variant="body2">В Windows откройте .p12 и импортируйте его в «Текущий пользователь → Личное». Храните файл и пароль раздельно.</Typography>
        {issued?.replacement && <Alert severity="info">Замена подготовлена. Старый сертификат продолжает работать. Установите новый и подтвердите замену отдельно со второго разрешённого устройства.</Alert>}
      </Stack></DialogContent>
      <DialogActions sx={{ flexWrap: "wrap", gap: 1 }}>
        <Button onClick={() => setCloseConfirmation(true)}>Готово</Button>
        <Button variant="contained" onClick={download}>Скачать сертификат (.p12)</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={!!issued && closeConfirmation} onClose={() => setCloseConfirmation(false)} aria-labelledby="close-issued-title">
      <DialogTitle id="close-issued-title">Закрыть окно выдачи?</DialogTitle>
      <DialogContent>Вы сохранили сертификат и пароль? После закрытия окна пароль больше не будет доступен.</DialogContent>
      <DialogActions>
        <Button onClick={() => setCloseConfirmation(false)}>Вернуться</Button>
        <Button onClick={clearIssued}>Да, закрыть</Button>
      </DialogActions>
    </Dialog>
  </Stack>;
}
