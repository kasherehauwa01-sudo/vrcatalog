import { useEffect, useRef, useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Fab,
  FormControlLabel,
  IconButton,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import FlashlightOffIcon from "@mui/icons-material/FlashlightOff";
import FlashlightOnIcon from "@mui/icons-material/FlashlightOn";

type BarcodeDetectorResult = { rawValue: string };
type BarcodeDetectorInstance = {
  detect(source: HTMLVideoElement): Promise<BarcodeDetectorResult[]>;
};
type BarcodeDetectorConstructor = new (options: { formats: string[] }) => BarcodeDetectorInstance;

declare global {
  interface Window {
    BarcodeDetector?: BarcodeDetectorConstructor;
  }
}

const isEan13 = (value: string) => {
  if (!/^\d{13}$/.test(value)) return false;
  const digits = [...value].map(Number);
  const sum = digits.slice(0, 12).reduce(
    (total, digit, index) => total + digit * (index % 2 === 0 ? 1 : 3),
    0,
  );
  return (10 - (sum % 10)) % 10 === digits[12];
};

const playSignal = (found: boolean) => {
  const AudioContextClass = window.AudioContext;
  if (!AudioContextClass) return;
  const context = new AudioContextClass();
  const frequencies = found ? [880, 1175] : [220, 165];
  frequencies.forEach((frequency, index) => {
    const oscillator = context.createOscillator();
    const gain = context.createGain();
    const start = context.currentTime + index * 0.13;
    oscillator.frequency.value = frequency;
    gain.gain.setValueAtTime(0.12, start);
    gain.gain.exponentialRampToValueAtTime(0.001, start + 0.11);
    oscillator.connect(gain).connect(context.destination);
    oscillator.start(start);
    oscillator.stop(start + 0.12);
  });
  window.setTimeout(() => void context.close(), 500);
};

function ScanBarcodeIcon() {
  return (
    <Box component="svg" viewBox="0 0 24 24" sx={{ width: 56, height: 56, fill: "none", stroke: "currentColor", strokeWidth: 1.8 }}>
      <path d="M4 8V5a1 1 0 0 1 1-1h3M16 4h3a1 1 0 0 1 1 1v3M20 16v3a1 1 0 0 1-1 1h-3M8 20H5a1 1 0 0 1-1-1v-3" />
      <path d="M7 8v8M10 8v8M13 8v8M17 8v8" />
    </Box>
  );
}

type Props = {
  onDetected: (barcode: string) => Promise<boolean>;
};

export function BarcodeScanner({ onDetected }: Props) {
  const [open, setOpen] = useState(false);
  const [soundEnabled, setSoundEnabled] = useState(true);
  const [torchEnabled, setTorchEnabled] = useState(false);
  const [torchAvailable, setTorchAvailable] = useState(false);
  const [status, setStatus] = useState<"scanning" | "searching" | "not-found">("scanning");
  const [error, setError] = useState<string | null>(null);
  const [manualBarcode, setManualBarcode] = useState("");
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const busyRef = useRef(false);
  const soundEnabledRef = useRef(true);

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    setTorchEnabled(false);
    setTorchAvailable(false);
  };

  const close = () => {
    stopCamera();
    setOpen(false);
  };

  const processBarcode = async (value: string) => {
    const barcode = value.trim();
    if (busyRef.current || !isEan13(barcode)) return;
    busyRef.current = true;
    setStatus("searching");
    const found = await onDetected(barcode).catch(() => false);
    if (soundEnabledRef.current) playSignal(found);
    if (found) {
      close();
    } else {
      setStatus("not-found");
      window.setTimeout(() => {
        busyRef.current = false;
        setStatus("scanning");
      }, 1400);
    }
  };

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    let frame = 0;
    const start = async () => {
      setError(null);
      setStatus("scanning");
      busyRef.current = false;
      if (!navigator.mediaDevices?.getUserMedia) {
        setError("Камера недоступна в этом браузере. Введите штрихкод вручную.");
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: { facingMode: { ideal: "environment" } },
        });
        if (cancelled) {
          stream.getTracks().forEach((track) => track.stop());
          return;
        }
        streamRef.current = stream;
        const track = stream.getVideoTracks()[0];
        setTorchAvailable(Boolean(track.getCapabilities && "torch" in track.getCapabilities()));
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
        if (!window.BarcodeDetector) {
          setError("Автоматическое распознавание не поддерживается. Введите EAN-13 вручную.");
          return;
        }
        const detector = new window.BarcodeDetector({ formats: ["ean_13"] });
        const scan = async () => {
          if (cancelled) return;
          if (!busyRef.current && videoRef.current?.readyState === HTMLMediaElement.HAVE_ENOUGH_DATA) {
            const results = await detector.detect(videoRef.current).catch(() => []);
            const result = results.find(({ rawValue }) => isEan13(rawValue));
            if (result) void processBarcode(result.rawValue);
          }
          frame = window.requestAnimationFrame(scan);
        };
        frame = window.requestAnimationFrame(scan);
      } catch {
        setError("Не удалось включить камеру. Разрешите доступ или введите штрихкод вручную.");
      }
    };
    void start();
    return () => {
      cancelled = true;
      window.cancelAnimationFrame(frame);
      stopCamera();
    };
  }, [open]);

  const toggleTorch = async () => {
    const track = streamRef.current?.getVideoTracks()[0];
    if (!track) return;
    const next = !torchEnabled;
    try {
      await track.applyConstraints({ advanced: [{ torch: next } as MediaTrackConstraintSet] });
      setTorchEnabled(next);
    } catch {
      setTorchAvailable(false);
    }
  };

  return (
    <>
      <Tooltip title="Сканировать штрихкод" placement="left">
        <Fab
          color="primary"
          aria-label="Сканировать штрихкод"
          onClick={() => setOpen(true)}
          sx={{
            // На телефонах с широким экраном и планшетах ширина viewport может
            // превышать 600 px, поэтому скрываем кнопку только на desktop (lg).
            display: { xs: "inline-flex", lg: "none" },
            position: "fixed",
            right: { xs: 16, sm: 24 },
            bottom: "max(16px, calc(env(safe-area-inset-bottom) + 12px))",
            zIndex: (theme) => theme.zIndex.drawer + 1,
            boxShadow: "0 10px 28px rgba(2, 132, 199, .42)",
            width: 80,
            height: 80,
          }}
        >
          <ScanBarcodeIcon />
        </Fab>
      </Tooltip>
      <Dialog open={open} onClose={close} fullScreen>
        <DialogTitle sx={{ pr: 7 }}>
          Сканировать штрихкод
          <IconButton aria-label="Закрыть сканер" onClick={close} sx={{ position: "absolute", right: 12, top: 10 }}><CloseIcon /></IconButton>
        </DialogTitle>
        <DialogContent sx={{ p: 2, bgcolor: "#08111f" }}>
          <Stack spacing={2} sx={{ height: "100%" }}>
            <Box sx={{ position: "relative", minHeight: 300, flex: 1, overflow: "hidden", borderRadius: 4, bgcolor: "#000" }}>
              <Box component="video" ref={videoRef} muted playsInline sx={{ width: "100%", height: "100%", objectFit: "cover", position: "absolute" }} />
              <Box sx={{ position: "absolute", left: "8%", right: "8%", top: "38%", height: 110, border: "3px solid", borderColor: status === "not-found" ? "error.main" : "primary.light", borderRadius: 3, boxShadow: "0 0 0 999px rgba(0,0,0,.38)" }} />
              <Typography sx={{ position: "absolute", bottom: 22, width: "100%", textAlign: "center", color: "white", fontWeight: 700 }}>
                {status === "searching" ? <><CircularProgress size={18} color="inherit" sx={{ mr: 1 }} />Ищем товар…</> : status === "not-found" ? "Товар не найден" : "Наведите камеру на штрихкод EAN-13"}
              </Typography>
            </Box>
            {error && <Alert severity="warning">{error}</Alert>}
            <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ color: "white" }}>
              <FormControlLabel control={<Switch checked={soundEnabled} onChange={(_, checked) => { setSoundEnabled(checked); soundEnabledRef.current = checked; }} />} label="Звуковые сигналы" />
              <Button color="inherit" startIcon={torchEnabled ? <FlashlightOnIcon /> : <FlashlightOffIcon />} disabled={!torchAvailable} onClick={toggleTorch}>
                Фонарик
              </Button>
            </Stack>
            <Stack direction="row" spacing={1}>
              <TextField fullWidth size="small" label="EAN-13 вручную" value={manualBarcode} error={manualBarcode.length > 0 && !isEan13(manualBarcode)} onChange={(event) => setManualBarcode(event.target.value.replace(/\D/g, "").slice(0, 13))} sx={{ bgcolor: "white", borderRadius: 1 }} />
              <Button variant="contained" disabled={!isEan13(manualBarcode) || status === "searching"} onClick={() => void processBarcode(manualBarcode)}>Найти</Button>
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions><Button onClick={close}>Закрыть</Button></DialogActions>
      </Dialog>
    </>
  );
}
