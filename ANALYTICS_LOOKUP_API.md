# Analytics lookup for Sales Journal (schema_version 1)

`POST /api/integration/products/analytics/lookup` is a separate, read-only API for
refreshing Sales Journal's local product attributes. Historical reports are
expected to use current attributes. It does not implement history, scheduled
synchronization, a full catalog export, a change feed, or deletion notifications.
With the deployment prefix the URL is `/vr/catalog/api/integration/products/analytics/lookup`.

## Authorization and input

Use the same `Authorization: Bearer <token>` and `INTERNAL_API_TOKEN` as the
existing integration API. `X-Internal-Token` alone is not accepted here. Never
put the token into the URL, checked-in examples, or diagnostic output.

```json
{
  "items": [
    {"code": "001234"},
    {"article": "A-17"},
    {"product_id": 123},
    {"code": "missing-code", "article": "A-17"}
  ]
}
```

- `items` must contain 1–250 entries, including repeated entries.
- At least one nonempty identifier is required. Outer whitespace is removed;
  blank code/article strings are treated as absent.
- `product_id` is a strict positive integer within the current PostgreSQL Integer
  domain (1–2147483647). Strings, booleans and fractional numbers are rejected.
- `code` and `article` must be strings (maximum 128 and 255 characters after
  trimming). Numeric inputs are rejected, never converted to identifiers.
- Leading zeroes remain significant. No fuzzy matching or numeric conversion.
- Unknown request fields are rejected. There is no arbitrary `fields` selector.

## Matching and per-input result

1. If `product_id` is present, look up that ID only. A missing ID does **not**
   fall back to supplied code/article and attach the entry to a different product.
2. Otherwise, try code first, then article only when code has no match.
3. Code/article matching follows the existing integration expressions:
   Python `strip()/casefold()` for input, PostgreSQL `lower(trim(column))` for
   the stored identifier. No new transliteration or identifier aliases are added.
4. A nonunique article returns `ambiguous`. A collision between normalized codes
   also returns `ambiguous`, even though original code strings have a UNIQUE
   constraint. An ambiguous code does not fall back to article.
5. Output length and order equal input length and order. Duplicate inputs get
   separate results with their own zero-based `request_index`.

```json
{
  "schema_version": 1,
  "items": [
    {
      "request_index": 0,
      "status": "matched",
      "matched_by": "code",
      "product": {
        "product_id": 123,
        "code": "001234",
        "article": "A-17",
        "manufacturer": "Производитель",
        "brand": "Бренд",
        "category_id": 7,
        "category": "Посуда",
        "subcategory": "Тарелки",
        "legacy_category": "Тарелки",
        "material": "Фарфор",
        "horeca": false,
        "updated_at": "2026-10-10T08:00:00.123456Z"
      }
    },
    {"request_index": 1, "status": "ambiguous", "matched_by": null, "product": null},
    {"request_index": 2, "status": "not_found", "matched_by": null, "product": null}
  ]
}
```

The example values are illustrative. `matched_by` is `product_id`, `code`, or
`article` only for matched results; otherwise it and `product` are null.
`ambiguous` is not a deletion. `not_found` by code/article is not proof of deletion:
identifiers may have changed. The existing `batch-info` still selects the minimum
product ID for duplicate articles; this new endpoint deliberately reports them.

## Attributes and compatibility

| Field | Type | Source and meaning |
| --- | --- | --- |
| `product_id` | integer | `products.id`; stable for the lifetime of that row |
| `code` | string | Stored code; leading zeroes preserved |
| `article` | string/null | Stored article; not a unique key |
| `manufacturer` | string/null | Trimmed `products.manufacturer`, then legacy fallback |
| `brand` | string/null | Trimmed `products.brand`, then legacy fallback |
| `category_id` | integer/null | Actual FK `products.category_id`, not the string ID in the old search API |
| `category` | string/null | Trimmed parent name `products.category1` |
| `subcategory` | string/null | Trimmed XML section `products.section` |
| `legacy_category` | string/null | Trimmed `products.section`, then the fallback used by `batch-info.category` |
| `material` | string/null | Trimmed `products.material`, then legacy fallback |
| `horeca` | boolean | True iff a property name AND its value, after trim/casefold, equal `horeca` |
| `updated_at` | UTC ISO 8601 string | Stored `products.updated_at`, preserving microseconds |

Fallback aliases are exactly those used in `batch-info`:

| Field | Case-insensitive, trimmed property names |
| --- | --- |
| `manufacturer` | `производитель`, `manufacturer` |
| `brand` | `бренд`, `brand` |
| `legacy_category` | `категория`, `category` |
| `material` | `материал`, `material` |

Nonempty main columns win. Empty property values do not supply a fallback.
When several fallback values exist, the choice follows `batch-info`: sort by
trimmed name/value using Python casefold, preserving its SQL name/value/id tie
order. Exact duplicate pairs do not affect the chosen value. Property whitespace
includes tabs, newlines and Unicode whitespace, matching Python `str.strip()`.

No new importer aliases are introduced: for example, `PROP_BREND` with an
unrecognized property name and `Материал основной` are not additional fallback
rules. Normally the importer already copies such special properties into their
main columns. HoReCa does not mean a truthy string: `true`, `1`, and `Да` are not
new positive classifications. Its boolean semantics match `batch-info.horeca`
and Sales Journal's existing HoReCa consumer. `material` remains a nullable
string, as expected by Sales Journal's material grouping.

The parent category may be null while the XML section remains present.
A `Category` property supplies only `legacy_category`, never a fabricated parent.
The raw `Subcategory` property is not the source of the hierarchy field.
**Existing API category semantics remain unchanged.**

## Bounded SQL and memory

At most three SELECT statements per valid request:

