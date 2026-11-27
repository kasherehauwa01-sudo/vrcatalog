import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';

const apiPath = '/vr/catalog/api';
const codes = Array.from({ length: 300 }, (_, index) => `CODE-${index}`).join(' ');

async function loadApi(t, respond) {
  const server = await createServer({
    configFile: false,
    base: '/vr/catalog/',
    server: { middlewareMode: true, watch: null, hmr: false },
  });
  const previousWindow = globalThis.window;
  globalThis.window = new EventTarget();
  const calls = [];
  t.mock.method(globalThis, 'fetch', async (url, init = {}) => {
    const call = {
      url: new URL(url, 'http://localhost'),
      method: init.method ?? 'GET',
      headers: new Headers(init.headers),
      body: init.body,
      credentials: init.credentials ?? 'same-origin',
      cache: init.cache,
    };
    calls.push(call);
    return respond(call);
  });
  t.after(async () => {
    if (previousWindow === undefined) delete globalThis.window;
    else globalThis.window = previousWindow;
    await server.close();
  });
  // Each case starts with a fresh module instance, as after a browser reload.
  const { api } = await server.ssrLoadModule('/src/api/client.ts');
  return { api, calls };
}

for (const code of ['00123', codes]) {
  test(`public export does not request CSRF with ${code === codes ? '300 codes' : 'one code'}`, async (t) => {
    const { api, calls } = await loadApi(t, (call) => {
      if (call.url.pathname.endsWith('/admin/session')) {
        assert.equal(call.credentials, 'same-origin');
        assert.equal(call.cache, 'no-store');
        return Response.json({ authenticated: true, csrf_token: 'restored-token' });
      }
      return Response.json({ job_id: 'job', status: 'processing' });
    });

    const params = new URLSearchParams({ code, brand: 'Brand' });
    assert.deepEqual(await api.startExcelExport(params, []), { job_id: 'job', status: 'processing' });
    assert.deepEqual(calls.map(({ method, url }) => [method, url.pathname]), [
      ['POST', `${apiPath}/exports/xlsx`],
    ]);
    assert.equal(calls[0].headers.has('X-CSRF-Token'), false);
    const post = calls[0];
    assert.equal(post.headers.get('X-CSRF-Token'), null);
    assert.equal(post.url.searchParams.get('brand'), 'Brand');
    if (code === codes) {
      assert.equal(post.url.searchParams.has('code'), false);
      assert.equal(post.headers.get('Content-Type'), 'application/json');
      assert.deepEqual(JSON.parse(post.body), { code });
    } else {
      assert.equal(post.url.searchParams.get('code'), code);
      assert.equal(post.body, undefined);
    }
  });
}

test('export works without an administrator session', async (t) => {
  const { api, calls } = await loadApi(t, (call) => {
    assert.ok(!call.url.pathname.endsWith('/admin/session'));
    return Response.json({ job_id: 'public-job', status: 'processing' });
  });
  assert.equal((await api.startExcelExport(new URLSearchParams())).job_id, 'public-job');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].headers.has('X-CSRF-Token'), false);
});

test('ordinary GETs and public long-code search do not restore or send CSRF', async (t) => {
  const { api, calls } = await loadApi(t, (call) => {
    if (call.url.pathname.endsWith('/chunk')) {
      return new Response('data', { headers: { 'X-Next-Offset': '4', 'X-File-Size': '4' } });
    }
    return Response.json({});
  });

  await api.meta();
  await api.searchProducts(new URLSearchParams({ code: codes }));
  await api.excelExportStatus('job');
  const chunk = await api.excelExportChunk('job', 0);
  assert.equal(chunk.content.byteLength, 4);
  assert.equal(chunk.nextOffset, 4);
  assert.equal(chunk.size, 4);
  assert.deepEqual(calls.map(({ method, url }) => [method, url.pathname]), [
    ['GET', `${apiPath}/meta`],
    ['POST', `${apiPath}/products/search`],
    ['GET', `${apiPath}/exports/xlsx/job`],
    ['GET', `${apiPath}/exports/xlsx/job/chunk`],
  ]);
  assert.ok(calls.every(({ headers }) => !headers.has('X-CSRF-Token')));
  assert.deepEqual(JSON.parse(calls[1].body), { code: codes });
});

test('protected operations share recovery and do not race with session rotation', async (t) => {
  let rotations = 0;
  let activeToken;
  const { api, calls } = await loadApi(t, async (call) => {
    if (call.url.pathname.endsWith('/admin/session')) {
      activeToken = `rotated-${++rotations}`;
      return Response.json({ authenticated: true, csrf_token: activeToken });
    }
    await new Promise((resolve) => setImmediate(resolve));
    assert.equal(call.headers.get('X-CSRF-Token'), activeToken);
    if (call.url.pathname.endsWith('/download')) return new Response('archive');
    return Response.json({ deleted: 1 });
  });

  const [deleted, archive] = await Promise.all([
    api.deleteProducts([7]),
    api.downloadReportPhotos([{ product_id: 7, image_id: 8 }]),
    api.adminSession(),
  ]);
  assert.deepEqual(deleted, { deleted: 1 });
  assert.equal(await archive.text(), 'archive');
  await api.adminLogout();
  assert.deepEqual(calls.map(({ method, url }) => [method, url.pathname]), [
    ['GET', `${apiPath}/admin/session`],
    ['DELETE', `${apiPath}/products`],
    ['POST', `${apiPath}/reports/photos/download`],
    ['GET', `${apiPath}/admin/session`],
    ['POST', `${apiPath}/admin/logout`],
  ]);
});

test('checked product IDs take precedence over catalog filters in Excel export', async (t) => {
  const { api, calls } = await loadApi(t, (call) => {
    if (call.url.pathname.endsWith('/admin/session')) {
      return Response.json({ authenticated: true, csrf_token: 'restored-token' });
    }
    return Response.json({ job_id: 'job', status: 'processing' });
  });
  const params = new URLSearchParams({
    code: codes, brand: 'Brand', page: '2', promotion: 'true', promotion_type: 'Надо продать',
    adjustment: 'true', adjustment_percent: '-10', markup_percent: '15',
    stock_warehouse: 'AVI', stock_comparison: 'less', stock_limit: '5',
  });
  params.append('column', 'code');
  params.append('column', 'name');

  await api.startExcelExport(params, [12, 35]);

  assert.equal(calls.length, 1);
  const post = calls[0];
  assert.equal(post.url.pathname, `${apiPath}/exports/xlsx`);
  assert.deepEqual([...post.url.searchParams], [
    ['promotion', 'true'], ['promotion_type', 'Надо продать'], ['adjustment', 'true'], ['adjustment_percent', '-10'],
    ['markup_percent', '15'], ['stock_warehouse', 'AVI'], ['stock_comparison', 'less'], ['stock_limit', '5'],
    ['column', 'code'], ['column', 'name'],
  ]);
  assert.equal(post.method, 'POST');
  assert.equal(post.headers.get('X-CSRF-Token'), null);
  assert.equal(post.headers.get('Content-Type'), 'application/json');
  assert.deepEqual(JSON.parse(post.body), { product_ids: [12, 35] });
});
