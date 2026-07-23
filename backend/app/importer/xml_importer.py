import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.services.logging import add_log
from app.services.notifications import add_notification

from app.models.catalog import Analog, Barcode, ImportRun, Price, Product, ProductProperty, Stock

IMAGE_BASE_URL = "https://volgorost.ru/upload/import_images/images/"

logger = logging.getLogger(__name__)
KNOWN_FIELDS = {"Код":"code","Название":"name","Наименование":"name","Раздел":"section","Количество":"quantity"}
PRICE_NAMES = {
    "ЦенаОптовая": "Оптовая",
    "ЦенаКорпоративная": "Корпоративная",
    "ЦенаРозничная": "Розничная",
    "ЦенаПредыдущаяОптовая": "Предыдущая оптовая",
    "ЦенаПредыдущаяКорпоративная": "Предыдущая корпоративная",
    "ЦенаПредыдущаяРозничная": "Предыдущая розничная",
}


def _tag_name(node: ET.Element) -> str:
    return node.tag.rsplit("}", 1)[-1]


def _text(node: ET.Element | None) -> str | None:
    return node.text.strip() if node is not None and node.text and node.text.strip() else None


def _child_text(node: ET.Element, *names: str) -> str | None:
    wanted = {name.lower() for name in names}
    for child in node:
        if _tag_name(child).lower() in wanted:
            return _text(child)
    return None


def _children_by_names(product: ET.Element, names: Iterable[str]) -> list[ET.Element]:
    lowered = {n.lower() for n in names}
    return [child for child in product if _tag_name(child).lower() in lowered]


