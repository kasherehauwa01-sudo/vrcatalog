import test from 'node:test';
import assert from 'node:assert/strict';
import { searchCategoryTree, toggleCategory, toggleSection } from '../.test-dist/categoryTree.js';
const tree = [
  { id: 1, name: 'Интерьер', subcategories: [{ name: 'Вазы для цветов', product_count: 2 }, { name: 'Ёлки', product_count: 1 }] },
  { id: 2, name: 'Посуда', subcategories: [{ name: 'Кастрюли', product_count: 1 }] },
  { id: null, name: 'Без категории', subcategories: [{ name: 'Новое', product_count: 1 }] },
];
test('category search keeps all children', () => assert.deepEqual(searchCategoryTree(tree, ' ИНТЕРЬЕР '), [tree[0]]));
test('section search keeps parent and matching child', () => assert.deepEqual(searchCategoryTree(tree, 'вазы'), [{ ...tree[0], subcategories: [tree[0].subcategories[0]] }]));
test('ё/е and no results', () => { assert.equal(searchCategoryTree(tree, 'елки').length, 1); assert.deepEqual(searchCategoryTree(tree, 'missing'), []); });
test('category selection sends one ID and removes redundant children', () => assert.deepEqual(toggleCategory(tree, tree[0], ['2'], ['Ёлки', 'Новое']), { category: ['2', '1'], section: ['Новое'] }));
test('uncheck child of whole category preserves other children', () => assert.deepEqual(toggleSection(tree[0], 'Ёлки', ['1', '2'], ['Новое']), { category: ['2'], section: ['Новое', 'Вазы для цветов'] }));
test('independent sections and uncategorized selection', () => { assert.deepEqual(toggleSection(tree[1], 'Кастрюли', [], ['Ёлки']), { category: [], section: ['Ёлки', 'Кастрюли'] }); assert.deepEqual(toggleCategory(tree, tree[2], [], []), { category: ['uncategorized'], section: [] }); });
test('large tree is not truncated', () => { const large = [{ ...tree[0], subcategories: Array.from({ length: 620 }, (_, i) => ({ name: `Раздел ${i}`, product_count: 1 })) }]; assert.equal(searchCategoryTree(large, '')[0].subcategories.length, 620); assert.equal(searchCategoryTree(large, 'Раздел 619')[0].subcategories.length, 1); });
