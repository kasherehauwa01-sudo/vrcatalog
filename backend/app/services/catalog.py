from math import ceil
from datetime import datetime, timedelta
import csv
import re

from sqlalchemy import String, and_, case, cast, func, literal, or_, select, union_all
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import Barcode, ImportRun, Price, Product, ProductImage, ProductProperty, Stock, WarehouseSetting, ProductTypeSetting

FILTER_FIELDS = ["section", "manufacturer", "brand", "manager", "country", "material", "color"]
WAREHOUSE_ORDER = [
    "Авиаторов", "Козловская", "Цитрус", "Привоз", "Бахтурова", "Ахтубинск",
    "СтройГрад", "Европа", "Парк Хаус", "ЦУМ", "Простор", "Универ",
]
EXCLUDED_PROPERTY_FILTERS = {
    "ID",
    "АкцияДоллар",
    "Артикул",
    "ВесНетто",
    "Код",
    "МинимальнаяНаценка",
    "Описание",
    "Сертификат",
    "Спецпредложение",
    "Тег",
    "Шарики",
    "Вид товара",
    "ВидТовара",
}
SORT_FIELDS = {
    "updated_at": Product.updated_at,
    "id": Product.id,
    "name": Product.name,
    "article": Product.article,
    "code": Product.code,
    "quantity": Product.quantity,
}
INTEGRATION_FILTER_LABELS = {
    "section": "Раздел",
    "manufacturer": "Производитель",
    "brand": "Бренд",
    "manager": "Менеджер",
    "country": "Страна",
    "material": "Материал",
    "color": "Цвет",
}
INTEGRATION_SORT_FIELDS = {
    "id": Product.id,
    "code": Product.code,
    "article": Product.article,
    "name": Product.name,
}
NEW_PRODUCT_PERIOD = timedelta(days=7)
NEW_PRODUCT_TYPE_FILTER = "Новинка"
EXCLUDED_YYY_SECTION = "яяявывод/разукомплектация НЕ ВЫГРУЖАТЬ НА САЙТ"
DEFAULT_PRODUCT_TYPE_NAMES = {
    "1": "Обычный",
    "2": "Ограниченная скидка",
    "3": "Надо продать",
    "4": "Куплен по акции",
    "5": "Прочие акции",
    "6": "Дисконт",
    "7": "Товар с деффектом",
    "8": "Последний экземпляр",
    "9": "Сетевой",
    "10": "Акция месяца",
    "11": "Разукомплектация",
    "12": "Минимальная наценка",
    "13": "Акция розница",
    "14": "Первая цена",
    "15": "9-19",
}


def new_product_cutoff() -> datetime:
    """Возвращает границу семидневного периода новинки в UTC."""
    return datetime.utcnow() - NEW_PRODUCT_PERIOD


def _values(value):
    if not value:
        return []
    # Значения фильтров передаются как CSV, чтобы запятые внутри одного значения
    # (например «Скалки, ступки, мялки») не превращались в несколько условий.
    return [item.strip() for item in next(csv.reader([str(value)]), []) if item.strip()]


def _search_values(value) -> list[str]:
    """Разделяет коды и артикулы по запятым либо любым пробельным символам."""
    return [item for item in re.split(r"[,\s]+", str(value or "").strip()) if item]


