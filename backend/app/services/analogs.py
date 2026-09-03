from __future__ import annotations

import json
import re
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


def _display_value(value: object) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _first_name_word(product: Product) -> str:
    """Возвращает первое слово наименования без учёта регистра и лишних пробелов."""
    normalized = _normalized(product.name)
    return normalized.split(maxsplit=1)[0] if normalized else ""


def _alphabetical_name(product: Product) -> tuple[str, str]:
    """Возвращает стабильный ключ русской сортировки, размещая «ё» рядом с «е»."""
    normalized = _normalized(product.name)
    return normalized.replace("ё", "е"), normalized


def _name_similarity(source: Product, candidate: Product) -> float:
    """Сравнивает слова и числовые обозначения в наименованиях."""
    pattern = r"\d+(?:[.,]\d+)?[a-zа-яё]*|[a-zа-яё]+"
    source_tokens = set(re.findall(pattern, _normalized(source.name)))
    candidate_tokens = set(re.findall(pattern, _normalized(candidate.name)))
    union = source_tokens | candidate_tokens
    if not union:
        return 0

    # Объём, размер и другие числовые обозначения помогают отличить, например,
    # «Таз 15л» от «Таз 11л», поэтому для них используется повышенный вес.
    weight = lambda token: 5 if token[0].isdigit() else 1
    return sum(weight(token) for token in source_tokens & candidate_tokens) / sum(
        weight(token) for token in union
    )


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


def _characteristics(product: Product) -> dict[str, tuple[str, str, str]]:
    result: dict[str, tuple[str, str, str]] = {}
    for label, field in BUILTIN_CHARACTERISTICS.items():
        value = getattr(product, field)
        if _normalized(value):
            result[_normalized(label)] = (label, _normalized(value), _display_value(value))
    for prop in product.properties:
        name = " ".join(prop.name.split())
        value = _normalized(prop.value)
        if name and value and name.casefold() not in EXCLUDED_CHARACTERISTICS:
            result[_normalized(name)] = (name, value, _display_value(prop.value))
    return result


@dataclass
class ScoredAnalog:
    product: Product
    similarity: int
    matched: list[dict[str, str]]
    unmatched: list[dict[str, str]]


def _score(source: Product, candidate: Product, primary: list[str]) -> ScoredAnalog:
    source_values = _characteristics(source)
    candidate_values = _characteristics(candidate)
    priorities = {_normalized(name): index for index, name in enumerate(primary)}
    total_weight = matched_weight = 0
    matched: list[dict[str, str]] = []
    unmatched: list[dict[str, str]] = []
    for key, (display_name, source_value, source_display_value) in source_values.items():
        # В расчёте участвуют только характеристики, явно выбранные основными.
        # Остальные фильтры не влияют ни на процент, ни на объяснение результата.
        if key not in priorities:
            continue
        candidate_value = candidate_values.get(key)
        # Отсутствующее значение у любой из карточек не является несовпадением:
        # характеристика полностью исключается из числителя и знаменателя.
        if candidate_value is None:
            continue
        # Вес основных признаков уменьшается от 2N до 2 согласно их приоритету.
        weight = max(2, (len(priorities) - priorities[key]) * 2)
        total_weight += weight
        if candidate_value[1] == source_value:
            matched_weight += weight
            matched.append({
                "name": display_name,
                "original_value": source_display_value,
                "analog_value": candidate_value[2],
            })
        else:
            unmatched.append({
                "name": display_name,
                "original_value": source_display_value,
                "analog_value": candidate_value[2],
            })
    similarity = round(matched_weight * 100 / total_weight) if total_weight else 0
    return ScoredAnalog(candidate, similarity, matched, unmatched)


def find_product_analogs(db: Session, product_id: int) -> list[ScoredAnalog] | None:
    """Считает аналоги динамически, ограничивая выборку индексированной категорией."""
    source = db.query(Product).options(selectinload(Product.properties)).filter(Product.id == product_id).first()
    if source is None:
        return None
    if not source.section:
        return []
    setting = get_analog_settings(db)
    primary = primary_properties(setting)
    primary_keys = {_normalized(name) for name in primary}
    if not primary_keys.intersection(_characteristics(source)):
        return []
    candidates = (
        db.query(Product)
        .options(selectinload(Product.properties))
        .filter(Product.section == source.section, Product.id != source.id)
        .all()
    )
    scored = [_score(source, candidate, primary) for candidate in candidates]
    eligible = [item for item in scored if item.similarity >= setting.minimum_similarity]
    same_type = [item for item in eligible if source.product_type and item.product.product_type == source.product_type]
    other_type = [
        item for item in eligible
        if not source.product_type or item.product.product_type != source.product_type
    ]
    # При равном проценте сначала показывается наиболее близкое к оригиналу
    # наименование, затем применяется алфавитный и стабильный порядок.
    key = lambda item: (
        -item.similarity,
        -_name_similarity(source, item.product),
        *_alphabetical_name(item.product),
        item.product.id,
    )
    selected = (sorted(same_type, key=key) + sorted(other_type, key=key))[:setting.maximum_analogs]
    # Фильтр применяется к уже сформированному перечню: товар считается аналогом,
    # только если первое слово его наименования совпадает с первым словом оригинала.
    source_first_word = _first_name_word(source)
    selected = [
        item for item in selected
        if source_first_word and _first_name_word(item.product) == source_first_word
    ]
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
