import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { AppBar, Box, Button, Card, CardContent, CardMedia, Chip, Container, CssBaseline, Drawer, Grid, IconButton, LinearProgress, List, ListItemButton, Stack, TextField, ThemeProvider, Toolbar, Typography, createTheme } from '@mui/material';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import FavoriteBorderIcon from '@mui/icons-material/FavoriteBorder';
import { api } from './api/client';
import type { Meta, Product, ProductDetail } from './types/catalog';

const theme = createTheme({ palette: { mode: 'light', primary: { main: '#2563eb' }, background: { default: '#f8fafc' } }, shape: { borderRadius: 14 } });
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
    <AppBar position="sticky" color="inherit" elevation={0}><Toolbar sx={{ gap: 2 }}>
      <Typography variant="h6" fontWeight={800}>VR Catalog</Typography>
      <TextField fullWidth size="small" placeholder="Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам" value={search} onChange={e=>setSearch(e.target.value)} />
      <Button variant="contained" component="label">Загрузить XML<input hidden type="file" accept=".xml" onChange={e=>upload(e.target.files?.[0])}/></Button>
    </Toolbar>{loading && <LinearProgress />}</AppBar>
    <Container maxWidth="xl" sx={{ py: 3 }}><Stack direction={{ xs:'column', md:'row' }} spacing={3}>
      <Box sx={{ width:{ xs:'100%', md:280 }, flexShrink:0 }}><Card><CardContent><Typography fontWeight={700}>Фильтры</Typography><Typography variant="body2" color="text.secondary">Последняя загрузка: {meta.last_import ? new Date(meta.last_import).toLocaleString() : 'нет'}</Typography><Typography variant="body2">Товаров: {meta.product_count}</Typography>{meta.imported_count !== undefined && <Typography variant="body2">Импортировано: {meta.imported_count}</Typography>}{meta.errors && <Typography color="error">Ошибки импорта: {meta.errors}</Typography>}<List>{Object.entries(labels).map(([key,label]) => <Box key={key}><Typography sx={{ mt:2 }} variant="subtitle2">{label}</Typography>{(filters[key] ?? []).slice(0,20).map(v => <ListItemButton selected={active[key]===v} key={v} onClick={()=>setActive(a=>({...a,[key]:a[key]===v?'':v}))}>{v}</ListItemButton>)}</Box>)}</List><Stack direction="row"><Button href={api.exportUrl('csv', search)}>CSV</Button><Button href={api.exportUrl('xlsx', search)}>Excel</Button></Stack></CardContent></Card></Box>
      <Grid container spacing={2}>{products.map(p => <Grid item xs={12} sm={6} md={4} lg={3} key={p.id}><Card onClick={()=>api.product(p.id).then(setDetail)} sx={{ height:'100%', cursor:'pointer' }}>{p.image && <CardMedia component="img" height="160" image={p.image} /> }<CardContent><Stack direction="row" justifyContent="space-between"><Typography fontWeight={700}>{p.name}</Typography><IconButton onClick={(e)=>{e.stopPropagation(); copy(p.article)}}><ContentCopyIcon /></IconButton></Stack><Typography color="text.secondary">Арт.: {p.article ?? '—'}</Typography><Typography>Розничная цена: {p.retail_price ?? '—'}</Typography><Typography>Остаток: {p.quantity}</Typography>{p.section && <Chip size="small" label={p.section}/>}</CardContent></Card></Grid>)}</Grid>
    </Stack></Container>
    <Drawer anchor="right" open={!!detail} onClose={()=>setDetail(null)}><Box sx={{ width:{ xs:'100vw', sm:560 }, p:3 }}>{detail && <Stack spacing={2}><Typography variant="h5" fontWeight={800}>{detail.name}</Typography><Stack direction="row" gap={1}><Button startIcon={<FavoriteBorderIcon/>}>В избранное</Button><Button onClick={()=>copy(detail.article)}>Копировать артикул</Button><Button onClick={()=>copy(detail.code)}>Копировать код</Button><Button onClick={()=>copy(detail.barcodes.map(b=>b.value).join('\n'))}>Штрихкоды</Button></Stack><Typography>Код: {detail.code}</Typography><Typography>Раздел: {detail.section}</Typography><Typography>{detail.description}</Typography><Typography fontWeight={700}>Цены</Typography>{detail.prices.map(p=><Typography key={p.price_type}>{p.price_type}: {p.value}</Typography>)}<Typography fontWeight={700}>Характеристики</Typography>{detail.properties.map(p=><Typography key={p.name}>{p.name}: {p.value}</Typography>)}<Typography fontWeight={700}>Остатки по складам</Typography>{detail.stocks.map(s=><Typography key={s.warehouse}>{s.warehouse}: {s.quantity}</Typography>)}<Typography fontWeight={700}>Аналоги</Typography>{detail.analogs.map(a=><Typography key={a.code}>{a.code} {a.name}</Typography>)}</Stack>}</Box></Drawer>
  </ThemeProvider>;
}

createRoot(document.getElementById('root')!).render(
  <BrowserRouter basename="/vr/catalog/">
    <App />
  </BrowserRouter>,
);
