import csv
import tempfile
from io import StringIO, BytesIO
from pathlib import Path

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from sqlalchemy.orm import Session, selectinload

from app.db.session import get_db
from app.importer.xml_importer import XMLCatalogImporter
from app.models.catalog import Favorite, Notification, Product, ServiceLog, ViewHistory
from app.schemas.catalog import MetaOut, NotificationOut, ProductDetailOut, ProductListOut, ServiceLogOut
from app.services.catalog import decorate, list_filters, meta, product_query
from app.services.logging import add_log

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
def products(db: Session = Depends(get_db), limit: int = 60, offset: int = 0, search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None):
    params = locals(); params.pop("db"); params.pop("limit"); params.pop("offset")
    return [decorate(p) for p in product_query(db, params).offset(offset).limit(limit).all()]


@router.get("/products/count")
def products_count(db: Session = Depends(get_db), search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None):
    params = locals(); params.pop("db")
    return {"count": product_query(db, params).count()}

@router.delete("/products")
def delete_products(product_ids: list[int] = Body(...), db: Session = Depends(get_db)):
    deleted = db.query(Product).filter(Product.id.in_(product_ids)).delete(synchronize_session=False)
    add_log(db, "products_delete", f"Удалено товаров: {deleted}")
    db.commit()
    return {"deleted": deleted}

@router.get("/products/{product_id}", response_model=ProductDetailOut)
def product_detail(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).options(selectinload(Product.prices), selectinload(Product.stocks), selectinload(Product.properties), selectinload(Product.analogs), selectinload(Product.barcodes)).get(product_id)
    if not product:
        raise HTTPException(404, "Товар не найден")
    db.add(ViewHistory(product_id=product_id)); db.commit()
    return decorate(product)

@router.get("/filters")
def filters(db: Session = Depends(get_db)):
    return list_filters(db)

@router.get("/meta", response_model=MetaOut)
def get_meta(db: Session = Depends(get_db)):
    return meta(db)

@router.post("/favorites/{product_id}")
def toggle_favorite(product_id: int, db: Session = Depends(get_db)):
    favorite = db.get(Favorite, product_id)
    if favorite: db.delete(favorite); active = False
    else: db.add(Favorite(product_id=product_id)); active = True
    db.commit(); return {"favorite": active}


@router.get("/notifications", response_model=list[NotificationOut])
def notifications(db: Session = Depends(get_db), limit: int = 200):
    return db.query(Notification).order_by(Notification.created_at.desc()).limit(limit).all()

@router.get("/notifications/unread-count")
def notifications_unread_count(db: Session = Depends(get_db)):
    return {"count": db.query(Notification).filter(Notification.is_read.is_(False)).count()}

@router.post("/notifications/{notification_id}/read")
def notification_read(notification_id: int, db: Session = Depends(get_db)):
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(404, "Уведомление не найдено")
    notification.is_read = True
    db.commit()
    return {"ok": True}

@router.get("/logs", response_model=list[ServiceLogOut])
def logs(db: Session = Depends(get_db), limit: int = 200):
    return db.query(ServiceLog).order_by(ServiceLog.created_at.desc()).limit(limit).all()

@router.get("/export.csv")
def export_csv(db: Session = Depends(get_db), search: str | None = None):
    add_log(db, "export_csv", f"Экспорт CSV; поиск: {search or ''}")
    db.commit()
    output = StringIO(); writer = csv.writer(output); writer.writerow(["Код", "Артикул", "Название", "Раздел", "Остаток"])
    for p in product_query(db, {"search": search}).all(): writer.writerow([p.code, p.article, p.name, p.section, p.quantity])
    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=products.csv"})

@router.get("/export.xlsx")
def export_xlsx(db: Session = Depends(get_db), search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None):
    params = locals(); params.pop("db")
    add_log(db, "export_xlsx", f"Экспорт Excel; поиск: {search or ''}")
    db.commit()
    wb = Workbook(); ws = wb.active; ws.append(["Код", "Артикул", "Название", "Раздел", "Остаток"])
    for p in product_query(db, params).all(): ws.append([p.code, p.article, p.name, p.section, p.quantity])
    stream = BytesIO(); wb.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=products.xlsx"})
