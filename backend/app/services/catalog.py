from math import ceil

from sqlalchemy import String, and_, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import Barcode, ImportRun, Price, Product, ProductProperty, Stock, WarehouseSetting, ProductTypeSetting

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
    "id": Product.id,
    "name": Product.name,
    "article": Product.article,
    "code": Product.code,
    "quantity": Product.quantity,
}


def _values(value):
    if not value:
        return []
    return [item.strip() for item in str(value).split(",") if item.strip()]


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
    if code := str(params.get("code") or "").strip():
        q = q.filter(Product.code.ilike(f"%{code}%"))
    if article := str(params.get("article") or "").strip():
        q = q.filter(Product.article.ilike(f"%{article}%"))
    barcode_values = _values(params.get("barcode"))
    if barcode_values:
        q = q.filter(Product.barcodes.any(Barcode.value.in_(barcode_values)))

    for field in FILTER_FIELDS:
        values = _values(params.get(field))
        if values:
            q = q.filter(getattr(Product, field).in_(values))

    type_values = _values(params.get("product_type"))
    if type_values:
        configured_codes = [
            code
            for code, in db.query(ProductTypeSetting.code)
            .filter(ProductTypeSetting.name.in_(type_values))
            .all()
        ]
        q = q.filter(Product.product_type.in_([*type_values, *configured_codes]))

    availability = params.get("availability")
    if availability == "in_stock":
        q = q.filter(Product.quantity > 0)
    elif availability == "out_of_stock":
        q = q.filter(Product.quantity <= 0)
    if params.get("in_stock_only"):
        q = q.filter(Product.stocks.any(Stock.quantity > 0))

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


def paginated_products(db: Session, params):
    q = catalog_product_query(db, params)
    total = q.order_by(None).count()
    sort = params.get("sort", "id")
    if sort == "price":
        sort_column = (
            select(func.min(Price.price_value))
            .where(Price.product_id == Product.id)
            .correlate(Product)
            .scalar_subquery()
        )
    else:
        sort_column = SORT_FIELDS[sort]
    direction = sort_column.desc() if params.get("order") == "desc" else sort_column.asc()
    page = params["page"]
    page_size = params["page_size"]
    items = q.order_by(direction, Product.id.asc()).offset((page - 1) * page_size).limit(page_size).all()
    return items, {
        "page": page,
        "pageSize": page_size,
        "totalItems": total,
        "totalPages": ceil(total / page_size) if total else 0,
    }

def product_query(db: Session, params):
    q = db.query(Product).options(selectinload(Product.prices), selectinload(Product.stocks), selectinload(Product.properties), selectinload(Product.images))
    if search := params.get("search"):
        term = f"%{search.lower()}%"
        q = q.filter(func.lower(Product.search_text).like(term))
    for field in FILTER_FIELDS:
        if value := params.get(field):
            values = [item.strip() for item in str(value).split(",") if item.strip()]
            if len(values) > 1:
                q = q.filter(getattr(Product, field).in_(values))
            elif values:
                q = q.filter(getattr(Product, field) == values[0])
    if product_type := params.get("product_type"):
        type_values = [item.strip() for item in str(product_type).split(",") if item.strip()]
        if type_values:
            configured_codes = [code for code, in db.query(ProductTypeSetting.code).filter(ProductTypeSetting.name.in_(type_values)).all()]
            q = q.filter(Product.product_type.in_(list(dict.fromkeys([*type_values, *configured_codes]))))
    if warehouse := params.get("warehouse"):
        warehouse_values = [item.strip() for item in str(warehouse).split(",") if item.strip()]
        if warehouse_values:
            configured_codes = [code for code, in db.query(WarehouseSetting.code).filter(WarehouseSetting.name.in_(warehouse_values)).all()]
            q = q.join(Stock).filter(
                Stock.warehouse.in_(list(dict.fromkeys([*warehouse_values, *configured_codes]))),
                Stock.quantity > 0,
            )
    if params.get("in_stock") == "true":
        q = q.filter(Product.quantity > 0)
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
    data["product_type"] = list(dict.fromkeys(type_names[code] for code in type_codes if code in type_names))
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
        product.product_type_name = product_type_names.get(code, code) if code else None
    return product
