import csv
import tempfile
from io import StringIO, BytesIO
from pathlib import Path

from typing import Annotated, Literal

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.importer.xml_importer import XMLCatalogImporter
from app.models.catalog import Favorite, Notification, Product, ProductTypeSetting, ServiceLog, Stock, ViewHistory, WarehouseSetting
from app.schemas.catalog import AutoImportStateOut, FtpConnectionTestOut, MetaOut, NotificationOut, ProductDetailOut, ProductListOut, ProductPageOut, ServiceLogOut, WarehouseSettingIn, WarehouseSettingOut, ProductTypeSettingIn, ProductTypeSettingOut, XmlServerSettingIn, XmlServerSettingOut
from app.services.catalog import decorate, list_filters, meta, product_query, paginated_products
from app.services.logging import add_log
from app.services.xml_auto_import import get_auto_import_state, get_xml_server_setting, start_manual_import, test_connection

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok"}

@router.post("/import", response_model=MetaOut)
def upload_xml(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.lower().endswith(".xml"):
        raise HTTPException(400, "Загрузите XML-файл")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xml") as tmp:
        tmp.write(file.file.read())
        path = Path(tmp.name)
    try:
        XMLCatalogImporter().import_file(db, path, file.filename)
    except Exception as exc:
        path.unlink(missing_ok=True)
        raise HTTPException(400, f"Ошибка импорта XML. Файл: {file.filename}. Причина: {exc}") from exc
    path.unlink(missing_ok=True)
    return meta(db)

@router.get("/products", response_model=list[ProductListOut])
def products(db: Session = Depends(get_db), limit: int = 60, offset: int = 0, search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None, warehouse: str | None = None, product_type: str | None = None):
    params = locals(); params.pop("db"); params.pop("limit"); params.pop("offset")
    type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    return [decorate(p, type_names) for p in product_query(db, params).offset(offset).limit(limit).all()]


@router.get("/products/count")
def products_count(db: Session = Depends(get_db), search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None, warehouse: str | None = None, product_type: str | None = None):
    params = locals(); params.pop("db")
    return {"count": product_query(db, params).count()}


@router.get("/products/search", response_model=ProductPageOut)
def search_products(
    db: Session = Depends(get_db),
    search: Annotated[str | None, Query(max_length=255)] = None,
    id: Annotated[int | None, Query(ge=1)] = None,
    name: Annotated[str | None, Query(max_length=512)] = None,
    code: Annotated[str | None, Query(max_length=128)] = None,
    article: Annotated[str | None, Query(max_length=255)] = None,
    barcode: Annotated[str | None, Query(max_length=2000)] = None,
    section: Annotated[str | None, Query(max_length=2000)] = None,
    manufacturer: Annotated[str | None, Query(max_length=2000)] = None,
    brand: Annotated[str | None, Query(max_length=2000)] = None,
    manager: Annotated[str | None, Query(max_length=2000)] = None,
    country: Annotated[str | None, Query(max_length=2000)] = None,
    material: Annotated[str | None, Query(max_length=2000)] = None,
    color: Annotated[str | None, Query(max_length=2000)] = None,
    product_type: Annotated[str | None, Query(alias="productType", max_length=2000)] = None,
    warehouse: Annotated[str | None, Query(max_length=2000)] = None,
    availability: Literal["all", "in_stock", "out_of_stock"] = "all",
    in_stock_only: Annotated[bool, Query(alias="inStockOnly")] = True,
    quantity_from: Annotated[float | None, Query(alias="quantityFrom")] = None,
    quantity_to: Annotated[float | None, Query(alias="quantityTo")] = None,
    price_from: Annotated[float | None, Query(alias="priceFrom", ge=0)] = None,
    price_to: Annotated[float | None, Query(alias="priceTo", ge=0)] = None,
    property: Annotated[list[str] | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize")] = 20,
    sort: Literal["id", "name", "article", "code", "price", "quantity"] = "id",
    order: Literal["asc", "desc"] = "asc",
):
    if page_size not in {20, 50, 100}:
        raise HTTPException(422, "pageSize должен быть равен 20, 50 или 100")
    if quantity_from is not None and quantity_to is not None and quantity_from > quantity_to:
        raise HTTPException(422, "Минимальное количество не может быть больше максимального")
    if price_from is not None and price_to is not None and price_from > price_to:
        raise HTTPException(422, "Минимальная цена не может быть больше максимальной")
    properties: dict[str, list[str]] = {}
    for item in property or []:
        property_name, separator, value = item.partition(":")
        if not separator or not property_name.strip() or not value.strip():
            raise HTTPException(422, "Свойство должно иметь формат «Название:Значение»")
        properties.setdefault(property_name.strip(), []).append(value.strip())
    params = {
        "search": search,
        "id": id,
        "name": name,
        "code": code,
        "article": article,
        "barcode": barcode,
        "section": section,
        "manufacturer": manufacturer,
        "brand": brand,
        "manager": manager,
        "country": country,
        "material": material,
        "color": color,
        "product_type": product_type,
        "warehouse": warehouse,
        "availability": availability,
        "in_stock_only": in_stock_only,
        "quantity_from": quantity_from,
        "quantity_to": quantity_to,
        "price_from": price_from,
        "price_to": price_to,
        "properties": properties,
        "page": page,
        "page_size": page_size,
        "sort": sort,
        "order": order,
    }
    items, pagination = paginated_products(db, params)
    type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    return {"items": [decorate(item, type_names) for item in items], "pagination": pagination}

@router.delete("/products")
def delete_products(product_ids: list[int] = Body(...), db: Session = Depends(get_db)):
    deleted = db.query(Product).filter(Product.id.in_(product_ids)).delete(synchronize_session=False)
    add_log(db, "products_delete", f"Удалено товаров: {deleted}")
    db.commit()
    return {"deleted": deleted}

@router.get("/products/{product_id}", response_model=ProductDetailOut)
def product_detail(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).options(selectinload(Product.prices), selectinload(Product.stocks), selectinload(Product.properties), selectinload(Product.analogs), selectinload(Product.barcodes), selectinload(Product.images)).get(product_id)
    if not product:
        raise HTTPException(404, "Товар не найден")
    db.add(ViewHistory(product_id=product_id)); db.commit()
    type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    warehouse_names = {item.code: item.name for item in db.query(WarehouseSetting).all()}
    for stock in product.stocks:
        stock.warehouse_name = warehouse_names.get(stock.warehouse, stock.warehouse)
    return decorate(product, type_names)


@router.get("/xml-server-settings", response_model=XmlServerSettingOut)
def xml_server_settings(db: Session = Depends(get_db)):
    return get_xml_server_setting(db)

@router.put("/xml-server-settings", response_model=XmlServerSettingOut)
def update_xml_server_settings(payload: XmlServerSettingIn, db: Session = Depends(get_db)):
    if payload.protocol.upper() != "FTP":
        raise HTTPException(400, "Пока поддерживается только FTP")
    setting = get_xml_server_setting(db)
    setting.protocol = payload.protocol.upper()
    setting.host = payload.host.strip()
    setting.port = payload.port
    setting.username = payload.username.strip()
    setting.password = payload.password
    setting.xml_dir = payload.xml_dir.strip() or "/"
    db.commit()
    db.refresh(setting)
    return setting

@router.post("/xml-server-settings/test", response_model=FtpConnectionTestOut)
def test_xml_server_settings(db: Session = Depends(get_db)):
    success, message = test_connection(db)
    return {"success": success, "message": message}

@router.get("/auto-import-state", response_model=AutoImportStateOut)
def auto_import_state(db: Session = Depends(get_db)):
    return get_auto_import_state(db)

@router.post("/auto-import/run")
def run_auto_import_now():
    started = start_manual_import()
    return {"started": started}

@router.get("/filters")
def filters(
    db: Session = Depends(get_db),
    brand: str | None = None,
    manager: str | None = None,
    manufacturer: str | None = None,
    country: str | None = None,
    product_type: str | None = Query(None, alias="productType"),
    warehouse: str | None = None,
    barcode: str | None = None,
    in_stock_only: bool = Query(True, alias="inStockOnly"),
    property: list[str] | None = Query(None),
):
    properties: dict[str, list[str]] = {}
    for item in property or []:
        property_name, separator, value = item.partition(":")
        if separator and property_name.strip() and value.strip():
            properties.setdefault(property_name.strip(), []).append(value.strip())
    return list_filters(db, {
        "brand": brand,
        "manager": manager,
        "manufacturer": manufacturer,
        "country": country,
        "product_type": product_type,
        "warehouse": warehouse,
        "barcode": barcode,
        "in_stock_only": in_stock_only,
        "properties": properties,
    })

@router.get("/meta", response_model=MetaOut)
def get_meta(db: Session = Depends(get_db)):
    return meta(db)

@router.post("/favorites/{product_id}")
def toggle_favorite(product_id: int, db: Session = Depends(get_db)):
    favorite = db.get(Favorite, product_id)
    if favorite: db.delete(favorite); active = False
    else: db.add(Favorite(product_id=product_id)); active = True
    db.commit(); return {"favorite": active}


@router.get("/warehouses", response_model=list[WarehouseSettingOut])
def warehouses(db: Session = Depends(get_db)):
    return db.query(WarehouseSetting).order_by(WarehouseSetting.code).all()

@router.get("/warehouses/codes")
def warehouse_codes(db: Session = Depends(get_db)):
    codes = [code for code, in db.query(Stock.warehouse).filter(Stock.warehouse.isnot(None)).distinct().order_by(Stock.warehouse).all()]
    return {"codes": codes}

@router.post("/warehouses", response_model=WarehouseSettingOut)
def create_warehouse(payload: WarehouseSettingIn, db: Session = Depends(get_db)):
    code = payload.code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(400, "Заполните код и имя склада")
    if db.query(WarehouseSetting).filter(WarehouseSetting.code == code).first():
        raise HTTPException(400, "Склад с таким кодом уже добавлен")
    warehouse = WarehouseSetting(code=code, name=name)
    db.add(warehouse)
    db.commit()
    db.refresh(warehouse)
    return warehouse

@router.put("/warehouses/{warehouse_id}", response_model=WarehouseSettingOut)
def update_warehouse(warehouse_id: int, payload: WarehouseSettingIn, db: Session = Depends(get_db)):
    warehouse = db.get(WarehouseSetting, warehouse_id)
    if not warehouse:
        raise HTTPException(404, "Склад не найден")
    code = payload.code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(400, "Заполните код и имя склада")
    duplicate = db.query(WarehouseSetting).filter(WarehouseSetting.code == code, WarehouseSetting.id != warehouse_id).first()
    if duplicate:
        raise HTTPException(400, "Склад с таким кодом уже добавлен")
    warehouse.code = code
    warehouse.name = name
    db.commit()
    db.refresh(warehouse)
    return warehouse

@router.delete("/warehouses/{warehouse_id}")
def delete_warehouse(warehouse_id: int, db: Session = Depends(get_db)):
    warehouse = db.get(WarehouseSetting, warehouse_id)
    if not warehouse:
        raise HTTPException(404, "Склад не найден")
    db.delete(warehouse)
    db.commit()
    return {"deleted": True}


@router.get("/product-types", response_model=list[ProductTypeSettingOut])
def product_types(db: Session = Depends(get_db)):
    return db.query(ProductTypeSetting).order_by(ProductTypeSetting.code).all()

@router.get("/product-types/codes")
def product_type_codes(db: Session = Depends(get_db)):
    codes = [code for code, in db.query(Product.product_type).filter(Product.product_type.isnot(None)).distinct().order_by(Product.product_type).all()]
    return {"codes": codes}

@router.post("/product-types", response_model=ProductTypeSettingOut)
def create_product_type(payload: ProductTypeSettingIn, db: Session = Depends(get_db)):
    code = payload.code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(400, "Заполните код и наименование вида товара")
    if db.query(ProductTypeSetting).filter(ProductTypeSetting.code == code).first():
        raise HTTPException(400, "Вид товара с таким кодом уже добавлен")
    item = ProductTypeSetting(code=code, name=name)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item

@router.put("/product-types/{product_type_id}", response_model=ProductTypeSettingOut)
def update_product_type(product_type_id: int, payload: ProductTypeSettingIn, db: Session = Depends(get_db)):
    item = db.get(ProductTypeSetting, product_type_id)
    if not item:
        raise HTTPException(404, "Вид товара не найден")
    code = payload.code.strip()
    name = payload.name.strip()
    if not code or not name:
        raise HTTPException(400, "Заполните код и наименование вида товара")
    duplicate = db.query(ProductTypeSetting).filter(ProductTypeSetting.code == code, ProductTypeSetting.id != product_type_id).first()
    if duplicate:
        raise HTTPException(400, "Вид товара с таким кодом уже добавлен")
    item.code = code
    item.name = name
    db.commit()
    db.refresh(item)
    return item

@router.delete("/product-types/{product_type_id}")
def delete_product_type(product_type_id: int, db: Session = Depends(get_db)):
    item = db.get(ProductTypeSetting, product_type_id)
    if not item:
        raise HTTPException(404, "Вид товара не найден")
    db.delete(item)
    db.commit()
    return {"deleted": True}


def error_notifications_query(db: Session):
    return db.query(Notification).filter(Notification.type.ilike("%error%"))

@router.get("/notifications", response_model=list[NotificationOut])
def notifications(db: Session = Depends(get_db), limit: int = 200):
    return error_notifications_query(db).order_by(Notification.created_at.desc()).limit(limit).all()

@router.get("/notifications/unread-count")
def notifications_unread_count(db: Session = Depends(get_db)):
    return {"count": error_notifications_query(db).filter(Notification.is_read.is_(False)).count()}

@router.post("/notifications/read-all")
def notifications_read_all(db: Session = Depends(get_db)):
    updated = error_notifications_query(db).filter(Notification.is_read.is_(False)).update({Notification.is_read: True}, synchronize_session=False)
    db.commit()
    return {"updated": updated}

@router.post("/notifications/{notification_id}/read")
def notification_read(notification_id: int, db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(404, "Уведомление не найдено")
    notification.is_read = True
    db.commit()
    return {"ok": True}

@router.get("/logs", response_model=list[ServiceLogOut])
def logs(db: Session = Depends(get_db)):
    return (
        db.query(ServiceLog)
        .filter(ServiceLog.level == "error")
        .order_by(ServiceLog.created_at.desc(), ServiceLog.id.desc())
        .limit(100)
        .all()
    )

@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), search: str | None = None):
    add_log(db, "export_csv", f"Экспорт CSV; поиск: {search or ''}")
    db.commit()
    output = StringIO(); writer = csv.writer(output); writer.writerow(["Код", "Артикул", "Название", "Раздел", "Остаток"])
    for p in product_query(db, {"search": search}).all(): writer.writerow([p.code, p.article, p.name, p.section, p.quantity])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=products.csv"})

@router.get("/export.xlsx")
def export_xlsx(db: Session = Depends(get_db), search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None, warehouse: str | None = None, product_type: str | None = None):
    params = locals(); params.pop("db")
    add_log(db, "export_xlsx", f"Экспорт Excel; поиск: {search or ''}")
    db.commit()
    wb = Workbook(); ws = wb.active; ws.append(["Код", "Артикул", "Название", "Раздел", "Остаток"])
    for p in product_query(db, params).all(): ws.append([p.code, p.article, p.name, p.section, p.quantity])
    stream = BytesIO(); wb.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=products.xlsx"})