def _float(value: str | None) -> float:
    try:
        return float((value or "0").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


def _normalize_price_type(raw: str) -> str:
    return PRICE_NAMES.get(raw, raw.replace("Цена", "", 1) or raw)


def _parse_xml_root(path: Path) -> ET.Element:
    raw = path.read_bytes()
    try:
        return ET.fromstring(raw)
    except ET.ParseError:
        text = raw.decode("windows-1251")
        return ET.fromstring(text.encode("utf-8"))


def _product_code(item: ET.Element) -> str | None:
    code = _child_text(item, "Код") or item.get("Код") or item.get("code")
    return code.strip() if code and code.strip() else None


class XMLCatalogImporter:
    """Независимый сервис импорта: XML читается только здесь, API работает уже с БД."""

    def import_file(self, db: Session, path: Path, filename: str) -> ImportRun:
        run = ImportRun(filename=filename, status="running")
        db.add(run)
        db.flush()
        errors: list[str] = []
        imported = 0
        try:
            add_log(db, "xml_import_start", f"Начато чтение XML: {filename}")
            root = _parse_xml_root(path)
            products = root.findall(".//Товар") or root.findall(".//product") or list(root)
            product_codes = [code for code in (_product_code(item) for item in products) if code]
            existing_products = self._load_existing_products(db, product_codes)
            for item in products:
                try:
                    parsed_product = self._parse_product(item)
                    product = self._persist_product(db, parsed_product, existing_products)
                    # Обновляем карту кодов, чтобы повторный товар с тем же кодом в этом же XML
                    # обновлял строку, а не создавал второй INSERT.
                    existing_products[product.code] = product
                    imported += 1
                except SQLAlchemyError:
                    raise
                except Exception as exc:  # noqa: BLE001 - ошибки одной позиции не должны ронять весь импорт
                    logger.exception("Ошибка импорта товара")
                    errors.append(str(exc))
                    add_notification(db, "import_error", "Ошибка обработки товара XML", f"Файл:\n{filename}\n\nПричина:\n{exc}")
            run.status = "completed" if not errors else "completed_with_errors"
            run.imported_count = imported
            run.errors = "\n".join(errors) if errors else None
            run.finished_at = datetime.utcnow()
            add_log(db, "xml_import_finish", f"Импорт XML завершен: {filename}; товаров: {imported}; ошибок: {len(errors)}")
            # Храним последние 10 загрузок как основу версионирования и отката.
            old_runs = db.query(ImportRun).order_by(ImportRun.created_at.desc()).offset(10).all()
            for old in old_runs:
                db.delete(old)
            db.commit()
        except Exception as exc:
            db.rollback()
            run.status = "failed"
            run.errors = str(exc)
            run.finished_at = datetime.utcnow()
            db.add(run)
            add_log(db, "xml_import_error", f"Ошибка импорта XML {filename}: {exc}", "error")
            add_notification(db, "import_error", "Ошибка загрузки XML", f"Файл:\n{filename}\n\nПричина:\n{exc}")
            db.commit()
            raise
        return run


    def _load_existing_products(self, db: Session, codes: list[str]) -> dict[str, Product]:
        """Заранее загружает товары по кодам из XML, чтобы обновлять их без повторных INSERT."""
        if not codes:
            return {}
        unique_codes = list(dict.fromkeys(codes))
        result: dict[str, Product] = {}
        chunk_size = 1000
        for index in range(0, len(unique_codes), chunk_size):
            chunk = unique_codes[index:index + chunk_size]
            for product in db.query(Product).filter(Product.code.in_(chunk)).all():
                result[product.code] = product
        return result

    def _product_scalar_values(self, product: Product) -> dict[str, object]:
        """Готовит только колонки products без связанных цен, складов и свойств."""
        return {
            "code": product.code,
            "name": product.name,
            "article": product.article,
            "section": product.section,
            "description": product.description,
            "image_url": product.image_url,
            "quantity": product.quantity,
            "manufacturer": product.manufacturer,
            "brand": product.brand,
            "manager": product.manager,
            "country": product.country,
            "material": product.material,
            "color": product.color,
            "certificate": product.certificate,
            "tags": product.tags,
            "search_text": product.search_text,
        }

    def _persist_product(self, db: Session, parsed_product: Product, existing_products: dict[str, Product]) -> Product:
        """Атомарный upsert товара по code: БД сама решает INSERT или UPDATE."""
        dialect = db.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as dialect_insert
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as dialect_insert
        else:
            return self._persist_product_fallback(db, parsed_product, existing_products)

        values = self._product_scalar_values(parsed_product)
        update_values = {key: value for key, value in values.items() if key != "code"}
        stmt = (
            dialect_insert(Product.__table__)
            .values(**values)
            .on_conflict_do_update(index_elements=["code"], set_=update_values)
            .returning(Product.__table__.c.id)
        )
        product_id = db.execute(stmt).scalar_one()
        existing = db.get(Product, product_id)
        if existing is None:
            raise ValueError(f"Не удалось получить товар с id {product_id} после upsert")
        self._copy_product_scalars(existing, parsed_product)
        return self._copy_product_relations(existing, parsed_product)

    def _persist_product_fallback(self, db: Session, parsed_product: Product, existing_products: dict[str, Product]) -> Product:
        existing = existing_products.get(parsed_product.code)
        if existing is None:
            existing = db.query(Product).filter(Product.code == parsed_product.code).one_or_none()
        if existing is None:
            db.add(parsed_product)
            db.flush()
            return parsed_product
        self._copy_product_scalars(existing, parsed_product)
        return self._copy_product_relations(existing, parsed_product)

    def _copy_product_scalars(self, existing: Product, parsed_product: Product) -> Product:
        for key, value in self._product_scalar_values(parsed_product).items():
            setattr(existing, key, value)
        return existing

    def _copy_product_relations(self, existing: Product, parsed_product: Product) -> Product:
        existing.prices.clear()
        existing.stocks.clear()
        existing.properties.clear()
        existing.analogs.clear()
        existing.barcodes.clear()
        existing.prices.extend(parsed_product.prices)
        existing.stocks.extend(parsed_product.stocks)
        existing.properties.extend(parsed_product.properties)
        existing.analogs.extend(parsed_product.analogs)
        existing.barcodes.extend(parsed_product.barcodes)
        return existing

    def _parse_product(self, item: ET.Element) -> Product:
        values = {field: _child_text(item, xml_name) for xml_name, field in KNOWN_FIELDS.items()}
        code = values.get("code") or item.get("Код") or item.get("code")
        code = code.strip() if code else None
        name = values.get("name") or item.get("Название") or item.get("name") or code
        name = name.strip() if name else None
        if not code or not name:
            raise ValueError("У товара отсутствует код или название")
        product = Product(code=code, name=name, section=values.get("section"), quantity=_float(values.get("quantity")), image_url=self._parse_image_url(item))
        properties = self._parse_properties(item)
        for prop in properties:
            product.properties.append(ProductProperty(property_code=prop["code"], name=prop["name"], value=prop["value"]))
        self._apply_special_properties(product, properties)
        self._parse_prices(item, product)
        self._parse_stocks(item, product)
        self._parse_analogs(item, product)
        self._parse_barcodes(item, product, properties)
        # Пересобираем поиск после применения специальных свойств.
        search_bits = [product.name, product.code, product.article, product.description, product.brand, product.manufacturer, product.manager, product.tags, product.certificate, product.material, product.color]
        search_bits.extend(b.value for b in product.barcodes)
        search_bits.extend(p.value for p in product.properties if p.value)
        product.search_text = " ".join(filter(None, search_bits)).lower()
        return product

    def _parse_image_url(self, item: ET.Element) -> str | None:
        """Берет первое изображение из XML и превращает /images/... в полный внешний URL."""
        for images_root in _children_by_names(item, ["Изображения", "images"]):
            for image in list(images_root):
                raw_path = _text(image) or image.get("path") or image.get("url")
                if not raw_path:
                    continue
                normalized_path = raw_path.strip().lstrip("/")
                if normalized_path.lower().startswith("images/"):
                    normalized_path = normalized_path[len("images/"):]
                return f"{IMAGE_BASE_URL}{normalized_path}"
        return None

    def _parse_prices(self, item: ET.Element, product: Product) -> None:
        price_nodes = [child for child in item if _tag_name(child).lower() in {"цена", "price"}]
        for price_root in _children_by_names(item, ["Цены", "prices"]):
            price_nodes.extend(list(price_root))
        seen: set[tuple[str, float]] = set()
        for price in price_nodes:
            raw_type = price.get("ТипЦены") or price.get("Тип") or price.get("type") or _tag_name(price)
            value = _text(price) or price.get("Значение") or price.get("value")
            price_type = _normalize_price_type(raw_type)
            price_value = _float(value)
            key = (price_type, price_value)
            if key not in seen:
                product.prices.append(Price(price_type=raw_type, price_value=price_value))
                seen.add(key)

    def _parse_stocks(self, item: ET.Element, product: Product) -> None:
        for stock_root in _children_by_names(item, ["Склады", "Остатки", "stocks"]):
            for stock in list(stock_root):
                warehouse = _child_text(stock, "КодСклада") or stock.get("КодСклада") or stock.get("Название") or stock.get("name") or _tag_name(stock)
                quantity = _child_text(stock, "Количество") or _text(stock) or stock.get("Количество") or stock.get("quantity")
                product.stocks.append(Stock(warehouse=warehouse, quantity=_float(quantity)))

    def _parse_properties(self, item: ET.Element) -> list[dict[str, str | None]]:
        result: list[dict[str, str | None]] = []
        for prop_root in _children_by_names(item, ["Свойства", "Характеристики", "properties"]):
            for prop in list(prop_root):
                code = _child_text(prop, "Код") or prop.get("Код") or prop.get("code")
                name = _child_text(prop, "Название", "Наименование") or prop.get("Название") or prop.get("name") or _tag_name(prop)
                value = _child_text(prop, "Значение") or prop.get("Значение") or prop.get("value") or _text(prop)
                if name or value or code:
                    result.append({"code": code, "name": name or code or _tag_name(prop), "value": value})
        return result

    def _apply_special_properties(self, product: Product, properties: list[dict[str, str | None]]) -> None:
        for prop in properties:
            code = (prop["code"] or "").strip()
            name = (prop["name"] or "").strip()
            value = prop["value"]
            if not value:
                continue
            if name == "Артикул": product.article = value
            if name == "Производитель": product.manufacturer = value
            if name == "Менеджер": product.manager = value
            if name == "Сертификат": product.certificate = value
            if name == "Описание": product.description = value
            if name == "Тег": product.tags = value if not product.tags else f"{product.tags}, {value}"
            if name == "Страна": product.country = value
            if code == "PROP_BREND" or name == "Бренд": product.brand = value
            if code == "PROP_MATERIAL" or name in {"Материал", "Материал основной"}: product.material = value
            if code == "PROP_COLOR" or name == "Цвет": product.color = value

    def _parse_analogs(self, item: ET.Element, product: Product) -> None:
        for analog_root in _children_by_names(item, ["Аналоги", "analogs"]):
            for analog in list(analog_root):
                product.analogs.append(Analog(code=_child_text(analog, "Код") or analog.get("Код") or analog.get("code") or _text(analog), name=_child_text(analog, "Название") or analog.get("Название") or analog.get("name")))

    def _parse_barcodes(self, item: ET.Element, product: Product, properties: list[dict[str, str | None]]) -> None:
        values: list[str] = []
        values.extend(prop["value"] or "" for prop in properties if prop["name"] == "Штрихкод")
        for barcode_root in _children_by_names(item, ["Штрихкоды", "barcodes"]):
            for barcode in list(barcode_root):
                values.append(_text(barcode) or barcode.get("value") or "")
        for raw in values:
            for value in [part.strip() for part in raw.split(",") if part.strip()]:
                if value not in [b.value for b in product.barcodes]:
                    product.barcodes.append(Barcode(value=value))