def catalog_product_query(db: Session, params, eager_load: bool = True):
    """Build the validated catalog query; all values remain SQLAlchemy bind parameters."""
    q = db.query(Product)
    if eager_load:
        q = q.options(
            selectinload(Product.prices),
            selectinload(Product.stocks),
            selectinload(Product.properties),
            selectinload(Product.images),
        )
    search = str(params.get("search") or "").strip()
    if search:
        pattern = f"%{search}%"
        search_conditions = [cast(Product.id, String).ilike(pattern), Product.search_text.ilike(pattern)]
        q = q.filter(or_(*search_conditions))

    if params.get("id") is not None:
        q = q.filter(Product.id == params["id"])
    if name := str(params.get("name") or "").strip():
        q = q.filter(Product.name.ilike(f"%{name}%"))
    code_values = _search_values(params.get("code"))
    if code_values:
        q = q.filter(or_(*(Product.code.ilike(f"%{code}%") for code in code_values)))
    article_values = _search_values(params.get("article"))
    if article_values:
        q = q.filter(or_(*(Product.article.ilike(f"%{article}%") for article in article_values)))
    barcode_values = _values(params.get("barcode"))
    if barcode_values:
        q = q.filter(Product.barcodes.any(Barcode.value.in_(barcode_values)))

    for field in FILTER_FIELDS:
        values = _values(params.get(field))
        if values:
            q = q.filter(getattr(Product, field).in_(values))

    if params.get("exclude_yyy"):
        q = q.filter(or_(Product.section.is_(None), Product.section != EXCLUDED_YYY_SECTION))

    type_values = _values(params.get("product_type"))
    if type_values:
        regular_type_values = [value for value in type_values if value != NEW_PRODUCT_TYPE_FILTER]
        configured_codes = [
            code
            for code, in db.query(ProductTypeSetting.code)
            .filter(ProductTypeSetting.name.in_(regular_type_values))
            .all()
        ]
        type_conditions = []
        if regular_type_values or configured_codes:
            type_conditions.append(Product.product_type.in_([*regular_type_values, *configured_codes]))
        if NEW_PRODUCT_TYPE_FILTER in type_values:
            # Значение «Новинка» является виртуальным видом товара:
            # оно определяется датой первой загрузки, а не XML-характеристикой.
            type_conditions.append(Product.created_at >= new_product_cutoff())
        q = q.filter(or_(*type_conditions))

    availability = params.get("availability")
    if availability == "in_stock":
        q = q.filter(Product.quantity > 0)
    elif availability == "out_of_stock":
        q = q.filter(Product.quantity <= 0)
    if params.get("in_stock_only"):
        q = q.filter(Product.stocks.any(Stock.quantity > 0))
    if params.get("only_new"):
        q = q.filter(Product.created_at >= new_product_cutoff())

    if params.get("quantity_from") is not None:
        q = q.filter(Product.quantity >= params["quantity_from"])
    if params.get("quantity_to") is not None:
        q = q.filter(Product.quantity <= params["quantity_to"])

    price_conditions = []
    if params.get("price_from") is not None:
        price_conditions.append(Price.price_value >= params["price_from"])
    if params.get("price_to") is not None:
        price_conditions.append(Price.price_value <= params["price_to"])
    if price_conditions:
        q = q.filter(Product.prices.any(and_(*price_conditions)))

    warehouse_values = _values(params.get("warehouse"))
    if warehouse_values:
        configured_codes = [
            code
            for code, in db.query(WarehouseSetting.code)
            .filter(WarehouseSetting.name.in_(warehouse_values))
            .all()
        ]
        q = q.filter(
            Product.stocks.any(
                and_(
                    Stock.warehouse.in_([*warehouse_values, *configured_codes]),
                    Stock.quantity > 0,
                )
            )
        )

    property_filters = params.get("properties") or {}
    for property_name, values in property_filters.items():
        q = q.filter(
            Product.properties.any(
                and_(ProductProperty.name == property_name, ProductProperty.value.in_(values))
            )
        )
    return q


def integration_filter_definitions(db: Session, option_limit: int = 100):
    """Возвращает стабильное описание только реально заполненных фильтров каталога."""
    filters = []
    for key, label in INTEGRATION_FILTER_LABELS.items():
        column = getattr(Product, key)
        values = [
            value
            for value, in db.query(column)
            .filter(column.isnot(None), func.trim(column) != "")
            .distinct()
            .order_by(column)
            .limit(option_limit + 1)
            .all()
        ]
        if values:
            filters.append({
                "key": key,
                "label": label,
                "type": "multi_select",
                "options": [{"value": value, "label": value} for value in values[:option_limit]],
                "options_paginated": len(values) > option_limit,
            })

    distinct_property_values = (
        db.query(
            ProductProperty.name.label("name"),
            ProductProperty.value.label("value"),
        )
        .filter(
            func.trim(ProductProperty.name) != "",
            ProductProperty.value.isnot(None),
            func.trim(ProductProperty.value) != "",
        )
        .distinct()
        .subquery()
    )
    ranked_property_values = (
        db.query(
            distinct_property_values.c.name,
            distinct_property_values.c.value,
            func.row_number().over(
                partition_by=distinct_property_values.c.name,
                order_by=distinct_property_values.c.value,
            ).label("position"),
        )
        .subquery()
    )
    property_rows = (
        db.query(
            ranked_property_values.c.name,
            ranked_property_values.c.value,
            ranked_property_values.c.position,
        )
        .filter(ranked_property_values.c.position <= option_limit + 1)
        .order_by(ranked_property_values.c.name, ranked_property_values.c.position)
        .all()
    )
    grouped_properties = {}
    for row in property_rows:
        grouped_properties.setdefault(row.name, []).append(row.value)
    for name, values in grouped_properties.items():
        filters.append({
            "key": f"property:{name}",
            "label": name.strip(),
            "type": "multi_select",
            "options": [{"value": value, "label": value} for value in values[:option_limit]],
            "options_paginated": len(values) > option_limit,
        })
    return filters


