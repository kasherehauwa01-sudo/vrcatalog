from sqlalchemy.orm import Session

from app.models.catalog import Product


def products_by_articles(db: Session, articles: list[str]) -> list[dict]:
    """Находит уникальные артикулы одним запросом и восстанавливает порядок входа."""
    unique_articles = list(dict.fromkeys(articles))
    if not unique_articles:
        return []

    products = (
        db.query(Product.id, Product.article, Product.name, Product.manager)
        .filter(Product.article.in_(unique_articles))
        .order_by(Product.id)
        .all()
    )
    # Артикул пока не уникален на уровне БД; при дубле сохраняем товар с меньшим ID.
    products_by_article = {}
    for product in products:
        products_by_article.setdefault(product.article, product)

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
            "manager_name": None,
        }
    return {
        "article": article,
        "found": True,
        "product_id": product.id,
        "name": product.name,
        # В текущем каталоге менеджер хранится только текстом, таблицы сотрудников нет.
        "manager_id": None,
        "manager_name": product.manager,
    }
