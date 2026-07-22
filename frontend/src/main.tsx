import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { alpha, AppBar, Avatar, Box, Button, Card, CardActionArea, CardContent, CardMedia, Chip, Container, CssBaseline, Divider, Drawer, Grid, IconButton, LinearProgress, List, ListItemButton, Paper, Stack, TextField, ThemeProvider, Toolbar, Typography, createTheme } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FavoriteBorderIcon from '@mui/icons-material/FavoriteBorder';
import SearchIcon from '@mui/icons-material/Search';
import UploadFileIcon from '@mui/icons-material/UploadFile';
import Inventory2OutlinedIcon from '@mui/icons-material/Inventory2Outlined';
import FileDownloadOutlinedIcon from '@mui/icons-material/FileDownloadOutlined';
import { api } from './api/client';
import type { Meta, Product, ProductDetail } from './types/catalog';

const theme = createTheme({
  palette: {
    mode: 'light',
    primary: { main: '#6750a4' },
    secondary: { main: '#625b71' },
    background: { default: '#fffbfe', paper: '#fff7ff' },
  },
  typography: {
    fontFamily: 'Inter, Roboto, Arial, sans-serif',
    h4: { fontWeight: 800, letterSpacing: '-0.04em' },
    h6: { fontWeight: 800 },
  },
  shape: { borderRadius: 24 },
  components: {
    MuiCard: { styleOverrides: { root: { border: '1px solid rgba(103,80,164,0.12)', boxShadow: '0 16px 48px rgba(31,27,36,0.08)' } } },
    MuiButton: { defaultProps: { disableElevation: true }, styleOverrides: { root: { borderRadius: 999, textTransform: 'none', fontWeight: 700 } } },
    MuiTextField: { defaultProps: { variant: 'outlined' } },
    MuiChip: { styleOverrides: { root: { borderRadius: 999, fontWeight: 600 } } },
  },
});

const labels: Record<string,string> = { section:'Раздел', manufacturer:'Производитель', brand:'Бренд', manager:'Менеджер', country:'Страна', material:'Материал', color:'Цвет' };

