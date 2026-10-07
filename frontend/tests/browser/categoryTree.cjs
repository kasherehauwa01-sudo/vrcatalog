const { chromium } = require('playwright');
const http = require('http');
const fs = require('fs');
const path = require('path');
const assert = require('assert');
const distDir = process.env.DIST_DIR || path.resolve(__dirname, '../../dist');
const outputDir = process.env.SCREENSHOT_DIR || '/tmp/vr-category-screenshots';
fs.mkdirSync(outputDir, { recursive: true });
const tree = Array.from({length:40}, (_,i)=>({id:i+1,name:i===0?'Интерьер':`Категория ${i}`,subcategories:Array.from({length:i<20?16:15},(_,j)=>({name:i===0&&j===0?'Вазы для цветов':i===0&&j===1?'Очень длинное название раздела '.repeat(7):`Раздел ${i} ${j}`,product_count:1}))}));
tree.push({id:null,name:'Без категории',subcategories:[{name:'Новый раздел',product_count:3}]});
const server=http.createServer((req,res)=>{
 const url=new URL(req.url,'http://localhost');
 if(url.pathname.includes('/api/')) {
  res.setHeader('Content-Type','application/json');
  const result=url.pathname.endsWith('/filters')?{filters:{section:tree.flatMap(n=>n.subcategories.map(s=>s.name))},section_tree:tree}:url.pathname.endsWith('/meta')?{product_count:623,last_import:null}:url.pathname.endsWith('/products/search')?{items:[],pagination:{page:1,pageSize:100,totalItems:0,totalPages:0}}:[];
  return res.end(JSON.stringify(result));
 }
 let relative=url.pathname.replace(/^\/vr\/catalog\/?/,'')||'index.html';
 let file=path.join(distDir,relative);
 if(!fs.existsSync(file)) file=path.join(distDir,'index.html');
 res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.svg')?'image/svg+xml':'text/html');
 res.end(fs.readFileSync(file));
});
(async()=>{
 await new Promise(r=>server.listen(8090,'127.0.0.1',r));
 const browser=await chromium.launch({executablePath:'/usr/bin/chromium',args:['--no-sandbox']});
 for(const mobile of [false,true]) {
  const context=await browser.newContext({viewport:mobile?{width:375,height:812}:{width:1440,height:1000},hasTouch:mobile,isMobile:mobile,serviceWorkers:'block'});
  const page=await context.newPage();
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('http://127.0.0.1:8090/vr/catalog/');
  const open=async()=>{const input=page.getByPlaceholder('Поиск по названию, коду, артикулу, бренду, штрихкодам и тегам'); await (mobile?input.tap():input.click());};
  await open();
  await page.getByRole('button',{name:/^Раздел/}).click();
  const search=page.getByLabel('Найти раздел...');
  await search.fill('вазы');
  await page.getByRole('checkbox',{name:'Интерьер',exact:true}).waitFor();
  await page.getByRole('checkbox',{name:'Вазы для цветов',exact:true}).waitFor();
  await search.fill('нет такого раздела');
  await page.getByText('Ничего не найдено',{exact:true}).waitFor();
  await search.fill('');
  assert((await page.getByRole('checkbox').count())<60,'children should start collapsed');
  await page.getByRole('button',{name:'Развернуть: Интерьер',exact:true}).click();
  await page.getByRole('checkbox',{name:'Вазы для цветов',exact:true}).check();
  await page.getByRole('checkbox',{name:'Интерьер · 1',exact:true}).check();
  const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth);
  assert(!overflow,'horizontal page overflow');
  await page.screenshot({path:path.join(outputDir, `${mobile?'mobile':'desktop'}.png`),fullPage:true});
  await page.getByRole('button',{name:'Применить',exact:true}).click();
  await page.waitForURL(/category=1/);
  assert(!new URL(page.url()).searchParams.has('section'),'whole category sends only ID');
  await page.getByText('Категория1: Интерьер',{exact:true}).waitFor();
  await open();
  if(!await search.isVisible()) await page.getByRole('button',{name:/^Раздел/}).click();
  await search.fill('Новый раздел');
  await page.getByRole('checkbox',{name:'Без категории',exact:true}).waitFor();
  await page.getByRole('checkbox',{name:'Новый раздел',exact:true}).check();
  await page.getByRole('button',{name:'Применить',exact:true}).click();
  await page.waitForURL(/section=/);
  assert.equal(new URL(page.url()).searchParams.get('section'),'Новый раздел');
  assert.deepEqual(errors,[]);
  console.log(`${mobile?'mobile touch 375px':'desktop 1440px'}: search, 620 sections, collapse, long names, no overflow, selection, URL, uncategorized OK`);
  await context.close();
 }
 await browser.close();server.close();
})().catch(e=>{console.error(e);process.exit(1)});
