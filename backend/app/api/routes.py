import csv
import hashlib
import json
import logging
from math import ceil
import secrets
import tempfile
import time
import uuid
import gc
from copy import copy
from concurrent.futures import ThreadPoolExecutor, wait
from io import StringIO, BytesIO
from pathlib import Path
from threading import Lock
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from zipfile import ZIP_DEFLATED, ZipFile

from typing import Annotated, Any, Callable, Literal

from fastapi import APIRouter, Body, Depends, File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from openpyxl import Workbook
from openpyxl.drawing.image import Image as ExcelImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from PIL import Image as PillowImage, UnidentifiedImageError
import xlsxwriter
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.db.session import SessionLocal, get_db
from app.core.config import settings
from app.importer.xml_importer import XMLCatalogImporter, public_image_url
from app.models.catalog import Favorite, Notification, NotificationEmailHistory, Product, ProductTypeSetting, ServiceLog, Stock, ViewHistory, WarehouseSetting
from app.schemas.catalog import AnalogSelectionSettingIn, AnalogSelectionSettingOut, AutoImportStateOut, DynamicAnalogOut, FtpConnectionTestOut, IntegrationBatchProductsRequest, IntegrationBatchProductsResponse, IntegrationFiltersResponse, IntegrationProductSearchRequest, IntegrationProductSearchResponse, MailSettingIn, MailSettingOut, MetaOut, NotificationHistoryOut, NotificationOut, ProductDetailOut, ProductListOut, ProductPageOut, ProductTypeUpdateIn, ScenarioRunOut, ScenarioSettingIn, ScenarioSettingOut, ScenarioSummaryOut, ServiceLogOut, TestMailIn, WarehouseSettingIn, WarehouseSettingOut, ProductTypeSettingIn, ProductTypeSettingOut, XmlServerSettingIn, XmlServerSettingOut
from app.services.analogs import available_characteristics, find_product_analogs, get_analog_settings, primary_properties
from app.services.catalog import catalog_product_query, decorate, integration_batch_product_info, integration_filter_definitions, integration_filter_options, integration_product_search, list_filters, meta, product_query, paginated_products, product_type_name
from app.services.logging import add_log
from app.services.export_image_cache import maintain_export_image_cache_safely
from app.services.xml_auto_import import get_auto_import_state, get_xml_server_setting, start_manual_import, test_connection
from app.services.monthly_promotion import check_connection as check_mail_connection, encrypt_password, get_mail_setting, get_scenario_setting, recipients as scenario_recipients, run_scenario, send_email

router = APIRouter()

# Одновременная генерация нескольких файлов с фотографиями может исчерпать
# память контейнера и привести к 502 от nginx, поэтому задания выполняются по одному.
export_executor = ThreadPoolExecutor(max_workers=1)
export_jobs: dict[str, dict[str, Any]] = {}
export_jobs_lock = Lock()
EXPORT_JOB_TTL_SECONDS = 60 * 60
EXPORT_DOWNLOAD_CHUNK_SIZE = 2 * 1024 * 1024
# openpyxl хранит каждую картинку в памяти до сохранения книги. Ограничение
# защищает backend от OOM на больших каталогах; остальные фото остаются ссылками.
MAX_EMBEDDED_EXPORT_IMAGES = 10_000
EXPORT_PRODUCT_BATCH_SIZE = 100

logger = logging.getLogger(__name__)
EXPORT_PAGINATION_KEYS = {"page", "page_size", "pageSize", "limit", "offset", "skip", "sort", "order"}


def filtered_product_ids_subquery(db: Session, params: dict):
    """Возвращает единый запрос уникальных ID со всеми фильтрами, но без пагинации UI."""
    filter_params = {key: value for key, value in params.items() if key not in EXPORT_PAGINATION_KEYS}
    return (
        catalog_product_query(db, filter_params, eager_load=False)
        .order_by(None)
        .with_entities(Product.id.label("product_id"))
        .distinct()
        .subquery()
    )

@router.get("/health")
def health():
    return {"status": "ok"}


def require_integration_token(authorization: str | None) -> None:
    """Проверяет межсервисный Bearer token, не раскрывая его в логах и ответах."""
    if not authorization:
        raise HTTPException(401, "Требуется Bearer token")
    scheme, separator, provided_token = authorization.partition(" ")
    if not separator or scheme.casefold() != "bearer" or not provided_token.strip():
        raise HTTPException(403, "Недостаточно прав для доступа")
    if not settings.internal_api_token:
        raise HTTPException(403, "Межсервисный API не настроен")
    if not secrets.compare_digest(provided_token.strip(), settings.internal_api_token):
        raise HTTPException(403, "Недостаточно прав для доступа")


@router.get("/integration/product-filters", response_model=IntegrationFiltersResponse)
def integration_product_filters(
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
):
    require_integration_token(authorization)
    return {"filters": integration_filter_definitions(db)}


@router.get("/integration/product-filters/{filter_key}/options")
def integration_product_filter_options(
    filter_key: str,
    search: Annotated[str, Query(max_length=255)] = "",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
):
    require_integration_token(authorization)
    try:
        values, total = integration_filter_options(db, filter_key, search, page, page_size)
    except KeyError as exc:
        raise HTTPException(422, f"Неизвестный фильтр: {filter_key}") from exc
    return {
        "items": [{"value": value, "label": value} for value in values],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": ceil(total / page_size) if total else 0,
    }


@router.post("/integration/products/search", response_model=IntegrationProductSearchResponse)
def integration_products_search(
    request: IntegrationProductSearchRequest,
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
):
    require_integration_token(authorization)
    try:
        products, total = integration_product_search(db, request)
    except KeyError as exc:
        raise HTTPException(422, f"Неизвестный фильтр: {exc.args[0]}") from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "items": [
            {
                "id": product.id,
                "code": str(product.code),
                "article": str(product.article) if product.article is not None else None,
                "name": product.name,
                "image_url": public_image_url(product.images[0].image_url) if product.images else None,
                "properties": [
                    {
                        "key": f"property:{item.name}",
                        "label": item.name.strip(),
                        "value": item.value or "",
                        "display_value": item.value or "",
                    }
                    for item in product.properties
                ],
            }
            for product in products
        ],
        "total": total,
        "page": request.page,
        "page_size": request.page_size,
        "pages": ceil(total / request.page_size) if total else 0,
    }