1. Identify unique matches using the primary key and existing normalized
   code/article indexes. Per-key `min(id)`/`max(id)` detect ambiguity without
   loading all duplicate candidates. There is no global catalog count or sort.
2. Select only the ten necessary columns for at most 250 uniquely matched products.
   No full Product entities or eager/lazy ORM relationships are loaded.
3. Select only matching HoReCa rows and fallback aliases for products whose
   corresponding main column is empty. No per-product queries. Properties are
   read in chunks of 250 rows; only the best fallback per product/field is retained.
   Sorting is scoped to these selected rows to preserve legacy tie behavior.

If there are no unique matches, only statement 1 runs. Duplicate inputs reuse the
same projection. No ProductImage, Stock, Price, other property names, writes,
service-log INSERTs, caches, background tasks or external calls are involved.
A service logger writes a single INFO line. The new code has no runtime activity
until the endpoint is called. No schema changes, new indexes or dependencies.

Page size bounds the number of products, not the number/length of stored alias
values: existing `product_properties.value` is Text. Streaming avoids accumulating
all selected rows; values are not silently truncated, to preserve the old API.
Pathological duplicate values can still cost database work. No production speed
or memory benchmark is claimed.

## Errors and diagnostics

| HTTP status | Meaning |
| --- | --- |
| 200 | Per-item `matched`, `not_found`, or `ambiguous` results |
| 401 | Missing Authorization header |
| 403 | Invalid/malformed Bearer token or integration token not configured |
| 422 | Invalid body, identifiers, empty batch or more than 250 inputs |
| 500 | Internal failure; generic safe message, no SQL/traceback |

Error examples:

```json
{"detail": "Требуется Bearer token"}
```

```json
{"detail": "Недостаточно прав для доступа"}
```

```json
{"detail": "Не удалось получить характеристики товаров"}
```

422 uses FastAPI's standard validation `detail` list; clients should inspect
its field locations rather than depend on localized wording. As with existing
FastAPI endpoints, body validation can run before the handler's authorization
check; malformed bodies may therefore receive 422 instead of 401.

Successful authorized processing and internal errors emit one line at INFO:

```text
analytics_lookup_perf requested=3 matched=1 not_found=1 ambiguous=1 total_ms=... products_sql_ms=... properties_sql_ms=... properties_rows=... status=ok
```

The line contains only numeric counters, timings and a fixed status. Counts refer
to input results (so duplicates count separately); `properties_rows` counts fetched
rows before choosing fallback values. `products_sql_ms` covers the two product
SELECTs, `properties_sql_ms` covers execution/fetch of the selective property
query, and `total_ms` includes matching/projection but excludes HTTP serialization.
On error, `status=error`; counters/timings for unfinished work may be zero/partial.
No exception text, identifiers, attributes, request bodies or tokens are logged.
The existing backend INFO logging configuration makes the line visible in stderr.

## Freshness, retries and later synchronization

This endpoint returns current data, not a historical snapshot. Changes between
its SELECTs are possible under the existing database isolation level; there is
no cross-request snapshot. A product deleted before projection returns not_found.
An ambiguous result must never be treated as deletion. Preserve local data on
500, transport timeout, or an interrupted request.

`updated_at` is **not** a complete synchronization cursor. Category hierarchy
refresh can preserve that timestamp, deletions have no tombstones, and long
transactions can commit after their per-product timestamps. Do not implement
incremental synchronization using only this field. Current attributes, including
nulls after removal, should replace the previous successfully matched projection.

Repeating a lookup is read-only and safe, but its values can change between calls.
A future Sales Journal sync should commit each successful batch locally, use
bounded retries with backoff for temporary errors, and stop/review 401/403/422.
No scheduler, retry worker or Sales Journal change is part of this PR.

## Local verification

The new tests use SQLite in memory with the actual FastAPI router and isolated
model fixtures, without importing the production app startup. Unicode lower is
registered for SQLite to emulate PostgreSQL's Cyrillic case conversion. They
verify 250 unique inputs, duplicates, ambiguity, fallback semantics against the
old batch endpoint, authorization, safe errors, SQL count/projection, selective
property rows and multi-chunk property reads.

```bash
DATABASE_URL=sqlite:// PYTHONPATH=backend python -m unittest discover -s backend/tests -p test_analytics_lookup.py -v
```

Two missing imports (`AdminLoginIn`, `AdminSession`) in existing `routes.py` are
restored so the real router can import. Existing handler/service bodies are not
changed. The new API's tests also exercise the unchanged old endpoints.

## Subsequent operator deployment (not performed by Codex)

1. Review and merge the PR through the normal process. Record the current backend
   revision/image for rollback; verify the server working tree is clean and its
   configured database is the intended one. This feature needs no migration.
2. In an isolated staging environment, build the reviewed revision and run the
   tests above plus existing integration API regression tests. No load test or
   full-catalog request is needed.
3. Schedule the normal backend update in `/var/www/html/vr/vrcatalog`, deploying
   only the reviewed backend revision. Do not restart PostgreSQL or change its
   settings, Docker configuration, concurrency, or memory limits for this feature.
4. Important: the repository's backend Docker CMD runs `alembic upgrade head`
   automatically. Before any production container restart, the operator must
   verify there are no unrelated pending migrations. Do not blindly run the
   all-services update script or interpret this PR as approval for migrations.
5. After deployment, use the existing secret-management mechanism to send a
   single authorized lookup for an agreed test product. Check the small response,
   the INFO diagnostic line, and one existing integration endpoint. Never echo
   the Bearer token or enable request-header/body debug logging.
6. Do not enable scheduled Sales Journal synchronization yet. If rollback is
   needed, restore the recorded backend image/revision; this change has no data
   migration to reverse.

No VPS deployment, container restart, production SQL, XML import, or migration
was performed as part of implementation.
