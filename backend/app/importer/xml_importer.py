import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.services.logging import add_log
from app.services.notifications import add_notification

from app.models.catalog import Analog, Barcode, ImportRun, Price, Product, ProductImage, ProductProperty, Stock

IMAGE_BASE_URL = "https://volgorost.ru/upload/import_images/images/"

logger = logging.getLogger(__name__)
PRODUCT_FIELD_TAGS = {
    "code": ("Код", "code"),
    "name": ("Название", "name"),
    "section": ("Раздел", "section"),
    "quantity": ("Количество", "quantity"),
}
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


def _is_valid_xml_char(char: str) -> bool:
    code = ord(char)
    return code in {0x09, 0x0A, 0x0D} or 0x20 <= code <= 0xD7FF or 0xE000 <= code <= 0xFFFD or 0x10000 <= code <= 0x10FFFF


def _clean_xml_text(text: str) -> str:
    return "".join(char for char in text if _is_valid_xml_char(char))


def _parse_xml_root(path: Path) -> ET.Element:
    raw = path.read_bytes()
    parse_errors: list[Exception] = []
    try:
        return ET.fromstring(raw)
    except ET.ParseError as exc:
        parse_errors.append(exc)
    for encoding in ("windows-1251", "utf-8"):
        try:
            text = raw.decode(encoding)
        except UnicodeDecodeError as exc:
            parse_errors.append(exc)
            continue
        try:
            return ET.fromstring(_clean_xml_text(text))
        except ET.ParseError as exc:
            parse_errors.append(exc)
    raise parse_errors[-1]


def _product_code(item: ET.Element) -> str | None:
    code = _child_text(item, "Код") or item.get("Код") or item.get("code")
    return code.strip() if code and code.strip() else None


def _product_nodes(root: ET.Element) -> list[ET.Element]:
    products = root.findall(".//Товар") or root.findall(".//product")
    if products:
        return products
    if _tag_name(root).lower() in {"товар", "product"}:
        return [root]
    return []


def xml_product_count(path: Path) -> int:
    return len(_product_nodes(_parse_xml_root(path)))


