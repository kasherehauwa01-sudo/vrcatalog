from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import ImportRun, Price, Product, Stock, WarehouseSetting

FILTER_FIELDS = ["section", "manufacturer", "brand", "manager", "country", "material", "color"]

def product_query(db: Session, params):
    q = db.query(Product).options(selectinload(Product.prices), selectinload(Product.stocks))
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
    if warehouse := params.get("warehouse"):
        warehouse_values = [item.strip() for item in str(warehouse).split(",") if item.strip()]
        if warehouse_values:
            configured_codes = [code for code, in db.query(WarehouseSetting.code).filter(WarehouseSetting.name.in_(warehouse_values)).all()]
            q = q.join(Stock).filter(Stock.warehouse.in_(list(dict.fromkeys([*warehouse_values, *configured_codes]))))
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

def list_filters(db: Session):
    data = {field: [v[0] for v in db.query(getattr(Product, field)).filter(getattr(Product, field).isnot(None)).distinct().order_by(getattr(Product, field)).all()] for field in FILTER_FIELDS}
    warehouse_names = {item.code: item.name for item in db.query(WarehouseSetting).all()}
    warehouse_codes = [code for code, in db.query(Stock.warehouse).filter(Stock.warehouse.isnot(None)).distinct().order_by(Stock.warehouse).all()]
    data["warehouse"] = [warehouse_names.get(code, code) for code in warehouse_codes]
    data["availability"] = ["В наличии", "Нет в наличии"]
    return data

def meta(db: Session):
    run = db.query(ImportRun).order_by(ImportRun.created_at.desc()).first()
    return {"last_import": run.finished_at if run else None, "product_count": db.query(Product).count(), "import_status": run.status if run else None, "imported_count": run.imported_count if run else None, "errors": run.errors if run else None}

def decorate(product: Product):
    retail = next((p.value for p in product.prices if "рознич" in p.price_type.lower()), product.prices[0].value if product.prices else None)
    product.retail_price = retail
    return product