@router.post("/integration/products/batch-info", response_model=IntegrationBatchProductsResponse)
def integration_products_batch_info(
    request: IntegrationBatchProductsRequest,
    db: Session = Depends(get_db),
    authorization: Annotated[str | None, Header()] = None,
):
    try:
        require_integration_token(authorization)
    except HTTPException as exc:
        # Для batch-контракта Sales Journal любая ошибка Bearer-а является 401.
        raise HTTPException(401, exc.detail) from exc
    products, details_by_product_id = integration_batch_product_info(
        db,
        request.products,
    )
    property_aliases = {
        "brand": {"бренд", "brand"},
        "manufacturer": {"производитель", "manufacturer"},
        "category": {"категория", "category"},
        "material": {"материал", "material"},
    }

    def normalized_value(product, field: str):
        direct_fields = {
            "brand": product.brand,
            "manufacturer": product.manufacturer,
            "category": product.section,
            "material": product.material,
        }
        direct_value = (direct_fields[field] or "").strip()
        if direct_value:
            return direct_value
        return next((
            item["value"]
            for item in details_by_product_id[product.id]["properties"]
            if item["name"].casefold() in property_aliases[field]
        ), None)

    return {
        "items": [
            {
                "code": str(product.code),
                "article": str(product.article) if product.article is not None else None,
                "name": product.name,
                "horeca": any(
                    item["name"].casefold() == "horeca" and item["value"].casefold() == "horeca"
                    for item in details_by_product_id[product.id]["properties"]
                ),
                "image_url": public_image_url(details_by_product_id[product.id]["image_url"]),
                "brand": normalized_value(product, "brand"),
                "manufacturer": normalized_value(product, "manufacturer"),
                "category": normalized_value(product, "category"),
                "material": normalized_value(product, "material"),
                "properties": [
                    {
                        **item,
                        "value": product_type_name(item["value"]),
                    } if item["name"].casefold() in {"вид товара", "видтовара"} else item
                    for item in details_by_product_id[product.id]["properties"]
                ],
                "stocks": details_by_product_id[product.id]["stocks"],
                "prices": details_by_product_id[product.id]["prices"],
            }
            for product in products
        ]
    }

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

@router.get("/products", response_model=list[ProductListOut], response_model_exclude_none=True)
def products(db: Session = Depends(get_db), limit: Annotated[int, Query(ge=1, le=10000)] = 60, offset: Annotated[int, Query(ge=0)] = 0, search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None, warehouse: str | None = None, product_type: str | None = None, only_new: Annotated[bool, Query(alias="onlyNew")] = False, property: str | None = None, property_value: str | None = None, authorization: Annotated[str | None, Header()] = None, x_internal_token: Annotated[str | None, Header()] = None):
    if (property is None) != (property_value is None):
        raise HTTPException(422, "Параметры property и property_value должны передаваться вместе")
    if property is not None:
        configured_token = settings.internal_api_token
        if not configured_token:
            raise HTTPException(401, "Межсервисный API не настроен")
        if authorization and not authorization.lower().startswith("bearer "):
            raise HTTPException(403, "Недостаточно прав для доступа")
        bearer_token = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else None
        provided_token = bearer_token or x_internal_token
        if not authorization and not x_internal_token:
            raise HTTPException(401, "Требуется Bearer token")
        if not provided_token:
            raise HTTPException(403, "Недостаточно прав для доступа")
        if not secrets.compare_digest(provided_token, configured_token):
            raise HTTPException(403, "Недостаточно прав для доступа")
    params = {
        "search": search, "section": section, "manufacturer": manufacturer,
        "brand": brand, "manager": manager, "country": country,
        "material": material, "color": color, "in_stock": in_stock,
        "price_min": price_min, "price_max": price_max,
        "stock_min": stock_min, "stock_max": stock_max,
        "warehouse": warehouse, "product_type": product_type,
        "only_new": only_new, "property": property,
        "property_value": property_value,
    }
    type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    matched_products = product_query(db, params).offset(offset).limit(limit).all()
    if property is not None:
        normalized_name = property.strip().casefold()
        normalized_value = property_value.strip().casefold()
        return JSONResponse([
            {
                "id": product.id,
                "article": product.article,
                "code": product.code,
                "name": product.name,
                "properties": {
                    item.name.strip(): (item.value or "").strip()
                    for item in product.properties
                    if item.name.strip().casefold() == normalized_name
                    and (item.value or "").strip().casefold() == normalized_value
                },
            }
            for product in matched_products
        ])
    return [decorate(p, type_names) for p in matched_products]


@router.get("/products/count")
def products_count(db: Session = Depends(get_db), search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None, warehouse: str | None = None, product_type: str | None = None, only_new: Annotated[bool, Query(alias="onlyNew")] = False):
    params = locals(); params.pop("db")
    return {"count": product_query(db, params).count()}