def integration_filter_options(
    db: Session,
    filter_key: str,
    search: str,
    page: int,
    page_size: int,
):
    """Постранично возвращает варианты одного реального фильтра."""
    if filter_key in INTEGRATION_FILTER_LABELS:
        column = getattr(Product, filter_key)
        query = db.query(column.label("value")).filter(column.isnot(None), func.trim(column) != "")
    elif filter_key.startswith("property:") and filter_key.removeprefix("property:").strip():
        property_name = filter_key.removeprefix("property:")
        exists = db.query(ProductProperty.id).filter(ProductProperty.name == property_name).first()
        if not exists:
            raise KeyError(filter_key)
        column = ProductProperty.value
        query = db.query(column.label("value")).filter(
            ProductProperty.name == property_name,
            column.isnot(None),
            func.trim(column) != "",
        )
    else:
        raise KeyError(filter_key)
    if search.strip():
        query = query.filter(column.ilike(f"%{search.strip()}%"))
    total = query.distinct().count()
    rows = query.distinct().order_by(column).offset((page - 1) * page_size).limit(page_size).all()
    return [row.value for row in rows], total


def integration_product_search(db: Session, request):
    """Фильтрует товары в БД: OR внутри фильтра, AND между фильтрами."""
    query = db.query(Product).options(
        selectinload(Product.properties),
        selectinload(Product.images),
    )
    search = request.search.strip()
    if search:
        pattern = f"%{search}%"
        query = query.filter(or_(
            Product.code.ilike(pattern),
            Product.article.ilike(pattern),
            Product.name.ilike(pattern),
        ))

    option_queries = []
    for key, values in request.filters.items():
        if key in INTEGRATION_FILTER_LABELS:
            column = getattr(Product, key)
            option_queries.append(select(literal(key).label("key"), column.label("value")).where(column.in_(values)))
        elif key.startswith("property:") and key.removeprefix("property:").strip():
            property_name = key.removeprefix("property:")
            option_queries.append(
                select(
                    (literal("property:") + ProductProperty.name).label("key"),
                    ProductProperty.value.label("value"),
                ).where(
                    ProductProperty.name == property_name,
                    ProductProperty.value.in_(values),
                )
            )
        else:
            raise KeyError(key)
    if option_queries:
        available_options = {
            (key, value)
            for key, value in db.execute(union_all(*option_queries)).all()
        }
        requested_options = {
            (key, value)
            for key, values in request.filters.items()
            for value in values
        }
        invalid_options = requested_options - available_options
        if invalid_options:
            key, value = sorted(invalid_options)[0]
            raise ValueError(f"Недопустимое значение фильтра {key}: {value}")

    for key, values in request.filters.items():
        if key in INTEGRATION_FILTER_LABELS:
            query = query.filter(getattr(Product, key).in_(values))
        elif key.startswith("property:") and key.removeprefix("property:").strip():
            property_name = key.removeprefix("property:")
            query = query.filter(Product.properties.any(and_(
                ProductProperty.name == property_name,
                ProductProperty.value.in_(values),
            )))
        else:
            raise KeyError(key)

    excluded_conditions = []
    for excluded in request.excluded:
        identifiers = []
        if excluded.code:
            identifiers.append(Product.code == excluded.code)
        if excluded.article:
            identifiers.append(Product.article == excluded.article)
        if identifiers:
            excluded_conditions.append(and_(*identifiers))
    if excluded_conditions:
        query = query.filter(~or_(*excluded_conditions))

    total = query.order_by(None).count()
    sort_column = INTEGRATION_SORT_FIELDS[request.sort_by]
    direction = sort_column.desc() if request.sort_dir == "desc" else sort_column.asc()
    items = (
        query.order_by(direction, Product.id.asc())
        .offset((request.page - 1) * request.page_size)
        .limit(request.page_size)
        .all()
    )
    return items, total


