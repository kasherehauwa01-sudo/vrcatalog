import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { alpha, AppBar, Box, Button, Card, CardContent, Chip, Container, CssBaseline, Divider, Drawer, IconButton, InputAdornment, LinearProgress, List, Paper, Stack, Tab, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Tabs, TextField, ThemeProvider, Toolbar, Typography, createTheme } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FavoriteBorderIcon from '@mui/icons-material/FavoriteBorder';
import SearchIcon from '@mui/icons-material/Search';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import { api } from './api/client';
import type { Meta, Product, ProductDetail } from './types/catalog';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#0284c7' },
    secondary: { main: '#0369a1' },
    background: { default: '#f0f9ff', paper: '#ffffff' },
  },
  typography: {
    fontFamily: 'Inter, Roboto, Arial, sans-serif',
    h4: { fontWeight: 800, letterSpacing: '-0.04em' },
    h6: { fontWeight: 800 },
  },
  shape: { borderRadius: 24 },
  components: {
    MuiCard: { styleOverrides: { root: { border: '1px solid rgba(2,132,199,0.14)', boxShadow: '0 16px 48px rgba(2,132,199,0.10)' } } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { borderRadius: 999, textTransform: 'none', fontWeight: 700 } } },
    MuiTextField: { defaultProps: { variant: 'outlined' } },
    MuiChip: { styleOverrides: { root: { borderRadius: 999, fontWeight: 600 } } },
  },
});

const labels: Record<string,string> = { section:'Раздел', manufacturer:'Производитель', brand:'Бренд', manager:'Менеджер', country:'Страна', material:'Материал', color:'Цвет' };
const updateScriptPath = '/var/www/html/vr/update_vrcatalog.sh';