@router.get("/products/search", response_model=ProductPageOut)
def search_products(
    db: Session = Depends(get_db),
    search: Annotated[str | None, Query(max_length=255)] = None,
    id: Annotated[int | None, Query(ge=1)] = None,
    name: Annotated[str | None, Query(max_length=512)] = None,
    code: Annotated[str | None, Query(max_length=2000)] = None,
    article: Annotated[str | None, Query(max_length=2000)] = None,
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
    exclude_yyy: Annotated[bool, Query(alias="excludeYyy")] = True,
    only_new: Annotated[bool, Query(alias="onlyNew")] = False,
    quantity_from: Annotated[float | None, Query(alias="quantityFrom")] = None,
    quantity_to: Annotated[float | None, Query(alias="quantityTo")] = None,
    price_from: Annotated[float | None, Query(alias="priceFrom", ge=0)] = None,
    price_to: Annotated[float | None, Query(alias="priceTo", ge=0)] = None,
    property: Annotated[list[str] | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(alias="pageSize")] = 100,
    sort: Literal["updated_at", "is_new", "id", "name", "article", "code", "price", "quantity"] = "updated_at",
    order: Literal["asc", "desc"] | None = None,
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
        "exclude_yyy": exclude_yyy,
        "only_new": only_new,
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


@router.get("/products/{product_id}/dynamic-analogs", response_model=list[DynamicAnalogOut])
def product_dynamic_analogs(product_id: int, show_all: bool = False, db: Session = Depends(get_db)):
    # В карточке показываем не более десяти позиций, а отдельное окно получает
    # полный перечень, прошедший установленный минимальный процент похожести.
    analogs = find_product_analogs(
        db,
        product_id,
        include_all=show_all,
        maximum_analogs=10,
    )
    if analogs is None:
        raise HTTPException(404, "Товар не найден")
    result = []
    for item in analogs:
        product = item.product
        retail = next((price.value for price in product.prices if "рознич" in price.price_type.lower()), product.prices[0].value if product.prices else None)
        result.append({
            "id": product.id, "code": product.code, "article": product.article,
            "name": product.name, "similarity": item.similarity,
            "retail_price": retail,
            "image_url": product.images[0].image_url if product.images else None,
            "matched": item.matched, "unmatched": item.unmatched,
        })
    return result


@router.get("/analog-selection-settings", response_model=AnalogSelectionSettingOut)
def analog_selection_settings(db: Session = Depends(get_db)):
    setting = get_analog_settings(db)
    return {
        "primary_properties": primary_properties(setting),
        "minimum_similarity": setting.minimum_similarity,
        "maximum_analogs": setting.maximum_analogs,
        "available_properties": available_characteristics(db),
    }


@router.put("/analog-selection-settings", response_model=AnalogSelectionSettingOut)
def update_analog_selection_settings(payload: AnalogSelectionSettingIn, db: Session = Depends(get_db)):
    setting = get_analog_settings(db)
    setting.primary_properties_json = json.dumps(payload.primary_properties, ensure_ascii=False)
    setting.minimum_similarity = payload.minimum_similarity
    setting.maximum_analogs = payload.maximum_analogs
    add_log(db, "analog_selection_settings_updated", json.dumps(payload.model_dump(), ensure_ascii=False))
    db.commit()
    return analog_selection_settings(db)


@router.patch("/products/{product_id}/product-type")
def update_product_product_type(product_id: int, payload: ProductTypeUpdateIn, db: Session = Depends(get_db)):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404, "Товар не найден")
    db.info["change_source"] = "manual"
    product.product_type = payload.product_type.strip() if payload.product_type else None
    db.commit()
    return {"ok": True, "product_type": product.product_type}


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
    setting.connection_attempts = payload.connection_attempts
    setting.retry_delay_seconds = payload.retry_delay_seconds
    db.commit()
    db.refresh(setting)
    return setting

@router.post("/xml-server-settings/test", response_model=FtpConnectionTestOut)
def test_xml_server_settings(db: Session = Depends(get_db)):
    success, message = test_connection(db)
    return {"success": success, "message": message}


def mail_setting_response(item) -> dict:
    return {
        "smtp_host": item.smtp_host,
        "smtp_port": item.smtp_port,
        "encryption": item.encryption,
        "username": item.username,
        "password_configured": bool(item.encrypted_password),
        "sender_name": item.sender_name,
        "sender_email": item.sender_email,
        "connection_status": item.connection_status,
        "last_success_at": item.last_success_at,
        "last_sent_at": item.last_sent_at,
        "last_error": item.last_error,
    }


@router.get("/mail-settings", response_model=MailSettingOut)
def mail_settings(db: Session = Depends(get_db)):
    return mail_setting_response(get_mail_setting(db))


@router.put("/mail-settings", response_model=MailSettingOut)
def update_mail_settings(payload: MailSettingIn, db: Session = Depends(get_db)):
    item = get_mail_setting(db)
    for field in ("smtp_host", "smtp_port", "encryption", "username", "sender_name", "sender_email"):
        setattr(item, field, getattr(payload, field))
    if payload.password:
        item.encrypted_password = encrypt_password(payload.password)
    db.commit()
    check_mail_connection(db, item)
    return mail_setting_response(item)


@router.post("/mail-settings/test")
def send_test_mail(payload: TestMailIn, db: Session = Depends(get_db)):
    try:
        send_email(db, [payload.email], "Тест уведомлений VR Catalog", "<h2>Тестовое письмо отправлено успешно</h2>")
        db.commit()
        return {"success": True, "message": "Тестовое письмо отправлено успешно."}
    except Exception as exc:
        db.rollback()
        item = get_mail_setting(db)
        item.connection_status = "error"
        item.last_error = str(exc)
        db.commit()
        return {"success": False, "message": f"Ошибка отправки: {exc}"}


@router.get("/notification-scenarios/monthly-promotion", response_model=ScenarioSettingOut)
def monthly_promotion_settings(db: Session = Depends(get_db)):
    item = get_scenario_setting(db)
    return {"code": item.code, "enabled": item.enabled, "send_time": item.send_time, "recipients": scenario_recipients(item)}


@router.get("/notification-scenarios", response_model=list[ScenarioSummaryOut])
def notification_scenarios(db: Session = Depends(get_db)):
    item = get_scenario_setting(db)
    return [{"code": item.code, "name": "Акция месяца", "enabled": item.enabled}]


@router.patch("/notification-scenarios/{code}/enabled", response_model=ScenarioSummaryOut)
def toggle_notification_scenario(code: str, enabled: bool = Body(embed=True), db: Session = Depends(get_db)):
    if code != "monthly_promotion":
        raise HTTPException(404, "Сценарий не найден")
    item = get_scenario_setting(db)
    item.enabled = enabled
    add_log(db, "notification_scenario_toggled", json.dumps({"scenario": code, "enabled": enabled}, ensure_ascii=False))
    db.commit()
    return {"code": item.code, "name": "Акция месяца", "enabled": item.enabled}


@router.put("/notification-scenarios/monthly-promotion", response_model=ScenarioSettingOut)
def update_monthly_promotion_settings(payload: ScenarioSettingIn, db: Session = Depends(get_db)):
    item = get_scenario_setting(db)
    item.enabled = payload.enabled
    item.send_time = payload.send_time
    item.recipients_json = json.dumps(list(dict.fromkeys(payload.recipients)), ensure_ascii=False)
    add_log(db, "notification_scenario_updated", json.dumps({"scenario": item.code, "send_time": item.send_time, "recipients": len(payload.recipients)}, ensure_ascii=False))
    db.commit()
    return {"code": item.code, "enabled": item.enabled, "send_time": item.send_time, "recipients": scenario_recipients(item)}