def integration_batch_product_info(db: Session, requested_products):
    """Пакетно сопоставляет товары и загружает связанные данные пятью запросами."""
    codes = {item.code.casefold() for item in requested_products if item.code}
    articles = {item.article.casefold() for item in requested_products if item.article}
    normalized_code = func.lower(func.trim(Product.code))
    normalized_article = func.lower(func.trim(Product.article))
    lookup_conditions = []
    if codes:
        lookup_conditions.append(normalized_code.in_(codes))
    if articles:
        lookup_conditions.append(normalized_article.in_(articles))
    candidates = db.query(Product).filter(or_(*lookup_conditions)).order_by(Product.id).all()

    by_code = {}
    by_article = {}
    for product in candidates:
        by_code.setdefault(product.code.strip().casefold(), product)
        if product.article and product.article.strip():
            by_article.setdefault(product.article.strip().casefold(), product)

    matched_products = []
    seen_product_ids = set()
    for requested in requested_products:
        product = by_code.get(requested.code.casefold()) if requested.code else None
        if product is None and requested.article:
            product = by_article.get(requested.article.casefold())
        if product is not None and product.id not in seen_product_ids:
            seen_product_ids.add(product.id)
            matched_products.append(product)

    product_ids = [product.id for product in matched_products]
    details = {
        product_id: {"properties": [], "stocks": [], "prices": [], "image_url": None}
        for product_id in product_ids
    }
    if not product_ids:
        return matched_products, details

    property_rows = (
        db.query(ProductProperty.product_id, ProductProperty.name, ProductProperty.value)
        .filter(ProductProperty.product_id.in_(product_ids))
        .order_by(ProductProperty.product_id, ProductProperty.name, ProductProperty.value, ProductProperty.id)
        .all()
    )
    seen_properties = {product_id: set() for product_id in product_ids}
    for product_id, raw_name, raw_value in property_rows:
        name = (raw_name or "").strip()
        value = (raw_value or "").strip()
        pair = (name, value)
        if not name or not value or pair in seen_properties[product_id]:
            continue
        seen_properties[product_id].add(pair)
        details[product_id]["properties"].append({"name": name, "value": value})
    for product_id in product_ids:
        details[product_id]["properties"].sort(
            key=lambda item: (item["name"].casefold(), item["value"].casefold())
        )

    first_orders = (
        db.query(
            ProductImage.product_id.label("product_id"),
            func.min(ProductImage.image_order).label("image_order"),
        )
        .filter(ProductImage.product_id.in_(product_ids))
        .group_by(ProductImage.product_id)
        .subquery()
    )
    image_rows = (
        db.query(ProductImage.product_id, ProductImage.image_url)
        .join(
            first_orders,
            and_(
                ProductImage.product_id == first_orders.c.product_id,
                ProductImage.image_order == first_orders.c.image_order,
            ),
        )
        .all()
    )
    for product_id, image_url in image_rows:
        details[product_id]["image_url"] = image_url

    warehouse_name = func.coalesce(WarehouseSetting.name, Stock.warehouse)
    stock_rows = (
        db.query(
            Stock.product_id,
            warehouse_name.label("warehouse_name"),
            func.sum(Stock.quantity).label("quantity"),
        )
        .outerjoin(WarehouseSetting, WarehouseSetting.code == Stock.warehouse)
        .filter(Stock.product_id.in_(product_ids))
        .group_by(Stock.product_id, Stock.warehouse, WarehouseSetting.name)
        .order_by(Stock.product_id, warehouse_name)
        .all()
    )
    for product_id, name, quantity in stock_rows:
        details[product_id]["stocks"].append({"warehouse": name, "quantity": quantity})

    price_rows = (
        db.query(Price.product_id, Price.price_type, Price.price_value)
        .filter(Price.product_id.in_(product_ids))
        .order_by(Price.product_id, Price.price_type, Price.price_value, Price.id)
        .all()
    )
    for product_id, name, value in price_rows:
        normalized_name = (name or "").strip()
        if normalized_name:
            details[product_id]["prices"].append({"name": normalized_name, "value": value, "currency": "RUB"})
    return matched_products, details


