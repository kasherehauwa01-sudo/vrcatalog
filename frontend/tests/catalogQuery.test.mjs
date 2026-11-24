import test from 'node:test';
import assert from 'node:assert/strict';
import { catalogUrl, readCatalogParams, codeRequest, codeList } from '../.test-dist/catalogQuery.js';

test('300 codes survive reload and stay out of HTTP URLs', () => {
  const code = Array.from({length: 300}, (_, i) => `CODE-${String(i).padStart(6, '0')}`).join(' ');
  const params = new URLSearchParams({code, page: '2', inStockOnly: 'false'});
  params.append('folder', 'НЕНУЖНОЕ');
  params.append('folder', 'БАНЯ');
  const url = new URL(catalogUrl('/vr/catalog/', params), 'http://localhost');
  assert.equal(url.searchParams.has('code'), false);
  const restored = readCatalogParams(url);
  assert.equal(restored.get('code'), code);
  assert.deepEqual(restored.getAll('folder'), ['НЕНУЖНОЕ', 'БАНЯ']);
  const request = codeRequest(restored);
  assert.equal(request.init.method, 'POST');
  assert.equal(JSON.parse(request.init.body).code, code);
  assert.equal(request.query.has('code'), false);
  assert.equal(request.query.get('page'), '2');
  assert.equal(params.get('code'), code);
});

test('short searches keep GET compatibility and resetting clears long list', () => {
  const params = new URLSearchParams({code: '001 002'});
  assert.equal(codeRequest(params).init, undefined);
  assert.equal(catalogUrl('/catalog/', params), '/catalog/?code=001+002');
  assert.equal(catalogUrl('/catalog/', new URLSearchParams()), '/catalog/');
  assert.deepEqual(codeList('001, 002\n003\t001'), ['001', '002', '003', '001']);
});