class XMLCatalogImporter:
    """Независимый сервис импорта: XML читается только здесь, API работает уже с БД."""

    def import_file(self, db: Session, path: Path, filename: str) -> ImportRun:
        run = ImportRun(filename=filename, status="running")
        db.add(run)
        db.flush()
        imported = 0
        created = 0
        updated = 0
        try:
            add_log(db, "xml_import_start", f"Начато чтение XML: {filename}")
            root = _parse_xml_root(path)
            products = _product_nodes(root)
            product_codes = [code for code in (_product_code(item) for item in products) if code]
            existing_products = self._load_existing_products(db, product_codes)
            for item in products:
                try:
                    parsed_product = self._parse_product(item)
                    was_existing = parsed_product.code in existing_products
                    product = self._persist_product(db, parsed_product, existing_products)
                    # Обновляем карту кодов, чтобы повторный товар с тем же кодом в этом же XML
                    # обновлял строку, а не создавал второй INSERT.
                    existing_products[product.code] = product
                    imported += 1
                    if was_existing:
                        if getattr(product, "_import_changed", False):
                            updated += 1
                    else:
                        created += 1
                except SQLAlchemyError:
                    raise
                except Exception as exc:  # noqa: BLE001 - добавляем контекст и откатываем весь импорт
                    code = _product_code(item) or "неизвестен"
                    raise ValueError(f"Ошибка обработки товара с кодом {code}: {exc}") from exc
            run.status = "completed"
            run.imported_count = imported
            run.created_count = created
            run.updated_count = updated
            run.errors = None
            run.finished_at = datetime.utcnow()
            add_log(db, "xml_import_finish", f"Импорт XML завершен: {filename}; товаров: {imported}; новых: {created}; обновлено: {updated}")
            add_notification(db, "import_success", "Импорт завершен", f"Импорт завершен. Загружено товаров: {imported}, обновлено: {updated}")
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
            products = (
                db.query(Product)
                .options(
                    selectinload(Product.prices),
                    selectinload(Product.stocks),
                    selectinload(Product.properties),
                    selectinload(Product.analogs),
                    selectinload(Product.barcodes),
                    selectinload(Product.images),
                )
                .filter(Product.code.in_(chunk))
                .all()
            )
            for product in products:
                result[product.code] = product
        return result

    def _product_scalar_values(self, product: Product) -> dict[str, object]:
        """Готовит только колонки products без связанных цен, складов и свойств."""
        return {
            "code": product.code,
            "name": product.name,
            "article": product.article,
            "section": product.section,
            "product_type": product.product_type,
            "description": product.description,
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
        """Создает новый товар или применяет только реальные изменения к существующему."""
        existing = existing_products.get(parsed_product.code)
        if existing is None:
            loaded_at = datetime.utcnow()
            parsed_product.created_at = loaded_at
            parsed_product.updated_at = loaded_at
            db.add(parsed_product)
            db.flush()
            parsed_product._import_changed = True
            add_log(db, "xml_product_created", f"Создан новый товар:\n{parsed_product.code}")
            return parsed_product

        changed = False
        changed_fields = self._sync_product_scalars(existing, parsed_product)
        if changed_fields:
            changed = True
            add_log(db, "xml_product_fields_updated", f"Обновлены поля:\n{', '.join(changed_fields)}")
        if self._sync_prices(db, existing, parsed_product):
            changed = True
        if self._sync_stocks(db, existing, parsed_product):
            changed = True
        if self._sync_relation_list(
            existing.properties,
            parsed_product.properties,
            lambda item: (item.property_code, item.name),
            lambda item: {"property_code": item.property_code, "name": item.name, "value": item.value},
            ProductProperty,
        ):
            changed = True
            add_log(db, "xml_product_properties_updated", f"Обновлены свойства:\n{existing.code}")
        if self._sync_relation_list(
            existing.analogs,
            parsed_product.analogs,
            lambda item: item.code or item.name,
            lambda item: {"code": item.code, "name": item.name},
            Analog,
        ):
            changed = True
            add_log(db, "xml_product_analogs_updated", f"Обновлены аналоги:\n{existing.code}")
        if self._sync_relation_list(
            existing.barcodes,
            parsed_product.barcodes,
            lambda item: item.value,
            lambda item: {"value": item.value},
            Barcode,
        ):
            changed = True
            add_log(db, "xml_product_barcodes_updated", f"Обновлены штрихкоды:\n{existing.code}")
        if self._sync_images(db, existing, parsed_product):
            changed = True
            add_log(db, "xml_product_images_updated", "Обновлены изображения")
        if not changed:
            add_log(db, "xml_product_no_changes", "Изменений нет.")
        else:
            # Связанные цены, остатки и изображения не вызывают onupdate у products,
            # поэтому фиксируем время любого фактического изменения явно.
            existing.updated_at = datetime.utcnow()
        existing._import_changed = changed
        return existing

    def _sync_product_scalars(self, existing: Product, parsed_product: Product) -> list[str]:
        changed_fields: list[str] = []
        labels = {
            "name": "Название",
            "article": "Артикул",
            "section": "Раздел",
            "product_type": "Вид товара",
            "description": "Описание",
            "quantity": "Количество",
            "manufacturer": "Производитель",
            "brand": "Бренд",
            "manager": "Менеджер",
            "country": "Страна",
            "material": "Материал",
            "color": "Цвет",
            "certificate": "Сертификат",
            "tags": "Теги",
            "search_text": "Поиск",
        }
        for field, value in self._product_scalar_values(parsed_product).items():
            if field == "code":
                continue
            if getattr(existing, field) != value:
                setattr(existing, field, value)
                changed_fields.append(labels.get(field, field))
        return changed_fields

    def _sync_prices(self, db: Session, existing: Product, parsed_product: Product) -> bool:
        changed = False
        current = {price.price_type: price for price in existing.prices}
        incoming = {price.price_type: price for price in parsed_product.prices}
        for price_type, parsed_price in incoming.items():
            price = current.get(price_type)
            if price is None:
                existing.prices.append(Price(price_type=parsed_price.price_type, price_value=parsed_price.price_value))
                changed = True
            elif price.price_value != parsed_price.price_value:
                price.price_value = parsed_price.price_value
                changed = True
        for price_type, price in list(current.items()):
            if price_type not in incoming:
                existing.prices.remove(price)
                changed = True
        if changed:
            add_log(db, "xml_product_prices_updated", f"Обновлена цена:\n{', '.join(incoming.keys())}")
        return changed

    def _sync_stocks(self, db: Session, existing: Product, parsed_product: Product) -> bool:
        changed = False
        current = {stock.warehouse: stock for stock in existing.stocks}
        incoming = {stock.warehouse: stock for stock in parsed_product.stocks}
        changed_warehouses: list[str] = []
        for warehouse, parsed_stock in incoming.items():
            stock = current.get(warehouse)
            if stock is None:
                existing.stocks.append(Stock(warehouse=parsed_stock.warehouse, quantity=parsed_stock.quantity))
                changed_warehouses.append(warehouse)
                changed = True
            elif stock.quantity != parsed_stock.quantity:
                stock.quantity = parsed_stock.quantity
                changed_warehouses.append(warehouse)
                changed = True
        for warehouse, stock in list(current.items()):
            if warehouse not in incoming:
                existing.stocks.remove(stock)
                changed_warehouses.append(warehouse)
                changed = True
        if changed:
            add_log(db, "xml_product_stocks_updated", f"Обновлены остатки:\n{', '.join(changed_warehouses)}")
        return changed

    def _sync_relation_list(self, current_items, incoming_items, key_fn, values_fn, model) -> bool:
        current = {key_fn(item): item for item in current_items}
        incoming = {key_fn(item): item for item in incoming_items}
        changed = False
        for key, parsed_item in incoming.items():
            item = current.get(key)
            values = values_fn(parsed_item)
            if item is None:
                current_items.append(model(**values))
                changed = True
                continue
            for field, value in values.items():
                if getattr(item, field) != value:
                    setattr(item, field, value)
                    changed = True
        for key, item in list(current.items()):
            if key not in incoming:
                current_items.remove(item)
                changed = True
        return changed

    def _sync_images(self, db: Session, existing: Product, parsed_product: Product) -> bool:
        current = [(image.image_order, image.image_url) for image in existing.images]
        incoming = [(image.image_order, image.image_url) for image in parsed_product.images]
        if current == incoming:
            return False
        existing.images.clear()
        db.flush()
        existing.images.extend(
            ProductImage(image_order=image.image_order, image_url=image.image_url)
            for image in parsed_product.images
        )
        return True

    def _product_field(self, item: ET.Element, field: str) -> str | None:
        """Читает поле товара только из XML-тегов/атрибутов, которые соответствуют этому полю."""
        names = PRODUCT_FIELD_TAGS[field]
        value = _child_text(item, *names)
        if value is None:
            value = next((item.get(name) for name in names if item.get(name)), None)
        return value.strip() if value and value.strip() else None

    def _parse_product(self, item: ET.Element) -> Product:
        code = self._product_field(item, "code")
        name = self._product_field(item, "name")
        section = self._product_field(item, "section")
        quantity = self._product_field(item, "quantity")
        if not code or not name:
            raise ValueError("У товара отсутствует код или название")
        product = Product(code=code, name=name, section=section, quantity=_float(quantity))
        product.images = self._parse_images(item)
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

    def _image_url(self, raw_path: str) -> str:
        """Превращает путь изображения из XML в полный внешний URL."""
        normalized_path = raw_path.strip().lstrip("/")
        if normalized_path.lower().startswith("images/"):
            normalized_path = normalized_path[len("images/"):]
        return f"{IMAGE_BASE_URL}{normalized_path}"

    def _parse_images(self, item: ET.Element) -> list[ProductImage]:
        """Сохраняет все изображения товара из XML с исходным порядком."""
        images: list[ProductImage] = []
        for images_root in _children_by_names(item, ["Изображения", "images"]):
            for image in list(images_root):
                raw_path = _text(image) or image.get("path") or image.get("url")
                if not raw_path:
                    continue
                images.append(ProductImage(image_order=len(images) + 1, image_url=self._image_url(raw_path)))
        return images

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
            if name in {"Наименование", "Наименование товара", "Название товара"} and value != product.code:
                product.name = value
            if name == "Производитель": product.manufacturer = value
            if name == "Менеджер": product.manager = value
            if name == "Сертификат": product.certificate = value
            if name == "Описание": product.description = value
            if name in {"Вид товара", "ВидТовара"}:
                product.product_type = value
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