def paginated_products(db: Session, params):
    q = catalog_product_query(db, params)
    total = q.order_by(None).count()
    sort = params.get("sort", "updated_at")
    if sort == "is_new":
        sort_column = case((Product.created_at >= new_product_cutoff(), 1), else_=0)
    elif sort == "price":
        sort_column = (
            select(func.min(Price.price_value))
            .where(Price.product_id == Product.id)
            .correlate(Product)
            .scalar_subquery()
        )
    else:
        sort_column = SORT_FIELDS[sort]
    requested_order = params.get("order")
    is_descending = requested_order == "desc" or (
        requested_order is None and sort in {"updated_at", "is_new"}
    )
    direction = sort_column.desc() if is_descending else sort_column.asc()
    page = params["page"]
    page_size = params["page_size"]
    # По умолчанию сначала показываем недавно измененные и новые товары.
    # created_at и id обеспечивают стабильный порядок при одинаковом времени обновления.
    if sort == "updated_at":
        query_order = (direction, Product.created_at.desc(), Product.id.desc())
    elif sort == "is_new":
        query_order = (direction, Product.updated_at.desc(), Product.id.desc())
    else:
        query_order = (direction, Product.id.asc())
    items = q.order_by(*query_order).offset((page - 1) * page_size).limit(page_size).all()
    return items, {
        "page": page,
        "pageSize": page_size,
        "totalItems": total,
        "totalPages": ceil(total / page_size) if total else 0,
    }

def product_query(db: Session, params, eager_load: bool = True):
    q = db.query(Product)
    if eager_load:
        q = q.options(selectinload(Product.prices), selectinload(Product.stocks), selectinload(Product.properties), selectinload(Product.images))
    if search := params.get("search"):
        term = f"%{search.lower()}%"
        q = q.filter(func.lower(Product.search_text).like(term))
    property_name = str(params.get("property") or "").strip().casefold()
    property_value = str(params.get("property_value") or "").strip().casefold()
    if property_name and property_value:
        normalized_name = func.lower(func.trim(ProductProperty.name))
        normalized_value = func.lower(func.trim(ProductProperty.value))
        property_conditions = [
            normalized_name == property_name,
            normalized_value == property_value,
        ]
        if db.bind is not None and db.bind.dialect.name == "postgresql":
            # Хэш-условия используют компактный expression index. Полные сравнения
            # выше сохраняют точную семантику и защищают от теоретической коллизии MD5.
            property_conditions.extend(
                [
                    func.md5(normalized_name) == func.md5(property_name),
                    func.md5(normalized_value) == func.md5(property_value),
                ]
            )
        q = q.filter(
            Product.properties.any(
                and_(*property_conditions)
            )
        )
    for field in FILTER_FIELDS:
        if value := params.get(field):
            values = _values(value)
            if len(values) > 1:
                q = q.filter(getattr(Product, field).in_(values))
            elif values:
                q = q.filter(getattr(Product, field) == values[0])
    if product_type := params.get("product_type"):
        type_values = _values(product_type)
        if type_values:
            regular_type_values = [value for value in type_values if value != NEW_PRODUCT_TYPE_FILTER]
            configured_codes = [code for code, in db.query(ProductTypeSetting.code).filter(ProductTypeSetting.name.in_(regular_type_values)).all()]
            type_conditions = []
            if regular_type_values or configured_codes:
                type_conditions.append(Product.product_type.in_(list(dict.fromkeys([*regular_type_values, *configured_codes]))))
            if NEW_PRODUCT_TYPE_FILTER in type_values:
                type_conditions.append(Product.created_at >= new_product_cutoff())
            q = q.filter(or_(*type_conditions))
    if warehouse := params.get("warehouse"):
        warehouse_values = _values(warehouse)
        if warehouse_values:
            configured_codes = [code for code, in db.query(WarehouseSetting.code).filter(WarehouseSetting.name.in_(warehouse_values)).all()]
            q = q.join(Stock).filter(
                Stock.warehouse.in_(list(dict.fromkeys([*warehouse_values, *configured_codes]))),
                Stock.quantity > 0,
            )
    if params.get("in_stock") == "true":
        q = q.filter(Product.quantity > 0)
    if params.get("only_new"):
        q = q.filter(Product.created_at >= new_product_cutoff())
    if params.get("price_min") or params.get("price_max"):
        q = q.join(Price)
        if params.get("price_min"): q = q.filter(Price.price_value >= float(params["price_min"]))
        if params.get("price_max"): q = q.filter(Price.price_value <= float(params["price_max"]))
    if params.get("stock_min") or params.get("stock_max"):
        q = q.join(Stock)
        if params.get("stock_min"): q = q.filter(Stock.quantity >= float(params["stock_min"]))
        if params.get("stock_max"): q = q.filter(Stock.quantity <= float(params["stock_max"]))
    return q.distinct()

