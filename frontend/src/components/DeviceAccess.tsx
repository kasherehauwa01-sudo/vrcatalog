import { useEffect, useState } from "react";
import {
  Alert, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogTitle, LinearProgress,
  MenuItem, Paper, Stack, Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
  TextField, Typography,
} from "@mui/material";
import { api, type AccessDevice, type DeviceDetails } from "../api/client";

type Mode = "issue" | "register" | "edit" | "replace" | "revoke";
const titles: Record<Mode, string> = {
  issue: "Выпустить сертификат", register: "Зарегистрировать сертификат",
  edit: "Редактировать устройство", replace: "Перевыпустить сертификат", revoke: "Заблокировать устройство",
};
const statusLabels = { active: "Активен", revoked: "Заблокирован", expired: "Истёк" };
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
  const [pem, setPem] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [issued, setIssued] = useState<{ name: string; certificate: string } | null>(null);

  const load = async () => {
    setListError("");
    try {
      setDevices(await api.accessDevices());
    } catch (failure) {
      setListError(failure instanceof Error ? failure.message : "Не удалось загрузить устройства");
    }
  };

  useEffect(() => { void load(); }, []);

  const open = (mode: Mode, device?: AccessDevice) => {
    setError("");
    setPem("");
    setDetails(device ? { name: device.name, owner: device.owner, comment: device.comment } : emptyDetails);
    setDialog({ mode, device });
  };

  const save = async () => {
    if (!dialog) return;
    const { mode, device } = dialog;
    const action = mode === "edit" ? String(device?.id)
      : mode === "replace" || mode === "revoke" ? `${device?.id}/${mode}` : mode;
    const data = mode === "revoke" ? undefined : mode === "edit" ? details
      : mode === "replace" ? { pem } : { ...details, pem };
    setSaving(true);
    setError("");
    try {
      const result = await api.saveAccessDevice(action, data, mode === "edit" ? "PATCH" : "POST");
      if ("certificate" in result) {
        setIssued({ name: result.device.common_name, certificate: result.certificate });
        setDevices((current) => [result.device, ...(current ?? []).map((item) =>
          item.id === device?.id ? { ...item, status: "revoked" as const } : item)]);
      } else {
        setDevices((current) => [result, ...(current ?? []).filter((item) => item.id !== result.id)]);
      }
      setPem("");
      setDialog(null);
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : "Не удалось сохранить изменения");
    } finally {
      setSaving(false);
    }
  };

  const download = () => {
    if (!issued) return;
    const url = URL.createObjectURL(new Blob([issued.certificate], { type: "application/x-pem-file" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = `${issued.name}.crt`;
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };

  const term = search.trim().toLocaleLowerCase("ru-RU");
  const visible = (devices ?? []).filter((device) =>
    (!status || device.status === status) &&
    [device.name, device.owner, device.common_name, device.fingerprint].some((value) => value.toLocaleLowerCase("ru-RU").includes(term)));
  const needsPem = dialog && ["issue", "register", "replace"].includes(dialog.mode);
  const needsDetails = dialog && ["issue", "register", "edit"].includes(dialog.mode);

  return <Stack spacing={2}>
    <Stack direction={{ xs: "column", md: "row" }} justifyContent="space-between" gap={2}>
      <Box><Typography variant="h6">Доступы устройств</Typography><Typography color="text.secondary" variant="body2">Клиентские сертификаты VR Catalog</Typography></Box>
      <Stack direction={{ xs: "column", sm: "row" }} gap={1}>
        <Button variant="outlined" onClick={() => open("register")}>{titles.register}</Button>
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
                <Button size="small" onClick={() => open("edit", device)}>Редактировать</Button>
                <Button size="small" onClick={() => open("replace", device)}>Перевыпустить</Button>
                {device.status === "active" && <Button size="small" color="error" onClick={() => open("revoke", device)}>Заблокировать</Button>}
              </Stack></TableCell>
            </TableRow>)}
          </TableBody>
        </Table>
      </TableContainer>}
    <Dialog open={!!dialog} onClose={saving ? undefined : () => setDialog(null)} fullWidth maxWidth="sm">
      <DialogTitle>{dialog && titles[dialog.mode]}</DialogTitle>
      <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
        {error && <Alert severity="error">{error}</Alert>}
        {dialog?.mode === "revoke" && <Typography>Заблокировать доступ для «{dialog.device?.name}»? Для восстановления доступа потребуется новый сертификат.</Typography>}
        {dialog?.mode === "replace" && <Alert severity="warning">При выпуске старый сертификат сразу блокируется. Если заменяете сертификат текущего устройства, убедитесь, что запрос с новым ключом создан на этом устройстве.</Alert>}
        {needsDetails && <>
          <TextField required label="Устройство" value={details.name} onChange={(event) => setDetails({ ...details, name: event.target.value })} inputProps={{ maxLength: 160 }} />
          <TextField required label="Владелец" value={details.owner} onChange={(event) => setDetails({ ...details, owner: event.target.value })} inputProps={{ maxLength: 160 }} />
          <TextField multiline label="Комментарий" value={details.comment} onChange={(event) => setDetails({ ...details, comment: event.target.value })} inputProps={{ maxLength: 500 }} />
        </>}
        {needsPem && <TextField required multiline minRows={5}
          label={dialog?.mode === "register" ? "Клиентский сертификат (PEM)" : "Запрос на сертификат (CSR в PEM)"}
          value={pem} onChange={(event) => setPem(event.target.value)} inputProps={{ maxLength: 16384 }}
          helperText={dialog?.mode === "register" ? "Сертификат должен быть подписан центром VR Catalog." : "Сгенерируйте запрос на устройстве владельца. Закрытый ключ оставьте на этом устройстве."}
        />}
      </Stack></DialogContent>
      <DialogActions>
        <Button disabled={saving} onClick={() => setDialog(null)}>Отмена</Button>
        <Button variant="contained" color={dialog?.mode === "revoke" ? "error" : "primary"} onClick={save}
          disabled={saving || Boolean(needsDetails && (!details.name.trim() || !details.owner.trim())) || Boolean(needsPem && !pem.trim())}
        >{saving ? "Сохраняем…" : dialog?.mode === "edit" ? "Сохранить" : dialog && titles[dialog.mode]}</Button>
      </DialogActions>
    </Dialog>
    <Dialog open={!!issued} onClose={() => setIssued(null)} fullWidth maxWidth="xs">
      <DialogTitle>Сертификат выпущен</DialogTitle>
      <DialogContent>Скачайте сертификат и установите его на устройство вместе с закрытым ключом, созданным при подготовке запроса.</DialogContent>
      <DialogActions><Button onClick={() => setIssued(null)}>Закрыть</Button><Button variant="contained" onClick={download}>Скачать сертификат</Button></DialogActions>
    </Dialog>
  </Stack>;
}
