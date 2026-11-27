import assert from 'node:assert/strict';
import { test } from 'node:test';
import { createServer } from 'vite';

const apiPath = '/vr/catalog/api';


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


const password = 'Ab9'.repeat(10) + 'Z1';
const operation_id = 'a'.repeat(32);
test('package response exposes only transient blob and generated password', async (t) => {
  const { api, calls } = await loadApi(t, (call) => call.url.pathname.endsWith('/admin/session')
    ? Response.json({authenticated: true, csrf_token: 'csrf'})
    : Response.json({device: {id: 1, name: 'Test'}, password, filename: 'device-abc.p12', pkcs12_base64: 'AQID'}));
  const result = await api.downloadDevicePackage('issue-package', {operation_id, name: 'Test', owner: 'Owner'});
  assert.equal(result.password, password);
  assert.deepEqual([...new Uint8Array(await result.file.arrayBuffer())], [1, 2, 3]);
  assert.equal(result.filename, 'device-abc.p12');
  const post = calls.find(c => c.method === 'POST');
  assert.equal(post.cache, 'no-store');
  assert.equal(post.headers.get('X-CSRF-Token'), 'csrf');
  assert.equal(JSON.parse(post.body).operation_id, operation_id);
  assert.equal(post.body.includes(password), false);
});
for (const failure of ['network', 'malformed']) {
  test(`package ${failure} failure never retries automatically`, async (t) => {
    const {api, calls} = await loadApi(t, (call) => {
      if (call.url.pathname.endsWith('/admin/session')) return Response.json({authenticated: true, csrf_token: 'csrf'});
      if (failure === 'network') throw new TypeError('Failed to fetch');
      return Response.json({password, pkcs12_base64: 'bad'});
    });
    await assert.rejects(api.downloadDevicePackage('issue-package', {operation_id}));
    assert.equal(calls.filter(c => c.method === 'POST').length, 1);
  });
}