@router.post("/notification-scenarios/monthly-promotion/run", response_model=ScenarioRunOut)
def run_monthly_promotion(db: Session = Depends(get_db)):
    return run_scenario(db)


@router.get("/notification-scenarios/monthly-promotion/preview", response_model=ScenarioRunOut)
def preview_monthly_promotion(db: Session = Depends(get_db)):
    from app.models.catalog import ProductTypeChange
    from app.services.monthly_promotion import build_preview, consolidate_changes
    changes = consolidate_changes(db.query(ProductTypeChange).filter(ProductTypeChange.processed.is_(False)).order_by(ProductTypeChange.changed_at).all())
    html = build_preview(changes)
    add_log(db, "notification_scenario_preview", json.dumps({"scenario": "monthly_promotion", "changes": len(changes)}, ensure_ascii=False))
    db.commit()
    return {"status": "preview", "changes": len(changes), "sent": 0, "recipients": scenario_recipients(get_scenario_setting(db)), "html": html}


@router.get("/notification-scenarios/{code}/history", response_model=list[NotificationHistoryOut])
def notification_scenario_history(
    code: str,
    search: str = "",
    status: Literal["all", "sent", "error"] = "all",
    db: Session = Depends(get_db),
):
    query = db.query(NotificationEmailHistory).filter(NotificationEmailHistory.scenario_code == code)
    if search.strip():
        query = query.filter(NotificationEmailHistory.recipients_json.ilike(f"%{search.strip()}%"))
    if status != "all":
        query = query.filter(NotificationEmailHistory.status == status)
    rows = query.order_by(NotificationEmailHistory.sent_at.desc(), NotificationEmailHistory.id.desc()).limit(500).all()
    result = []
    for item in rows:
        result.append({
            "id": item.id, "scenario_code": item.scenario_code, "sent_at": item.sent_at,
            "recipients": json.loads(item.recipients_json), "subject": item.subject,
            "body_html": item.body_html, "status": item.status, "error_message": item.error_message,
            "duration_ms": item.duration_ms,
        })
    return result

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
    exclude_yyy: bool = Query(True, alias="excludeYyy"),
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
        "exclude_yyy": exclude_yyy,
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


def cleanup_export_jobs() -> None:
    """Удаляет устаревшие задания и временные файлы экспорта."""
    cutoff = time.monotonic() - EXPORT_JOB_TTL_SECONDS
    with export_jobs_lock:
        expired_ids = [job_id for job_id, job in export_jobs.items() if job["created_at"] < cutoff]
        expired_jobs = [export_jobs.pop(job_id) for job_id in expired_ids]
    for job in expired_jobs:
        if job.get("path"):
            Path(job["path"]).unlink(missing_ok=True)


def create_xlsx_export(job_id: str, params: dict, columns: list[str] | None) -> None:
    """Формирует XLSX на диске вне HTTP-запроса."""
    path: str | None = None
    started_at = time.monotonic()
    try:
        with SessionLocal() as db:
            filtered_ids = filtered_product_ids_subquery(db, params)
            product_count = db.query(func.count()).select_from(filtered_ids).scalar() or 0
            has_photos = bool(columns and "photo" in columns)
            safe_params = {key: value for key, value in params.items() if value not in (None, "", [], {}, False, "all")}
            with export_jobs_lock:
                export_jobs[job_id].update(total=product_count, processed=0, progress=0)
            logger.info("Экспорт %s: начало, товаров=%s, фильтры=%s, фото=%s, RSS=%s МБ", job_id, product_count, safe_params, has_photos, current_rss_mb())
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as output:
                path = output.name
            processed = write_export_workbook_streaming(db, params, columns, path, job_id, product_count, filtered_ids)
            if has_photos:
                # Одно обслуживание после задания вместо обхода каталога для каждой фотографии.
                maintain_export_image_cache_safely(job_id)
            filename = "products.xlsx"
            media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            gc.collect()
            if processed != product_count:
                logger.error("Экспорт %s: количество не совпало, обработано=%s, ожидалось=%s", job_id, processed, product_count)
                raise RuntimeError(f"Количество строк экспорта изменилось: обработано {processed}, ожидалось {product_count}")
            with export_jobs_lock:
                export_jobs[job_id].update(processed=processed, progress=100)
            logger.info("Экспорт %s завершён: обработано=%s, ожидалось=%s, время=%.1f сек., RSS=%s МБ", job_id, processed, product_count, time.monotonic() - started_at, current_rss_mb())
        with export_jobs_lock:
            export_jobs[job_id].update(status="ready", path=path, filename=filename, media_type=media_type)
    except Exception as exc:
        if path:
            Path(path).unlink(missing_ok=True)
        with export_jobs_lock:
            export_jobs[job_id].update(status="error", error=str(exc) or "Не удалось сформировать Excel")


@router.post("/exports/xlsx")
def start_xlsx_export(
    search: Annotated[str | None, Query(max_length=255)] = None,
    id: Annotated[int | None, Query(ge=1)] = None,
    name: Annotated[str | None, Query(max_length=512)] = None,
    code: Annotated[str | None, Query(max_length=2000)] = None,
    article: Annotated[str | None, Query(max_length=2000)] = None,
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
    exclude_yyy: Annotated[bool, Query(alias="excludeYyy")] = True,
    only_new: Annotated[bool, Query(alias="onlyNew")] = False,
    quantity_from: Annotated[float | None, Query(alias="quantityFrom")] = None,
    quantity_to: Annotated[float | None, Query(alias="quantityTo")] = None,
    price_from: Annotated[float | None, Query(alias="priceFrom", ge=0)] = None,
    price_to: Annotated[float | None, Query(alias="priceTo", ge=0)] = None,
    property: Annotated[list[str] | None, Query()] = None,
    column: Annotated[list[str] | None, Query()] = None,
):
    """Запускает длительное формирование Excel и сразу возвращает идентификатор задания."""
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
        "search": search, "id": id, "name": name, "code": code, "article": article,
        "barcode": barcode, "section": section, "manufacturer": manufacturer, "brand": brand,
        "manager": manager, "country": country, "material": material, "color": color,
        "product_type": product_type, "warehouse": warehouse, "availability": availability,
        "in_stock_only": in_stock_only, "exclude_yyy": exclude_yyy, "only_new": only_new,
        "quantity_from": quantity_from, "quantity_to": quantity_to,
        "price_from": price_from, "price_to": price_to, "properties": properties,
    }
    columns = column
    cleanup_export_jobs()
    job_id = uuid.uuid4().hex
    with export_jobs_lock:
        export_jobs[job_id] = {"status": "processing", "created_at": time.monotonic(), "path": None, "error": None, "processed": 0, "total": None, "progress": 0}
    export_executor.submit(create_xlsx_export, job_id, params, columns)
    return {"job_id": job_id, "status": "processing"}


