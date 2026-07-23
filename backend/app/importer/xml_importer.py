import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.catalog import Analog, Barcode, ImportRun, Price, Product, ProductProperty, Stock

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


class XMLCatalogImporter:
    """Независимый сервис импорта: XML читается только здесь, API работает уже с БД."""

    def import_file(self, db: Session, path: Path, filename: str) -> ImportRun:
        run = ImportRun(filename=filename, status="running")
        db.add(run)
        db.flush()
        errors: list[str] = []
        imported = 0
        try:
            root = ET.parse(path).getroot()
            products = root.findall(".//Товар") or root.findall(".//product") or list(root)
            for item in products:
                try:
                    parsed_product = self._parse_product(item)
                    product = self._upsert_product(db, parsed_product)
                    db.add(product)
                    # Сразу отправляем товар в БД, чтобы следующий товар с тем же кодом обновлял его,
                    # а не создавал второй INSERT и не падал на unique constraint products.code.
                    db.flush()
                    imported += 1
                except SQLAlchemyError:
                    raise
                except Exception as exc:  # noqa: BLE001 - ошибки одной позиции не должны ронять весь импорт
                    logger.exception("Ошибка импорта товара")
                    errors.append(str(exc))
            run.status = "completed" if not errors else "completed_with_errors"
            run.imported_count = imported
            run.errors = "\n".join(errors) or None
            run.finished_at = datetime.utcnow()
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
            db.commit()
            raise
        return run


    def _upsert_product(self, db: Session, parsed_product: Product) -> Product:
        existing = db.query(Product).filter(Product.code == parsed_product.code).one_or_none()
        if existing is None:
            return parsed_product
        existing.name = parsed_product.name
        existing.article = parsed_product.article
        existing.section = parsed_product.section
        existing.description = parsed_product.description
        existing.quantity = parsed_product.quantity
        existing.manufacturer = parsed_product.manufacturer
        existing.brand = parsed_product.brand
        existing.manager = parsed_product.manager
        existing.country = parsed_product.country
        existing.material = parsed_product.material
        existing.color = parsed_product.color
        existing.certificate = parsed_product.certificate
        existing.tags = parsed_product.tags
        existing.search_text = parsed_product.search_text
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
        product = Product(code=code, name=name, section=values.get("section"), quantity=_float(values.get("quantity")))
        properties = self._parse_properties(item)
        for prop in properties:
            product.properties.append(ProductProperty(property_code=prop["code"], name=prop["name"], value=prop["value"]))
        self._apply_special_properties(product, properties)
        self._parse_prices(item, product)
        self._parse_stocks(item, product)
        self._parse_analogs(item, product)
        self._parse_barcodes(item, product, properties)
        search_bits = [product.name, product.code, product.article, product.description, product.brand, product.manufacturer, product.manager, product.tags, product.certificate, product.material, product.color]
        search_bits.extend(b.value for b in product.barcodes)
        search_bits.extend(p.value for p in product.properties if p.value)
        product.search_text = " ".join(filter(None, search_bits)).lower()
        return product

    def _parse_prices(self, item: ET.Element, product: Product) -> None:
        for price_root in _children_by_names(item, ["Цены", "prices"]):
            for price in list(price_root):
                raw_type = price.get("ТипЦены") or price.get("Тип") or price.get("type") or _tag_name(price)
                value = _text(price) or price.get("Значение") or price.get("value")
                product.prices.append(Price(price_type=_normalize_price_type(raw_type), value=_float(value)))

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