function App() {
  const [search, setSearch] = useState('');
  const [filters, setFilters] = useState<Record<string,string[]>>({});
  const [active, setActive] = useState<Record<string,string>>({});
  const [products, setProducts] = useState<Product[]>([]);
  const [meta, setMeta] = useState<Meta>({ product_count: 0 });
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<ProductDetail | null>(null);
  const params = useMemo(() => { const p = new URLSearchParams({ search }); Object.entries(active).forEach(([k,v]) => v && p.set(k,v)); return p; }, [search, active]);
  const reload = () => { api.products(params).then(setProducts); api.meta().then(setMeta); api.filters().then(setFilters); };
  useEffect(reload, [params]);
  const upload = async (file?: File) => { if (!file) return; setLoading(true); try { setMeta(await api.upload(file)); reload(); } finally { setLoading(false); } };
  const copy = (value?: string) => value && navigator.clipboard.writeText(value);

  return <ThemeProvider theme={theme}><CssBaseline />
    <Box sx={{ minHeight: '100vh', background: 'radial-gradient(circle at top left, #f4efff 0, #fffbfe 38%, #fef7ff 100%)' }}>
      <AppBar position="sticky" color="transparent" elevation={0} sx={{ backdropFilter: 'blur(20px)', borderBottom: '1px solid', borderColor: alpha('#6750a4', 0.12) }}>
        <Toolbar sx={{ gap: 2, py: 1 }}>
          <Avatar sx={{ bgcolor: 'primary.main', boxShadow: '0 8px 24px rgba(103,80,164,.35)' }}><Inventory2OutlinedIcon /></Avatar>
          <Box sx={{ display: { xs: 'none', sm: 'block' } }}><Typography variant="h6">VR Catalog</Typography><Typography variant="caption" color="text.secondary">каталог товаров</Typography></Box>
          <TextField fullWidth size="small" placeholder="Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам" value={search} onChange={e=>setSearch(e.target.value)} InputProps={{ startAdornment: <SearchIcon color="action" sx={{ mr: 1 }} /> }} sx={{ '& .MuiOutlinedInput-root': { bgcolor: alpha('#ffffff', .86), borderRadius: 999 } }} />
          <Button variant="contained" startIcon={<UploadFileIcon />} component="label">Загрузить XML<input hidden type="file" accept=".xml" onChange={e=>upload(e.target.files?.[0])}/></Button>
        </Toolbar>{loading && <LinearProgress />}
      </AppBar>

      <Container maxWidth="xl" sx={{ py: { xs: 2, md: 4 } }}>
        <Paper sx={{ p: { xs: 2, md: 4 }, mb: 3, overflow: 'hidden', background: 'linear-gradient(135deg, #eaddff 0%, #fff7ff 55%, #f3edf7 100%)', border: '1px solid rgba(103,80,164,.14)' }} elevation={0}>
          <Stack direction={{ xs:'column', md:'row' }} justifyContent="space-between" spacing={2}>
            <Box><Typography variant="h4">Современный каталог товаров</Typography><Typography color="text.secondary" sx={{ mt: 1 }}>Импортируйте XML и работайте с быстрым поиском, фильтрами и экспортом из базы данных.</Typography></Box>
            <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap><Chip label={`Товаров: ${meta.product_count}`} color="primary" /><Chip label={`Загрузка: ${meta.last_import ? new Date(meta.last_import).toLocaleString() : 'нет'}`} variant="outlined" />{meta.imported_count !== undefined && <Chip label={`Импортировано: ${meta.imported_count}`} />}</Stack>
          </Stack>
        </Paper>

        <Stack direction={{ xs:'column', md:'row' }} spacing={3} alignItems="flex-start">
          <Card sx={{ width:{ xs:'100%', md:304 }, flexShrink:0, position: { md: 'sticky' }, top: 96 }}><CardContent><Typography variant="h6">Фильтры</Typography>{meta.errors && <Typography sx={{ mt: 1 }} color="error">Ошибки импорта: {meta.errors}</Typography>}<Divider sx={{ my: 2 }} />
            <List disablePadding>{Object.entries(labels).map(([key,label]) => <Box key={key} sx={{ mb: 2 }}><Typography variant="subtitle2" color="text.secondary" sx={{ mb: 1 }}>{label}</Typography><Stack direction="row" flexWrap="wrap" gap={1}>{(filters[key] ?? []).slice(0,24).map(v => <Chip clickable color={active[key]===v ? 'primary' : 'default'} variant={active[key]===v ? 'filled' : 'outlined'} key={v} label={v} onClick={()=>setActive(a=>({...a,[key]:a[key]===v?'':v}))} />)}</Stack></Box>)}</List>
            <Divider sx={{ my: 2 }} /><Stack direction="row" spacing={1}><Button startIcon={<FileDownloadOutlinedIcon />} href={api.exportUrl('csv', search)}>CSV</Button><Button startIcon={<FileDownloadOutlinedIcon />} href={api.exportUrl('xlsx', search)}>Excel</Button></Stack>
          </CardContent></Card>

          <Grid container spacing={2.5}>{products.map(p => <Grid item xs={12} sm={6} md={4} lg={3} key={p.id}><Card sx={{ height:'100%', overflow: 'hidden', transition: '.2s ease', '&:hover': { transform: 'translateY(-4px)', boxShadow: '0 24px 64px rgba(31,27,36,0.14)' } }}><CardActionArea onClick={()=>api.product(p.id).then(setDetail)} sx={{ height: '100%', alignItems: 'stretch' }}>{p.image ? <CardMedia component="img" height="180" image={p.image} /> : <Box sx={{ height: 180, display: 'grid', placeItems: 'center', bgcolor: '#eaddff' }}><Inventory2OutlinedIcon color="primary" fontSize="large" /></Box>}<CardContent><Stack direction="row" justifyContent="space-between" alignItems="flex-start" gap={1}><Typography fontWeight={800}>{p.name}</Typography><IconButton size="small" onClick={(e)=>{e.stopPropagation(); copy(p.article)}}><ContentCopyIcon fontSize="small" /></IconButton></Stack><Typography color="text.secondary">Арт.: {p.article ?? '—'}</Typography><Typography sx={{ mt: 1 }} fontWeight={800}>₽ {p.retail_price ?? '—'}</Typography><Typography color="text.secondary">Остаток: {p.quantity}</Typography>{p.section && <Chip sx={{ mt: 1 }} size="small" label={p.section}/>}</CardContent></CardActionArea></Card></Grid>)}</Grid>
        </Stack>
      </Container>

      <Drawer anchor="right" open={!!detail} onClose={()=>setDetail(null)} PaperProps={{ sx: { borderTopLeftRadius: 28, borderBottomLeftRadius: 28 } }}><Box sx={{ width:{ xs:'100vw', sm:620 }, p:3 }}>{detail && <Stack spacing={2}><Typography variant="h5" fontWeight={900}>{detail.name}</Typography><Stack direction="row" gap={1} flexWrap="wrap"><Button startIcon={<FavoriteBorderIcon/>}>В избранное</Button><Button onClick={()=>copy(detail.article)}>Копировать артикул</Button><Button onClick={()=>copy(detail.code)}>Копировать код</Button><Button onClick={()=>copy(detail.barcodes.map(b=>b.value).join('\n'))}>Штрихкоды</Button></Stack><Paper variant="outlined" sx={{ p: 2 }}><Typography>Код: {detail.code}</Typography><Typography>Раздел: {detail.section}</Typography><Typography sx={{ mt: 1 }}>{detail.description}</Typography></Paper><Typography fontWeight={800}>Цены</Typography>{detail.prices.map(p=><Typography key={p.price_type}>{p.price_type}: {p.value}</Typography>)}<Typography fontWeight={800}>Характеристики</Typography>{detail.properties.map(p=><Typography key={p.name}>{p.name}: {p.value}</Typography>)}<Typography fontWeight={800}>Остатки по складам</Typography>{detail.stocks.map(s=><Typography key={s.warehouse}>{s.warehouse}: {s.quantity}</Typography>)}<Typography fontWeight={800}>Аналоги</Typography>{detail.analogs.map(a=><Typography key={a.code}>{a.code} {a.name}</Typography>)}</Stack>}</Box></Drawer>
    </Box>
  </ThemeProvider>;
}

createRoot(document.getElementById('root')!).render(<App />);
