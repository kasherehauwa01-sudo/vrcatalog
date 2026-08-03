from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from app.models.catalog import Product


def products_by_articles(
    db: Session,
    articles: list[str],
    *,
    include_zero_stock: bool = False,
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
        .options(selectinload(Product.properties))
        .filter(
            or_(
                Product.article.in_(unique_articles),
                Product.code.in_(unique_articles),
            )
        )
        .order_by(Product.id)
        .all()
    )
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

    return [product_for_article(article, products_by_article.get(article)) for article in articles]


def product_for_article(article: str, product) -> dict:
    """Формирует строго ограниченный контракт внутреннего API."""
    if product is None:
        return {
            "article": article,
            "found": False,
            "product_id": None,
            "name": None,
            "manager_id": None,
            "manager_name": "",
        }
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
    return {
        "article": article,
        "found": True,
        "product_id": product.id,
        "name": product.name,
        # В текущем каталоге менеджер хранится только текстом, таблицы сотрудников нет.
        "manager_id": None,
        "manager_name": manager_name,
    }
