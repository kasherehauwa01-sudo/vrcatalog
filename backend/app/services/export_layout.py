"""Disk-backed ordering for export layouts; never retain the catalog in RAM."""
from contextlib import contextmanager
import json
import re
import sqlite3
import tempfile
from pathlib import Path

from app.models.catalog import Product, ProductProperty
from app.services.catalog_folders import FOLDER_PATH_PROPERTIES, folder_path

PRICE_PAIRS = {
    'ЦенаОптовая': 'ЦенаПредыдущаяОптовая',
    'ЦенаКорпоративная': 'ЦенаПредыдущаяКорпоративная',
    'ЦенаРозничная': 'ЦенаПредыдущаяРозничная',
}
FORM_HEADERS = {'promo_price': 'Акция! Новая цена', 'old_price': 'Старая цена',
                'order_quantity': 'Заказ', 'order_total': 'Сумма заказа'}


def form_price(columns, options):
    if not (options.get('promotion') or options.get('order_form')):
        return None
    prices = [column[6:] for column in columns if column.startswith('price:')]
    if len(prices) != 1 or prices[0] not in PRICE_PAIRS:
        raise ValueError('Для формы акции или заказа выберите ровно один вид цены')
    return prices[0]


def form_columns(columns, options):
    result = list(columns)
    if options.get('promotion'):
        result = [column for column in result if not column.startswith('price:')]
        result.extend(['promo_price', 'old_price'])
    if options.get('order_form'):
        result.extend(['order_quantity', 'order_total'])
    return result


def archive_name(name, used):
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')[:120] or 'Без подкатегории'
    if stem.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        stem = '_' + stem
    stem = stem.encode('utf-8')[:180].decode('utf-8', errors='ignore')
    candidate, number = stem, 1
    while candidate.casefold() in used:
        number += 1
        candidate = f'{stem} ({number})'
    used.add(candidate.casefold())
    return candidate + '.xlsx'


class ExportPlan:
    def __init__(self, connection, options):
        self.connection = connection
        self.options = options

    def sections(self):
        return self.connection.execute('SELECT category, section, count(*) FROM items GROUP BY category, section ORDER BY category, section')

    def batches(self, section=None, size=500):
        where, args = ('WHERE category=? AND section=?', section) if section else ('', ())
        order = []
        if self.options.get('group_categories') or self.options.get('zip_categories'):
            order.extend(['category', 'section'])
        if self.options.get('group_folders'):
            order.append('folders')
        order.append('id')
        cursor = self.connection.execute(f'SELECT id, category, section, folders FROM items {where} ORDER BY {", ".join(order)}', args)
        while rows := cursor.fetchmany(size):
            yield [(row[0], row[1], row[2], json.loads(row[3])) for row in rows]


@contextmanager
def export_plan(db, filtered_ids, options, directory):
    with tempfile.TemporaryDirectory(dir=directory) as temp:
        connection = sqlite3.connect(str(Path(temp) / 'order.sqlite'))
        try:
            connection.execute('PRAGMA cache_size=-2048')
            connection.execute('PRAGMA temp_store=FILE')
            connection.execute('CREATE TABLE items (id INTEGER PRIMARY KEY, category TEXT, section TEXT, folders TEXT)')
            last_id = 0
            while True:
                rows = (db.query(Product.id, Product.name, Product.category1, Product.section)
                        .join(filtered_ids, filtered_ids.c.product_id == Product.id)
                        .filter(Product.id > last_id).order_by(Product.id).limit(500).all())
                if not rows:
                    break
                paths = {}
                if options.get('group_folders'):
                    names = {row.id: row.name for row in rows}
                    for pid, value in (db.query(ProductProperty.product_id, ProductProperty.value)
                                       .filter(ProductProperty.product_id.in_(names), ProductProperty.name.in_(FOLDER_PATH_PROPERTIES))
                                       .order_by(ProductProperty.id)):
                        if value and pid not in paths:
                            path = folder_path(value, names[pid])
                            if path:
                                paths[pid] = [part.strip() for part in path.split('|')]
                connection.executemany('INSERT INTO items VALUES (?, ?, ?, ?)', [
                    (row.id, (row.category1 or '').strip() or 'Без категории',
                     (row.section or '').strip() or 'Без подкатегории',
                     json.dumps(paths.get(row.id, ['Без папки']), ensure_ascii=False)) for row in rows])
                last_id = rows[-1].id
            connection.commit()
            yield ExportPlan(connection, options)
        finally:
            connection.close()
