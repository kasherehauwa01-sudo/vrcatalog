from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session, selectinload

from app.models.catalog import AnalogSelectionSetting, Product, ProductProperty
from app.services.catalog import EXCLUDED_PROPERTY_FILTERS


DEFAULT_PRIMARY_PROPERTIES = [
    "Коллекция", "Материал", "Цвет", "Вид", "Высота", "Диаметр",
    "Для индукционных плит", "Литраж", "Материал основной", "Набор",
    "Наличие крышки", "Наличие рисунка", "Напиток", "Наполнитель",
    "Покрытие", "Размер", "Форм фактор", "Форма", "Цифра",
]
BUILTIN_CHARACTERISTICS = {
    "Материал": "material", "Цвет": "color", "Производитель": "manufacturer",
    "Бренд": "brand", "Страна": "country", "Менеджер": "manager",
    "Вид товара": "product_type",
}
EXCLUDED_CHARACTERISTICS = {_normalized_name.casefold() for _normalized_name in EXCLUDED_PROPERTY_FILTERS}


def _normalized(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).casefold()


def get_analog_settings(db: Session) -> AnalogSelectionSetting:
    setting = db.query(AnalogSelectionSetting).order_by(AnalogSelectionSetting.id).first()
    if setting:
        return setting
    setting = AnalogSelectionSetting(
        primary_properties_json=json.dumps(DEFAULT_PRIMARY_PROPERTIES, ensure_ascii=False),
        minimum_similarity=60,
        maximum_analogs=10,
    )
    db.add(setting)
    db.commit()
    db.refresh(setting)
    return setting


def primary_properties(setting: AnalogSelectionSetting) -> list[str]:
    try:
        values = json.loads(setting.primary_properties_json)
        return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    except (TypeError, ValueError):
        return DEFAULT_PRIMARY_PROPERTIES.copy()


def available_characteristics(db: Session) -> list[str]:
    property_names = [
        name.strip() for name, in db.query(ProductProperty.name)
        .filter(ProductProperty.name.isnot(None)).distinct().order_by(ProductProperty.name).all()
        if name and name.strip() and name.strip().casefold() not in EXCLUDED_CHARACTERISTICS
    ]
    return sorted(set(BUILTIN_CHARACTERISTICS) | set(property_names), key=str.casefold)


def _characteristics(product: Product) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for label, field in BUILTIN_CHARACTERISTICS.items():
        value = getattr(product, field)
        if _normalized(value):
            result[_normalized(label)] = (label, _normalized(value))
    for prop in product.properties:
        name = " ".join(prop.name.split())
        value = _normalized(prop.value)
        if name and value and name.casefold() not in EXCLUDED_CHARACTERISTICS:
            result[_normalized(name)] = (name, value)
    return result


@dataclass
class ScoredAnalog:
    product: Product
    similarity: int
    matched: list[str]
    unmatched: list[str]


def _score(source: Product, candidate: Product, primary: list[str]) -> ScoredAnalog:
    source_values = _characteristics(source)
    candidate_values = _characteristics(candidate)
    priorities = {_normalized(name): index for index, name in enumerate(primary)}
    total_weight = matched_weight = 0
    matched: list[str] = []
    unmatched: list[str] = []
    for key, (display_name, source_value) in source_values.items():
        candidate_value = candidate_values.get(key)
        # Отсутствующее значение у любой из карточек не является несовпадением:
        # характеристика полностью исключается из числителя и знаменателя.
        if candidate_value is None:
            continue
        # Основные признаки имеют вес от 2N до 2 по приоритету, второстепенные — 1.
        weight = max(2, (len(priorities) - priorities[key]) * 2) if key in priorities else 1
        total_weight += weight
        if candidate_value[1] == source_value:
            matched_weight += weight
            matched.append(display_name)
        else:
            unmatched.append(display_name)
    similarity = round(matched_weight * 100 / total_weight) if total_weight else 0
    return ScoredAnalog(candidate, similarity, matched, unmatched)


def find_product_analogs(db: Session, product_id: int) -> list[ScoredAnalog] | None:
    """Считает аналоги динамически, ограничивая выборку индексированной категорией."""
    source = db.query(Product).options(selectinload(Product.properties)).filter(Product.id == product_id).first()
    if source is None:
        return None
    if not source.section or not _characteristics(source):
        return []
    setting = get_analog_settings(db)
    candidates = (
        db.query(Product)
        .options(selectinload(Product.properties))
        .filter(Product.section == source.section, Product.id != source.id)
        .all()
    )
    primary = primary_properties(setting)
    scored = [_score(source, candidate, primary) for candidate in candidates]
    eligible = [item for item in scored if item.similarity >= setting.minimum_similarity]
    same_type = [item for item in eligible if source.product_type and item.product.product_type == source.product_type]
    other_type = [
        item for item in eligible
        if not source.product_type or item.product.product_type != source.product_type
    ]
    key = lambda item: (-item.similarity, item.product.id)
    selected = (sorted(same_type, key=key) + sorted(other_type, key=key))[:setting.maximum_analogs]
    if not selected:
        return []
    display_products = (
        db.query(Product)
        .options(selectinload(Product.prices), selectinload(Product.images))
        .filter(Product.id.in_([item.product.id for item in selected]))
        .all()
    )
    display_by_id = {product.id: product for product in display_products}
    for item in selected:
        item.product = display_by_id[item.product.id]
    return selected
