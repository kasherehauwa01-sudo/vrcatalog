"""Disk-backed ordering for export layouts; never retain the catalog in RAM."""
from contextlib import contextmanager
import math
from decimal import Decimal, ROUND_HALF_UP
import json
import re
import sqlite3
import tempfile
from pathlib import Path

from sqlalchemy import Numeric, and_, cast, func, or_, select
from app.importer.xml_importer import PRICE_NAMES
from app.models.catalog import Price, Product, ProductProperty, ProductTypeSetting, Stock
from app.services.catalog import DEFAULT_PRODUCT_TYPE_NAMES
from app.services.catalog_folders import FOLDER_PATH_PROPERTIES, folder_path

PRICE_PAIRS = {
    'ЦенаОптовая': 'ЦенаПредыдущаяОптовая',
    'ЦенаКорпоративная': 'ЦенаПредыдущаяКорпоративная',
    'ЦенаРозничная': 'ЦенаПредыдущаяРозничная',
}
PURCHASE_PRICE_TYPE = "ЦенаЗакупочная"
EXPORT_PRICE_ALIASES = {**PRICE_NAMES, PURCHASE_PRICE_TYPE: "Закупочная"}

FORM_HEADERS = {'adjusted_price': 'Ваша цена', 'promo_price': 'Акция! Новая цена', 'old_price': 'Старая цена',
                'order_quantity': 'Заказ', 'order_total': 'Сумма заказа'}


def form_price(columns, options):
    if options.get('promotion') and options.get('promotion_type') not in ('Акция месяца', 'Надо продать'):
        raise ValueError('Выберите вид товара: Акция месяца или Надо продать')
    if options.get('adjustment') and (options.get('adjustment_percent') is None or not math.isfinite(options['adjustment_percent'])):
        raise ValueError('Введите процент скидки / наценки')
    if not (options.get('promotion') or options.get('order_form') or options.get('adjustment') or options.get('markup_percent') is not None):
        return None
    prices = [column[6:] for column in columns if column.startswith('price:')]
    if len(prices) != 1 or prices[0] not in PRICE_PAIRS:
        raise ValueError('Выберите ровно один вид цены')
    return prices[0]


def form_columns(columns, options):
    result = list(columns)
    if options.get('promotion'):
        result = [column for column in result if not column.startswith('price:')]
        result.extend(['promo_price', 'old_price'])
    if options.get('adjustment'):
        result.append('adjusted_price')
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
                            path = folder_path(value, names[pid], uppercase_only=True)
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


def promotion_product_ids(db, filtered_ids, promotion_type):
    """Intersect the selection with the same product-type representation as the catalog."""
    names = dict(DEFAULT_PRODUCT_TYPE_NAMES)
    names.update({row.code: row.name for row in db.query(ProductTypeSetting).all()})
    codes = [code for code, name in names.items() if name.strip() == promotion_type]
    values = [promotion_type, *codes]
    fallback = Product.properties.any(and_(
        ProductProperty.name.in_(['Вид товара', 'ВидТовара']),
        func.trim(ProductProperty.value).in_(values),
    ))
    return (db.query(Product.id.label('product_id'))
            .join(filtered_ids, filtered_ids.c.product_id == Product.id)
            .filter(or_(func.trim(Product.product_type).in_(values),
                        and_(or_(Product.product_type.is_(None), Product.product_type == ''), fallback)))
            .subquery())


def restrict_export_product_ids(db, filtered_ids, columns, options):
    markup_percent = options.get("markup_percent")
    warehouse = options.get("stock_warehouse")
    if markup_percent is None and warehouse is None:
        return filtered_ids

    query = db.query(Product.id.label("product_id")).join(filtered_ids, filtered_ids.c.product_id == Product.id)
    if markup_percent is not None:
        sale_type = form_price(columns, options)

        def price_value(price_type):
            return (select(Price.price_value)
                    .where(Price.product_id == Product.id, Price.price_type.in_((price_type, EXPORT_PRICE_ALIASES[price_type])))
                    .order_by((Price.price_type == price_type).desc(), Price.id.desc())
                    .limit(1).scalar_subquery())

        purchase = price_value(PURCHASE_PRICE_TYPE)
        sale = price_value(sale_type)
        # Stabilize strict equality at the threshold for prices stored as floats.
        difference = (sale - purchase) * 100 - purchase * markup_percent
        query = query.filter(purchase > 0, func.round(cast(difference, Numeric), 8) > 0)

    if warehouse is not None:
        balance = (select(func.sum(Stock.quantity))
                   .where(Stock.product_id == Product.id, Stock.warehouse == warehouse)
                   .scalar_subquery())
        limit = options["stock_limit"]
        query = query.filter(balance >= 1, balance <= limit if options["stock_comparison"] == "less" else balance > limit)
    return query.subquery()


def adjusted_price(value, percent):
    if value is None:
        return None
    return float((Decimal(str(value)) * (1 + Decimal(str(percent)) / 100)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def export_prices(prices):
    """Prefer explicit XML names, then the latest row with each label."""
    result = {price.price_type: price.price_value for price in sorted(prices, key=lambda item: item.id or 0)}
    for xml_name, label in EXPORT_PRICE_ALIASES.items():
        if xml_name in result:
            result[label] = result[xml_name]
        elif label in result:
            result[xml_name] = result[label]
    return result



def export_stocks(stocks):
    totals = {}
    for stock in stocks:
        totals[stock.warehouse] = totals.get(stock.warehouse, 0) + stock.quantity
    return totals
