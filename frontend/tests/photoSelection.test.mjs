import assert from "node:assert/strict";
import test from "node:test";

import { togglePhotoSelection } from "../.test-dist/photoSelection.js";

test("выбор фотографий по умолчанию пуст", () => {
  assert.equal(new Set().size, 0);
});

test("отдельную фотографию можно выбрать и снять", () => {
  const selected = togglePhotoSelection(new Set(), "1:10");
  assert.deepEqual([...selected], ["1:10"]);
  assert.equal(togglePhotoSelection(selected, "1:10").size, 0);
});

test("фотографии разных товаров выбираются независимо", () => {
  const first = togglePhotoSelection(new Set(), "1:10");
  const second = togglePhotoSelection(first, "2:20");
  assert.deepEqual([...second], ["1:10", "2:20"]);
});