function App() {
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Record<string,string[]>>({});
  const [active, setActive] = useState<Record<string,string>>({});
  const [products, setProducts] = useState<Product[]>([]);
  const [meta, setMeta] = useState<Meta>({ product_count: 0 });
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const [tab, setTab] = useState<'catalog' | 'settings'>('catalog');
  const [uploadError, setUploadError] = useState<string | null>(null);
  const params = useMemo(() => { const p = new URLSearchParams({ search }); Object.entries(active).forEach(([k,v]) => v && p.set(k,v)); return p; }, [search, active]);
  const reload = () => { api.products(params).then(setProducts); api.meta().then(setMeta); api.filters().then(setFilters); };
  useEffect(reload, [params]);
  const upload = async (file?: File) => { if (!file) return; setLoading(true); setUploadError(null); try { setMeta(await api.upload(file)); reload(); } catch (error) { setUploadError(error instanceof Error ? error.message : 'Не удалось загрузить XML'); } finally { setLoading(false); } };
  const copy = (value?: string) => value && navigator.clipboard.writeText(value);

  return <ThemeProvider theme={theme}><CssBaseline />
    <Box sx={{ minHeight: '100vh', background: 'radial-gradient(circle at top left, #e0f2fe 0, #f0f9ff 42%, #ffffff 100%)' }}>
      <AppBar position="sticky" color="transparent" elevation={0} sx={{ backdropFilter: 'blur(20px)', borderBottom: '1px solid', borderColor: alpha('#0284c7', 0.14) }}>
        <Toolbar sx={{ gap: 2, py: 1 }}>

          <TextField fullWidth size="small" placeholder="Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам" value={search} onChange={e=>setSearch(e.target.value)} InputProps={{ startAdornment: <SearchIcon color="action" sx={{ mr: 1 }} /> }} sx={{ '& .MuiOutlinedInput-root': { bgcolor: alpha('#ffffff', .86), borderRadius: 999 } }} />
          <Button variant="contained" startIcon={<UploadFileIcon />} component="label" sx={{ fontSize: 12, whiteSpace: 'nowrap', px: 2 }}>Загрузить XML<input hidden type="file" accept=".xml" onChange={e=>upload(e.target.files?.[0])}/></Button>
        </Toolbar>{loading && <LinearProgress />}
      </AppBar>

      <Container maxWidth="xl" sx={{ py: { xs: 2, md: 4 } }}>
        {uploadError && <Card sx={{ mb: 3 }}><CardContent><Typography color="error">{uploadError}</Typography></CardContent></Card>}

        <Paper sx={{ mb: 3, px: 1, bgcolor: alpha('#ffffff', .78), border: '1px solid rgba(2,132,199,.14)' }} elevation={0}>
          <Tabs value={tab} onChange={(_, value) => setTab(value)} textColor="primary" indicatorColor="primary" variant="scrollable">
            <Tab value="catalog" label="Каталог" />
            <Tab value="settings" label="Настройки" />
          </Tabs>
        </Paper>

        {tab === 'settings' && <Card sx={{ maxWidth: 900 }}><CardContent><Typography variant="h6">Настройки</Typography><Typography color="text.secondary" sx={{ mt: 1, mb: 2 }}>Путь к скрипту обновления каталога на сервере. Нажмите на иконку, чтобы скопировать значение.</Typography><TextField fullWidth label="Скрипт обновления" value={updateScriptPath} InputProps={{ readOnly: true, endAdornment: <InputAdornment position="end"><IconButton aria-label="Скопировать путь к скрипту обновления" onClick={() => copy(updateScriptPath)}><ContentCopyIcon /></IconButton></InputAdornment> }} /></CardContent></Card>}

        {tab === 'catalog' && <Stack direction={{ xs:'column', md:'row' }} spacing={3} alignItems="flex-start">
          <Card sx={{ width:{ xs:'100%', md:304 }, flexShrink:0, position: { md: 'sticky' }, top: 96 }}><CardContent><Typography variant="h6">Фильтры</Typography>{meta.errors && <Typography sx={{ mt: 1 }} color="error">Ошибки импорта: {meta.errors}</Typography>}<Divider sx={{ my: 2 }} />
            <List disablePadding>{Object.entries(labels).map(([key,label]) => <Box key={key} sx={{ mb: 2 }}><Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>{label}</Typography><Stack direction="row" flexWrap="wrap" gap={1}>{(filters[key] ?? []).slice(0,24).map(v => <Chip clickable color={active[key]===v ? 'primary' : 'default'} variant={active[key]===v ? 'filled' : 'outlined'} key={v} label={v} onClick={()=>setActive(a=>({...a,[key]:a[key]===v?'':v}))} />)}</Stack></Box>)}</List>
            <Divider sx={{ my: 2 }} /><Button href={api.exportUrl('xlsx', search)}>Экспорт Excel</Button>
          </CardContent></Card>

          <TableContainer component={Card} sx={{ flex: 1 }}><Table><TableHead><TableRow><TableCell>Наименование</TableCell><TableCell>Артикул</TableCell><TableCell>Код</TableCell><TableCell>Раздел</TableCell><TableCell align="right">Розничная цена</TableCell><TableCell align="right">Остаток</TableCell><TableCell /></TableRow></TableHead><TableBody>{products.map(p => <TableRow hover key={p.id} onClick={()=>api.product(p.id).then(setDetail)} sx={{ cursor: 'pointer' }}><TableCell><Typography fontWeight={800}>{p.name}</Typography></TableCell><TableCell>{p.article ?? '—'}</TableCell><TableCell>{p.code}</TableCell><TableCell>{p.section ? <Chip size="small" label={p.section}/> : '—'}</TableCell><TableCell align="right">{p.retail_price ?? '—'}</TableCell><TableCell align="right">{p.quantity}</TableCell><TableCell align="right"><IconButton size="small" onClick={(e)=>{e.stopPropagation(); copy(p.article)}}><ContentCopyIcon fontSize="small" /></IconButton></TableCell></TableRow>)}</TableBody></Table></TableContainer>
        </Stack>}
      </Container>

      <Drawer anchor="right" open={!!detail} onClose={()=>setDetail(null)} PaperProps={{ sx: { borderTopLeftRadius: 28, borderBottomLeftRadius: 28 } }}><Box sx={{ width:{ xs:'100vw', sm:620 }, p:3 }}>{detail && <Stack spacing={2}><Typography variant="h5" fontWeight={900}>{detail.name}</Typography><Stack direction="row" gap={1} flexWrap="wrap"><Button startIcon={<FavoriteBorderIcon/>}>В избранное</Button><Button onClick={()=>copy(detail.article)}>Копировать артикул</Button><Button onClick={()=>copy(detail.code)}>Копировать код</Button><Button onClick={()=>copy(detail.barcodes.map(b=>b.value).join(', '))}>Штрихкоды</Button></Stack><Paper variant="outlined" sx={{ p: 2 }}><Typography>Код: {detail.code}</Typography><Typography>Артикул: {detail.article ?? '—'}</Typography><Typography>Раздел: {detail.section}</Typography><Typography>Производитель: {detail.manufacturer ?? '—'}</Typography><Typography>Менеджер: {detail.manager ?? '—'}</Typography><Typography>Бренд: {detail.brand ?? '—'}</Typography><Typography>Материал: {detail.material ?? '—'}</Typography><Typography>Цвет: {detail.color ?? '—'}</Typography><Typography>Сертификат: {detail.certificate ?? '—'}</Typography><Typography>Штрихкоды: {detail.barcodes.length ? detail.barcodes.map(b => b.value).join(', ') : '—'}</Typography><Typography sx={{ mt: 1 }}>{detail.description}</Typography></Paper><Typography fontWeight={800}>Цены</Typography>{detail.prices.map(p=><Typography key={p.price_type}>{p.price_type}: {p.value}</Typography>)}<Typography fontWeight={800}>Характеристики</Typography>{detail.properties.map((p, index)=><Typography key={`${p.property_code ?? p.name}-${index}`}>{p.name}: {p.value ?? '—'}</Typography>)}<Typography fontWeight={800}>Остатки по складам</Typography><Table size="small"><TableHead><TableRow><TableCell>Склад</TableCell><TableCell align="right">Остаток</TableCell></TableRow></TableHead><TableBody>{detail.stocks.map(s=><TableRow key={s.warehouse}><TableCell>{s.warehouse}</TableCell><TableCell align="right">{s.quantity}</TableCell></TableRow>)}</TableBody></Table><Typography fontWeight={800}>Аналоги</Typography>{detail.analogs.map(a=><Typography key={a.code}>{a.code} {a.name}</Typography>)}</Stack>}</Box></Drawer>
    </Box>
  </ThemeProvider>;
}

createRoot(document.getElementById('root')!).render(<App />);