@router.get("/exports/xlsx/{job_id}")
def xlsx_export_status(job_id: str):
    """Возвращает состояние фонового экспорта."""
    cleanup_export_jobs()
    with export_jobs_lock:
        job = export_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Задание экспорта не найдено или устарело")
        size = Path(job["path"]).stat().st_size if job["status"] == "ready" and job["path"] else None
        return {
            "status": job["status"],
            "error": job["error"],
            "size": size,
            "filename": job.get("filename"),
            "media_type": job.get("media_type"),
            "processed": job.get("processed", 0),
            "total": job.get("total"),
            "progress": job.get("progress", 0),
        }


@router.get("/exports/xlsx/{job_id}/download")
def download_xlsx_export(job_id: str):
    """Отдаёт уже сформированный файл без длительного ожидания в прокси."""
    with export_jobs_lock:
        job = export_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Задание экспорта не найдено или устарело")
        if job["status"] != "ready" or not job["path"]:
            raise HTTPException(409, "Файл Excel ещё не готов")
        path = job["path"]
    return FileResponse(
        path,
        media_type=job.get("media_type") or "application/octet-stream",
        filename=job.get("filename") or "products.xlsx",
    )


@router.get("/exports/xlsx/{job_id}/chunk")
def download_xlsx_export_chunk(job_id: str, offset: Annotated[int, Query(ge=0)] = 0):
    """Отдаёт небольшой фрагмент файла, чтобы внешний прокси не ожидал всю выгрузку целиком."""
    with export_jobs_lock:
        job = export_jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Задание экспорта не найдено или устарело")
        if job["status"] != "ready" or not job["path"]:
            raise HTTPException(409, "Файл Excel ещё не готов")
        path = Path(job["path"])
    file_size = path.stat().st_size
    if offset >= file_size:
        raise HTTPException(416, "Смещение находится за пределами файла")
    with path.open("rb") as source:
        source.seek(offset)
        content = source.read(EXPORT_DOWNLOAD_CHUNK_SIZE)
    return Response(
        content,
        media_type="application/octet-stream",
        headers={
            "X-File-Size": str(file_size),
            "X-Next-Offset": str(offset + len(content)),
        },
    )


