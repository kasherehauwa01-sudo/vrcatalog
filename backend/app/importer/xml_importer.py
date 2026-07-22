import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from app.models.catalog import Analog, Barcode, ImportRun, Price, Product, ProductImage, ProductProperty, Stock

logger = logging.getLogger(__name__)
KNOWN_FIELDS = {"Код":"code","Название":"name","Наименование":"name","Артикул":"article","Раздел":"section","Количество":"quantity","Описание":"description","Производитель":"manufacturer","Бренд":"brand","Менеджер":"manager","Страна":"country","Материал":"material","Цвет":"color","Теги":"tags"}


def _text(node: ET.Element | None) -> str | None:
    return node.text.strip() if node is not None and node.text else None


def _children_by_names(product: ET.Element, names: Iterable[str]) -> list[ET.Element]:
    lowered = {n.lower() for n in names}
    return [child for child in product if child.tag.lower() in lowered]


def _float(value: str | None) -> float:
    try:
        return float((value or "0").replace(" ", "").replace(",", "."))
    except ValueError:
        return 0.0


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
            db.query(Product).delete()
            for item in products:
                try:
                    product = self._parse_product(item)
                    db.add(product)
                    imported += 1
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

    def _parse_product(self, item: ET.Element) -> Product:
        values = {field: _text(item.find(xml_name)) for xml_name, field in KNOWN_FIELDS.items()}
        code = values.get("code") or item.get("Код") or item.get("code")
        name = values.get("name") or item.get("Название") or item.get("name") or code
        if not code or not name:
            raise ValueError("У товара отсутствует код или название")
        product = Product(
            code=code,
            name=name,
            article=values.get("article"),
            section=values.get("section"),
            description=values.get("description"),
            quantity=_float(values.get("quantity")),
            manufacturer=values.get("manufacturer"),
            brand=values.get("brand"),
            manager=values.get("manager"),
            country=values.get("country"),
            material=values.get("material"),
            color=values.get("color"),
            tags=values.get("tags"),
        )
        for price_root in _children_by_names(item, ["Цены", "prices"]):
            for price in list(price_root):
                product.prices.append(Price(price_type=price.get("Тип") or price.get("type") or price.tag, value=_float(_text(price) or price.get("Значение") or price.get("value"))))
        for stock_root in _children_by_names(item, ["Склады", "Остатки", "stocks"]):
            for stock in list(stock_root):
                product.stocks.append(Stock(warehouse=stock.get("Название") or stock.get("name") or stock.tag, quantity=_float(_text(stock) or stock.get("Количество") or stock.get("quantity"))))
        for prop_root in _children_by_names(item, ["Свойства", "Характеристики", "properties"]):
            for prop in list(prop_root):
                name = prop.get("Название") or prop.get("name") or prop.tag
                value = _text(prop) or prop.get("Значение") or prop.get("value")
                product.properties.append(ProductProperty(property_code=prop.get("Код") or prop.get("code"), name=name, value=value))
        for image_root in _children_by_names(item, ["Изображения", "images"]):
            for image in list(image_root):
                url = _text(image) or image.get("url")
                if url:
                    product.images.append(ProductImage(url=url))
        for analog_root in _children_by_names(item, ["Аналоги", "analogs"]):
            for analog in list(analog_root):
                product.analogs.append(Analog(code=analog.get("Код") or analog.get("code") or _text(analog), name=analog.get("Название") or analog.get("name")))
        for barcode_root in _children_by_names(item, ["Штрихкоды", "barcodes"]):
            for barcode in list(barcode_root):
                value = _text(barcode) or barcode.get("value")
                if value:
                    product.barcodes.append(Barcode(value=value))
        search_bits = [product.name, product.code, product.article, product.description, product.brand, product.manufacturer, product.tags]
        search_bits.extend(b.value for b in product.barcodes)
        product.search_text = " ".join(filter(None, search_bits)).lower()
        return product