def list_filters(db: Session, params=None):
    base_ids = None
    if params:
        base_ids = catalog_product_query(db, params, eager_load=False).with_entities(Product.id).subquery()
    def product_scope(query):
        return query.filter(Product.id.in_(select(base_ids.c.id))) if base_ids is not None else query

    data = {
        field: [v[0] for v in product_scope(db.query(getattr(Product, field))).filter(getattr(Product, field).isnot(None)).distinct().order_by(getattr(Product, field)).all()]
        for field in FILTER_FIELDS
    }
    type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    type_codes = [code for code, in product_scope(db.query(Product.product_type)).filter(Product.product_type.isnot(None)).distinct().order_by(Product.product_type).all()]
    configured_types = list(dict.fromkeys(type_names[code] for code in type_codes if code in type_names))
    data["product_type"] = [NEW_PRODUCT_TYPE_FILTER, *configured_types]
    warehouse_names = {item.code: item.name for item in db.query(WarehouseSetting).all()}
    warehouse_query = db.query(Stock.warehouse).join(Product, Product.id == Stock.product_id)
    if base_ids is not None:
        warehouse_query = warehouse_query.filter(Product.id.in_(select(base_ids.c.id)))
    warehouse_codes = [code for code, in warehouse_query.filter(Stock.warehouse.isnot(None), Stock.quantity > 0).distinct().order_by(Stock.warehouse).all()]
    warehouse_values = [warehouse_names.get(code, code) for code in warehouse_codes]
    warehouse_rank = {name: index for index, name in enumerate(WAREHOUSE_ORDER)}
    data["warehouse"] = sorted(
        warehouse_values,
        key=lambda name: (warehouse_rank.get(name, len(WAREHOUSE_ORDER)), name.casefold()),
    )
    data["availability"] = ["В наличии", "Нет в наличии"]
    property_query = db.query(ProductProperty.name, ProductProperty.value).join(Product)
    if base_ids is not None:
        property_query = property_query.filter(Product.id.in_(select(base_ids.c.id)))
    property_rows = (
        property_query
        .filter(ProductProperty.value.isnot(None))
        .distinct()
        .order_by(ProductProperty.name, ProductProperty.value)
        .all()
    )
    for property_name, value in property_rows:
        normalized_name = property_name.strip().casefold()
        if property_name.strip() in EXCLUDED_PROPERTY_FILTERS or normalized_name in {"производитель", "страна", "бренд", "менеджер", "материал", "цвет"}:
            continue
        key = f"property:{property_name}"
        if len(data.setdefault(key, [])) < 100:
            data[key].append(value)
    barcode_query = db.query(Barcode.value).join(Product)
    if base_ids is not None:
        barcode_query = barcode_query.filter(Product.id.in_(select(base_ids.c.id)))
    data["barcode"] = [value for value, in barcode_query.distinct().order_by(Barcode.value).limit(100).all()]
    return data

def meta(db: Session):
    run = db.query(ImportRun).order_by(ImportRun.created_at.desc()).first()
    return {"last_import": run.finished_at if run else None, "product_count": db.query(Product).count(), "import_status": run.status if run else None, "imported_count": run.imported_count if run else None, "errors": run.errors if run else None}

def product_type_code(product: Product) -> str | None:
    if product.product_type:
        return product.product_type
    for prop in product.properties:
        if prop.name in {"Вид товара", "ВидТовара"}:
            return prop.value
    return None


def product_type_name(code: str | None, configured_names: dict[str, str] | None = None) -> str | None:
    """Возвращает понятное название вида товара вместо служебного числового кода."""
    normalized_code = (code or "").strip()
    if not normalized_code:
        return None
    return (configured_names or {}).get(normalized_code, DEFAULT_PRODUCT_TYPE_NAMES.get(normalized_code, normalized_code))


def product_display_name(product: Product) -> str:
    if product.name and product.name != product.code:
        return product.name
    for prop in product.properties:
        prop_name = prop.name.lower()
        is_name_property = (
            prop.name in {"Наименование", "Наименование товара", "Название товара", "Название"}
            or "наименование" in prop_name
            or "название" in prop_name
        )
        if is_name_property and prop.value and prop.value != product.code:
            return prop.value
    return product.name


def decorate(product: Product, product_type_names: dict[str, str] | None = None):
    retail = next((p.value for p in product.prices if "рознич" in p.price_type.lower()), product.prices[0].value if product.prices else None)
    product.retail_price = retail
    product.name = product_display_name(product)
    code = product_type_code(product)
    product.product_type = code
    if product_type_names is not None:
        product.product_type_name = product_type_name(code, product_type_names)
    return product
