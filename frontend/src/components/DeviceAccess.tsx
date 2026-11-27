import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Checkbox, Chip, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { api, type AccessDevice, type DeviceDetails } from "../api/client";

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
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [installationConfirmed, setInstallationConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [issued, setIssued] = useState<{ file: Blob; filename: string; replacement: boolean } | null>(null);
  const [downloadStarted, setDownloadStarted] = useState(false);

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
    setPassword("");
    setConfirmation("");
    setDialog(null);
  };

  const open = (mode: Mode, device?: AccessDevice) => {
    setError("");
    setInstallationConfirmed(false);
    setDetails(device ? { name: device.name, owner: device.owner, comment: device.comment } : emptyDetails);
    setDialog({ mode, device });
  };

  const save = async () => {
    if (!dialog) return;
    const { mode, device } = dialog;
    setSaving(true);
    setError("");
    try {
      if (mode === "issue" || mode === "replace") {
        const credentials = { password, password_confirmation: confirmation };
        const result = await api.downloadDevicePackage(
          mode === "issue" ? "issue-package" : `${device?.id}/replacements/prepare`,
          mode === "issue" ? { ...details, ...credentials } : credentials,
        );
        setDownloadStarted(false);
        setIssued({ ...result, replacement: mode === "replace" });
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
      setPassword("");
      setConfirmation("");
    } finally {
      setSaving(false);
      void load();
    }
  };

  const download = () => {
    if (!issued) return;
    const url = URL.createObjectURL(issued.file);
    const link = document.createElement("a");
    link.href = url;
    link.download = issued.filename;
    link.click();
    setDownloadStarted(true);
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const term = search.trim().toLocaleLowerCase("ru-RU");
  const visible = (devices ?? []).filter((device) =>
    (!status || device.status === status) &&
    [device.name, device.owner, device.common_name, device.fingerprint].some((value) => value.toLocaleLowerCase("ru-RU").includes(term)));
  const needsPassword = dialog?.mode === "issue" || dialog?.mode === "replace";
  const needsDetails = dialog?.mode === "issue" || dialog?.mode === "edit";
  const validPassword = [...password].length >= 12 && new TextEncoder().encode(password).length <= 127
    && Boolean(password.trim()) && !password.includes("\x00") && password === confirmation;
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
        {needsPassword && <>
          <TextField required type="password" autoComplete="new-password" label="Пароль для сертификата"
            value={password} onChange={(event) => setPassword(event.target.value)} inputProps={{ maxLength: 127 }}
            helperText="Минимум 12 символов, не более 127 байт" />
          <TextField required type="password" autoComplete="new-password" label="Подтверждение пароля"
            value={confirmation} onChange={(event) => setConfirmation(event.target.value)} inputProps={{ maxLength: 127 }}
            error={!!confirmation && password !== confirmation} helperText={confirmation && password !== confirmation ? "Пароли не совпадают" : undefined} />
        </>}
      </Stack></DialogContent>
      <DialogActions>
        <Button disabled={saving} onClick={close}>Отмена</Button>
        <Button variant="contained" color={dialog?.mode === "revoke" ? "error" : "primary"} onClick={save}
          disabled={saving || Boolean(needsDetails && (!details.name.trim() || !details.owner.trim())) || (needsPassword && !validPassword) || (dialog?.mode === "confirm" && !dialog.device?.crl_pending && !installationConfirmed)}
        >{saving ? "Сохраняем…" : dialog?.mode === "edit" ? "Сохранить" : dialog && titles[dialog.mode]}</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={!!issued} disableEscapeKeyDown fullWidth maxWidth="sm">
      <DialogTitle>{issued?.replacement ? "Замена подготовлена" : "Сертификат выпущен"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Alert severity="warning">Сохраните файл .p12. Повторно скачать этот закрытый ключ невозможно. Храните файл и пароль раздельно.</Alert>
          <Typography>В Windows откройте .p12, выберите «Текущий пользователь», введите пароль и импортируйте в хранилище «Личное». Оставьте параметр экспорта закрытого ключа выключенным. Перезапустите браузер и выберите сертификат при подключении.</Typography>
          {issued?.replacement && <Typography>Проверьте наличие сертификата в хранилище Windows. Затем подтвердите замену в списке устройств со второго разрешённого устройства.</Typography>}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button disabled={!downloadStarted} onClick={() => setIssued(null)}>Готово</Button>
        <Button variant="contained" onClick={download}>Скачать .p12</Button>
      </DialogActions>
    </Dialog>
  </Stack>;
}