@router.get("/export.xlsx")
def export_xlsx(db: Session = Depends(get_db), search: str | None = None, section: str | None = None, manufacturer: str | None = None, brand: str | None = None, manager: str | None = None, country: str | None = None, material: str | None = None, color: str | None = None, in_stock: str | None = None, price_min: str | None = None, price_max: str | None = None, stock_min: str | None = None, stock_max: str | None = None, warehouse: str | None = None, product_type: str | None = None, exclude_yyy: bool = Query(True, alias="excludeYyy"), column: Annotated[list[str] | None, Query()] = None):
    params = locals(); params.pop("db"); columns = params.pop("column")
    add_log(db, "export_xlsx", f"Экспорт Excel; поиск: {search or ''}")
    db.commit()
    wb = build_export_workbook(db, params, columns)
    stream = BytesIO(); wb.save(stream); stream.seek(0)
    return StreamingResponse(stream, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": "attachment; filename=products.xlsx"})


EXPORT_MAIN_COLUMNS = {
    "code": "Код",
    "article": "Артикул",
    "photo": "Фото",
    "name": "Наименование",
    "section": "Раздел",
    "product_type": "Вид товара",
    "manufacturer": "Производитель",
    "manager": "Менеджер",
    "marking_code": "Код маркировки",
    "material": "Материал",
    "certificate": "Сертификат",
    "barcodes": "Штрихкоды",
}
LEGACY_EXPORT_COLUMNS = ["code", "article", "name", "section", "quantity"]
EXPORT_LEADING_COLUMNS = ("photo", "code", "article", "name", "section")
EXPORT_FIXED_WIDTHS = {
    "name": 50,
    "section": 12,
    "manufacturer": 20,
    "manager": 12,
    "material": 12,
    "barcodes": 17,
}
EXPORT_VALUE_WIDTH_COLUMNS = {"code", "certificate", "product_type"}


def normalize_export_property_key(value: str | None) -> str:
    """Нормализует название свойства для устойчивого поиска значений при экспорте."""
    return "".join(character for character in (value or "").casefold() if character.isalnum())


def normalize_image_url(url: str) -> str:
    """Кодирует пробелы и кириллицу в путях изображений из XML."""
    parts = urlsplit(url.strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError("Некорректный URL изображения")
    return urlunsplit((
        parts.scheme,
        parts.netloc.encode("idna").decode("ascii"),
        quote(parts.path, safe="/%:@"),
        quote(parts.query, safe="=&%:@/?"),
        "",
    ))


def export_image_cache_path(url: str) -> Path:
    normalized_url = normalize_image_url(url)
    return Path(settings.upload_dir) / "export-image-cache" / f"{hashlib.sha256(normalized_url.encode()).hexdigest()}.jpg"


def download_export_image(url: str) -> BytesIO | None:
    """Возвращает миниатюру из кэша либо загружает и сохраняет её."""
    try:
        normalized_url = normalize_image_url(url)
        cache_path = export_image_cache_path(normalized_url)
        cache_dir = cache_path.parent
        if cache_path.exists():
            return BytesIO(cache_path.read_bytes())
        request = Request(normalized_url, headers={
            "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": "https://volgorost.ru/",
            "User-Agent": "Mozilla/5.0 (compatible; VRCatalog Excel Export)",
        })
        with urlopen(request, timeout=3) as response:
            content = response.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            return None
        source = BytesIO(content)
        with PillowImage.open(source) as image:
            image.thumbnail((100, 100))
            prepared = BytesIO()
            # JPEG значительно компактнее PNG для фотографий товаров. Это уменьшает
            # память при создании книги и итоговый размер выгрузки.
            image.convert("RGB").save(prepared, format="JPEG", quality=70, optimize=True)
            prepared.seek(0)
            cache_dir.mkdir(parents=True, exist_ok=True)
            temporary_cache_path = cache_path.with_suffix(".tmp")
            temporary_cache_path.write_bytes(prepared.getvalue())
            temporary_cache_path.replace(cache_path)
            return prepared
    except (OSError, ValueError, UnidentifiedImageError):
        return None


def download_export_images(
    urls: list[str],
    image_loader: Callable[[str], BytesIO | None],
    *,
    max_workers: int = 24,
    timeout: float = 15,
) -> dict[str, bytes]:
    """Параллельно загружает уникальные фото с заданными лимитами."""
    unique_urls = list(dict.fromkeys(urls))
    if not unique_urls:
        return {}
    executor = ThreadPoolExecutor(max_workers=min(max_workers, len(unique_urls)))
    futures = {executor.submit(image_loader, url): url for url in unique_urls}
    completed, pending = wait(futures, timeout=timeout)
    images: dict[str, bytes] = {}
    for future in completed:
        try:
            stream = future.result()
        except Exception:
            stream = None
        if stream:
            images[futures[future]] = stream.getvalue()
    for future in pending:
        future.cancel()
    executor.shutdown(wait=False, cancel_futures=True)
    return images


def current_rss_mb() -> float | str:
    """Возвращает текущий RSS процесса в Linux без дополнительных зависимостей."""
    try:
        status = Path("/proc/self/status").read_text()
        rss_kb = int(next(line.split()[1] for line in status.splitlines() if line.startswith("VmRSS:")))
        return round(rss_kb / 1024, 1)
    except (OSError, StopIteration, ValueError):
        return "н/д"


def write_export_workbook_streaming(
    db: Session,
    params: dict,
    columns: list[str] | None,
    path: str,
    job_id: str,
    total: int,
    filtered_ids=None,
) -> int:
    """Пишет большой XLSX на диск пакетами, не удерживая строки каталога в памяти."""
    selected_columns = columns or LEGACY_EXPORT_COLUMNS
    warehouse_names = {item.code: item.name for item in db.query(WarehouseSetting).all()}
    product_type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    selected_columns = [
        *(column for column in EXPORT_LEADING_COLUMNS if column in selected_columns),
        *(column for column in selected_columns if column not in EXPORT_LEADING_COLUMNS),
    ]
    headers = [
        EXPORT_MAIN_COLUMNS[column] if column in EXPORT_MAIN_COLUMNS
        else "Остаток" if column == "quantity"
        else column.removeprefix("price:") if column.startswith("price:")
        else warehouse_names[column.removeprefix("stock:")]
        for column in selected_columns
    ]
    needs_photos = "photo" in selected_columns
    needs_prices = any(column.startswith("price:") for column in selected_columns)
    needs_stocks = any(column.startswith("stock:") for column in selected_columns)
    needs_properties = any(column in {"manager", "marking_code"} for column in selected_columns)
    needs_barcodes = "barcodes" in selected_columns
    relation_options = []
    if needs_photos:
        relation_options.append(selectinload(Product.images))
    if needs_prices:
        relation_options.append(selectinload(Product.prices))
    if needs_stocks:
        relation_options.append(selectinload(Product.stocks))
    if needs_properties:
        relation_options.append(selectinload(Product.properties))
    if needs_barcodes:
        relation_options.append(selectinload(Product.barcodes))

    workbook = xlsxwriter.Workbook(path, {"constant_memory": True})
    worksheet = workbook.add_worksheet("Товары")
    border = 1
    header_format = workbook.add_format({
        "bold": True, "bg_color": "#E7E9EC", "border": border,
        "align": "center", "valign": "vcenter", "text_wrap": True,
    })
    text_format = workbook.add_format({"border": border, "valign": "vcenter", "text_wrap": True})
    text_alt_format = workbook.add_format({"border": border, "valign": "vcenter", "text_wrap": True, "bg_color": "#F7F7F7"})
    center_format = workbook.add_format({"border": border, "align": "center", "valign": "vcenter", "text_wrap": True})
    center_alt_format = workbook.add_format({"border": border, "align": "center", "valign": "vcenter", "text_wrap": True, "bg_color": "#F7F7F7"})
    price_format = workbook.add_format({"border": border, "align": "right", "valign": "vcenter", "num_format": "# ##0.00"})
    price_alt_format = workbook.add_format({"border": border, "align": "right", "valign": "vcenter", "num_format": "# ##0.00", "bg_color": "#F7F7F7"})
    number_format = workbook.add_format({"border": border, "align": "right", "valign": "vcenter", "num_format": "# ##0"})
    number_alt_format = workbook.add_format({"border": border, "align": "right", "valign": "vcenter", "num_format": "# ##0", "bg_color": "#F7F7F7"})
    column_widths = {
        "photo": 14, "code": 16, "article": 20, "name": 55, "section": 30,
        "product_type": 25, "manufacturer": 24, "manager": 20, "marking_code": 20,
        "material": 22, "certificate": 22, "barcodes": 22, "quantity": 14,
    }
    for column_index, header in enumerate(headers):
        column = selected_columns[column_index]
        width = 16 if column.startswith("price:") else 14 if column.startswith("stock:") else column_widths.get(column, 24)
        worksheet.write(0, column_index, header, header_format)
        worksheet.set_column(column_index, column_index, width)
    worksheet.set_row(0, 32)
    worksheet.freeze_panes(1, 0)
    photo_column = selected_columns.index("photo") if needs_photos else None
    row_index = 1
    processed = 0
    last_id = 0
    batch_number = 0
    if filtered_ids is None:
        filtered_ids = filtered_product_ids_subquery(db, params)
    try:
        while True:
            batch_ids = [
                product_id
                for product_id, in (
                    db.query(filtered_ids.c.product_id)
                    .filter(filtered_ids.c.product_id > last_id)
                    .order_by(filtered_ids.c.product_id)
                    .limit(EXPORT_PRODUCT_BATCH_SIZE)
                    .all()
                )
            ]
            if not batch_ids:
                break
            query = db.query(Product).filter(Product.id.in_(batch_ids))
            if relation_options:
                query = query.options(*relation_options)
            products = query.all()
            product_order = {product_id: index for index, product_id in enumerate(batch_ids)}
            products.sort(key=lambda product: product_order[product.id])
            batch_number += 1
            logger.info(
                "Экспорт %s: пакет=%s, min_id=%s, max_id=%s, batch_size=%s, processed=%s, total=%s, RSS=%s МБ",
                job_id, batch_number, batch_ids[0], batch_ids[-1], len(batch_ids), processed, total, current_rss_mb(),
            )
            if needs_photos:
                download_export_images(
                    [product.images[0].image_url for product in products if product.images],
                    download_export_image,
                    max_workers=32,
                    timeout=15,
                ).clear()
            for product in products:
                properties = {}
                for item in (product.properties if needs_properties else ()):
                    value = (item.value or "").strip()
                    for key in (item.name, item.property_code):
                        normalized_key = normalize_export_property_key(key)
                        if normalized_key and value:
                            properties.setdefault(normalized_key, value)
                prices = {item.price_type: item.price_value for item in product.prices} if needs_prices else {}
                stocks = {item.warehouse: item.quantity for item in product.stocks} if needs_stocks else {}
                values = {
                    "code": product.code, "article": product.article or "", "photo": "",
                    "name": product.name, "section": product.section or "",
                    "product_type": product_type_names.get(product.product_type, product.product_type or ""),
                    "manufacturer": product.manufacturer or "", "manager": product.manager or properties.get("менеджер", ""),
                    "marking_code": properties.get("кодмаркировки", "") or properties.get("markingcode", ""),
                    "material": product.material or "", "certificate": product.certificate or "",
                    "barcodes": ", ".join(item.value for item in product.barcodes) if needs_barcodes else "", "quantity": product.quantity,
                }
                for column_index, column in enumerate(selected_columns):
                    value = values.get(column, prices.get(column.removeprefix("price:"), 0) if column.startswith("price:") else stocks.get(column.removeprefix("stock:"), 0))
                    alternate = row_index % 2 == 0
                    if column.startswith("price:"):
                        cell_format = price_alt_format if alternate else price_format
                    elif column == "quantity" or column.startswith("stock:"):
                        cell_format = number_alt_format if alternate else number_format
                    elif column in {"photo", "code", "article"}:
                        cell_format = center_alt_format if alternate else center_format
                    else:
                        cell_format = text_alt_format if alternate else text_format
                    worksheet.write(row_index, column_index, value, cell_format)
                if needs_photos and product.images:
                    photo_url = product.images[0].image_url
                    try:
                        cache_path = export_image_cache_path(photo_url)
                        if cache_path.exists():
                            with PillowImage.open(cache_path) as thumbnail:
                                image_width, image_height = thumbnail.size
                            scale = min(1, 70 / max(image_width, image_height))
                            displayed_width = image_width * scale
                            displayed_height = image_height * scale
                            worksheet.set_row(row_index, 60)
                            worksheet.insert_image(row_index, photo_column, str(cache_path), {
                                "x_scale": scale, "y_scale": scale,
                                "x_offset": max(2, round((98 - displayed_width) / 2)),
                                "y_offset": max(2, round((80 - displayed_height) / 2)),
                                "object_position": 1,
                            })
                        else:
                            photo_format = center_alt_format if row_index % 2 == 0 else center_format
                            worksheet.write_url(row_index, photo_column, photo_url, photo_format, "Открыть фото")
                    except (OSError, ValueError, UnidentifiedImageError):
                        photo_format = center_alt_format if row_index % 2 == 0 else center_format
                        worksheet.write(row_index, photo_column, "Фото недоступно", photo_format)
                row_index += 1
            last_id = batch_ids[-1]
            processed += len(products)
            with export_jobs_lock:
                job = export_jobs.get(job_id)
                if job:
                    job.update(
                        processed=processed,
                        progress=round(processed * 100 / total) if total else 100,
                    )
            del products
            db.expire_all()
            gc.collect()
    finally:
        if row_index > 1 and selected_columns:
            worksheet.autofilter(0, 0, row_index - 1, len(selected_columns) - 1)
        workbook.close()
        del worksheet, workbook
        gc.collect()
    return processed


def build_export_workbook(
    db: Session,
    params: dict,
    columns: list[str] | None,
    image_loader: Callable[[str], BytesIO | None] = download_export_image,
    offset: int = 0,
    limit: int | None = None,
    apply_formatting: bool = True,
) -> Workbook:
    selected_columns = columns or LEGACY_EXPORT_COLUMNS
    warehouse_names = {item.code: item.name for item in db.query(WarehouseSetting).all()}
    product_type_names = {item.code: item.name for item in db.query(ProductTypeSetting).all()}
    allowed_columns = set(EXPORT_MAIN_COLUMNS) | {"quantity"}
    allowed_columns.update(f"price:{name}" for name in ("ЦенаОптовая", "ЦенаКорпоративная", "ЦенаРозничная"))
    allowed_columns.update(f"stock:{code}" for code in warehouse_names)
    unknown_columns = set(selected_columns) - allowed_columns
    if unknown_columns:
        raise HTTPException(422, f"Неизвестные колонки экспорта: {', '.join(sorted(unknown_columns))}")

    # Основные поля сохраняют одинаковый порядок независимо от порядка выбора пользователя.
    selected_columns = [
        *(column for column in EXPORT_LEADING_COLUMNS if column in selected_columns),
        *(column for column in selected_columns if column not in EXPORT_LEADING_COLUMNS),
    ]

    headers = []
    for column in selected_columns:
        if column in EXPORT_MAIN_COLUMNS:
            headers.append(EXPORT_MAIN_COLUMNS[column])
        elif column == "quantity":
            headers.append("Остаток")
        elif column.startswith("price:"):
            headers.append(column.removeprefix("price:"))
        else:
            headers.append(warehouse_names[column.removeprefix("stock:")])

    needs_prices = any(column.startswith("price:") for column in selected_columns)
    needs_stocks = any(column.startswith("stock:") for column in selected_columns)
    needs_properties = any(column in {"manager", "marking_code"} for column in selected_columns)
    needs_barcodes = "barcodes" in selected_columns
    relation_options = []
    if "photo" in selected_columns:
        relation_options.append(selectinload(Product.images))
    if needs_prices:
        relation_options.append(selectinload(Product.prices))
    if needs_stocks:
        relation_options.append(selectinload(Product.stocks))
    if needs_properties:
        relation_options.append(selectinload(Product.properties))
    if needs_barcodes:
        relation_options.append(selectinload(Product.barcodes))
    products_query = catalog_product_query(db, params, eager_load=False).distinct().order_by(Product.id)
    if relation_options:
        products_query = products_query.options(*relation_options)
    if offset:
        products_query = products_query.offset(offset)
    if limit is not None:
        products_query = products_query.limit(limit)
    products = products_query.all()
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    photo_column = selected_columns.index("photo") + 1 if "photo" in selected_columns else None
    if photo_column:
        worksheet.column_dimensions[get_column_letter(photo_column)].width = 16

    # Фото загружаются небольшими пакетами. Раньше все изображения каталога
    # одновременно хранились в памяти, из-за чего backend мог быть завершён OOM-killer.
    batch_size = 200 if photo_column and not apply_formatting else 100 if photo_column else max(1, len(products))
    embedded_photo_count = 0
    for batch_start in range(0, len(products), batch_size):
        product_batch = products[batch_start:batch_start + batch_size]
        remaining_photo_slots = max(0, MAX_EMBEDDED_EXPORT_IMAGES - embedded_photo_count)
        photo_products = [product for product in product_batch if product.images][:remaining_photo_slots]
        downloaded_images = download_export_images(
            [product.images[0].image_url for product in photo_products],
            image_loader,
            max_workers=64 if not apply_formatting else 24,
            timeout=30 if not apply_formatting else 15,
        ) if photo_column else {}
        for product in product_batch:
            photo_url = product.images[0].image_url if photo_column and product.images else ""
            image_content = downloaded_images.get(photo_url)
            properties: dict[str, str] = {}
            for item in (product.properties if needs_properties else ()):
                value = (item.value or "").strip()
                for key in (item.name, item.property_code):
                    normalized_key = normalize_export_property_key(key)
                    if normalized_key and value:
                        properties.setdefault(normalized_key, value)
            prices = {item.price_type: item.price_value for item in product.prices} if needs_prices else {}
            stocks = {item.warehouse: item.quantity for item in product.stocks} if needs_stocks else {}
            main_values = {
                "code": product.code,
                "article": product.article or "",
                "photo": "" if image_content or not photo_url else "Открыть фото",
                "name": product.name,
                "section": product.section or "",
                "product_type": product_type_names.get(product.product_type, product.product_type or ""),
                "manufacturer": product.manufacturer or "",
                "manager": product.manager or properties.get("менеджер", ""),
                "marking_code": properties.get("кодмаркировки", "") or properties.get("markingcode", ""),
                "material": product.material or "",
                "certificate": product.certificate or "",
                "barcodes": ", ".join(item.value for item in product.barcodes) if needs_barcodes else "",
                "quantity": product.quantity,
            }
            row = []
            for column in selected_columns:
                if column in main_values:
                    row.append(main_values[column])
                elif column.startswith("price:"):
                    row.append(prices.get(column.removeprefix("price:"), 0))
                else:
                    row.append(stocks.get(column.removeprefix("stock:"), 0))
            worksheet.append(row)
            if photo_column and photo_url and not image_content:
                photo_cell = worksheet.cell(row=worksheet.max_row, column=photo_column)
                photo_cell.hyperlink = photo_url
                photo_cell.style = "Hyperlink"
            if image_content:
                if embedded_photo_count < MAX_EMBEDDED_EXPORT_IMAGES:
                    try:
                        image = ExcelImage(BytesIO(image_content))
                        image.width = 100
                        image.height = 100
                        # Ячейка шириной 16 символов занимает около 117 px, а высотой 82,5 pt — 110 px.
                        # Небольшие смещения помещают фотографию по центру, а не у верхней левой границы.
                        image.anchor = OneCellAnchor(
                            _from=AnchorMarker(
                                col=photo_column - 1,
                                row=worksheet.max_row - 1,
                                colOff=pixels_to_EMU(8),
                                rowOff=pixels_to_EMU(5),
                            ),
                            ext=XDRPositiveSize2D(
                                cx=pixels_to_EMU(image.width),
                                cy=pixels_to_EMU(image.height),
                            ),
                        )
                        worksheet.add_image(image)
                        worksheet.row_dimensions[worksheet.max_row].height = 82.5
                        embedded_photo_count += 1
                    except (OSError, ValueError):
                        # Повреждённое или неподдерживаемое изображение не должно прерывать весь экспорт.
                        pass

    for column_index, column in enumerate(selected_columns, start=1):
        column_letter = get_column_letter(column_index)
        if column == "photo":
            continue
        if column in EXPORT_FIXED_WIDTHS:
            width = EXPORT_FIXED_WIDTHS[column]
        elif column in EXPORT_VALUE_WIDTH_COLUMNS and apply_formatting:
            value_lengths = (len(str(cell.value or "")) for cell in worksheet[column_letter][1:])
            width = max(len(headers[column_index - 1]), *value_lengths) + 2
        else:
            width = len(headers[column_index - 1]) + 2
        worksheet.column_dimensions[column_letter].width = width

        if column in EXPORT_FIXED_WIDTHS and apply_formatting:
            for cell in worksheet[column_letter]:
                alignment = copy(cell.alignment)
                alignment.wrap_text = True
                cell.alignment = alignment

    # Вертикальное выравнивание применяется ко всей таблице, включая заголовки,
    # обычные значения и ячейки с переносом строк.
    if apply_formatting:
        for row in worksheet.iter_rows():
            for cell in row:
                alignment = copy(cell.alignment)
                alignment.vertical = "center"
                cell.alignment = alignment
    return workbook
