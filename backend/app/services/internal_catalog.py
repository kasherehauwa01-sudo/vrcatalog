from html import unescape
from html.parser import HTMLParser

from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import Product, WarehouseSetting


class _SectionTextExtractor(HTMLParser):
    """Извлекает отображаемый текст раздела, не пропуская HTML в контракт API."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def normalize_section(value: str | None) -> str | None:
    """Нормализует пробелы раздела, сохраняя регистр и исходные буквы."""
    if not value:
        return None
    parser = _SectionTextExtractor()
    parser.feed(unescape(value))
    normalized = " ".join("".join(parser.parts).replace("\xa0", " ").split())
    return normalized or None


def products_by_articles(
    db: Session,
    articles: list[str],
    *,
    include_zero_stock: bool = False,
    include_warehouse_stocks: bool = False,
    include_section: bool = False,
) -> list[dict]:
    """Находит точные артикулы во всех карточках и восстанавливает порядок входа.

    Внутренний API выбирает данные непосредственно из ``products`` и
    не связывает результат обязательным JOIN с остатками. Поэтому значение
    ``include_zero_stock`` явно поддерживается контрактом, но не добавляет
    ограничений к запросу: как при прежнем значении ``False``, так и при ``True``
    карточки без складских строк и с нулевым остатком остаются доступными.
    """
    unique_articles = list(dict.fromkeys(articles))
    if not unique_articles:
        return []

    products = (
        db.query(Product)
        .options(selectinload(Product.properties), selectinload(Product.stocks))
        .filter(
            or_(
                Product.article.in_(unique_articles),
                Product.code.in_(unique_articles),
            )
        )
        .order_by(Product.id)
        .all()
    )
    warehouse_names = {
        code: name for code, name in db.query(WarehouseSetting.code, WarehouseSetting.name).all()
    }
    # Артикул пока не уникален на уровне БД; при дубле сохраняем товар с меньшим ID.
    products_by_article: dict[str, Product] = {}
    # Сначала сохраняем точное совпадение с артикулом, если оно есть.
    for product in products:
        if product.article in unique_articles:
            products_by_article.setdefault(product.article, product)
    # Код карточки — совместимый резерв для импортов, где свойство «Артикул» пусто.
    for product in products:
        if product.code in unique_articles:
            products_by_article.setdefault(product.code, product)

    return [
        product_for_article(
            article,
            products_by_article.get(article),
            warehouse_names,
            include_warehouse_stocks=include_warehouse_stocks,
            include_section=include_section,
        )
        for article in articles
    ]


def product_for_article(
    article: str,
    product,
    warehouse_names: dict[str, str] | None = None,
    *,
    include_warehouse_stocks: bool = False,
    include_section: bool = False,
) -> dict:
    """Формирует строго ограниченный контракт внутреннего API."""
    if product is None:
        item = {
            "article": article,
            "found": False,
            "product_id": None,
            "code": None,
            "name": None,
            "manager_id": None,
            "manager_name": "",
            "stocks": [],
        }
        if include_section:
            item["section"] = None
        return item
    manager_name = (product.manager or "").strip()
    if not manager_name:
        manager_name = next(
            (
                (property_.value or "").strip()
                for property_ in product.properties
                if property_.name.strip().casefold() == "менеджер"
                and (property_.value or "").strip()
            ),
            "",
        )
    stocks: list[dict] = []
    if include_warehouse_stocks:
        quantities_by_warehouse: dict[str, float] = {}
        for stock in product.stocks:
            quantities_by_warehouse[stock.warehouse] = (
                quantities_by_warehouse.get(stock.warehouse, 0.0) + float(stock.quantity or 0)
            )

        names = warehouse_names or {}
        warehouses = set(names) | set(quantities_by_warehouse)
        # Возвращаем канонические названия складов из настроек UI и не теряем склады,
        # которые есть только в остатках импортированного товара.
        stocks = [
            {
                "warehouse": warehouse,
                "warehouse_name": names.get(warehouse, warehouse),
                "quantity": float(quantities_by_warehouse.get(warehouse, 0.0)),
            }
            for warehouse in sorted(warehouses, key=lambda code: names.get(code, code))
        ]
    item = {
        "article": article,
        "found": True,
        "product_id": product.id,
        "code": product.code,
        "name": product.name,
        # В текущем каталоге менеджер хранится только текстом, таблицы сотрудников нет.
        "manager_id": None,
        "manager_name": manager_name,
        "stocks": stocks,
    }
    if include_section:
        item["section"] = normalize_section(product.section)
    return item
