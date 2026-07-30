import json
import secrets
from time import perf_counter
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.catalog import ServiceLog
from app.schemas.catalog import (
    InternalProductResponse,
    InternalProductsRequest,
    InternalProductsResponse,
)
from app.services.internal_catalog import products_by_articles


router = APIRouter(prefix="/internal/products", include_in_schema=False)


def token_is_valid(token: str | None) -> bool:
    """Сравнивает токен без утечки времени и закрывает API при пустой настройке."""
    return bool(
        settings.internal_api_token
        and token
        and secrets.compare_digest(token, settings.internal_api_token)
    )


def write_request_log(
    db: Session,
    *,
    endpoint: str,
    article_count: int,
    started_at: float,
    found_count: int,
    status_code: int,
) -> None:
    """Записывает только метрики обращения, без токена, заголовков и артикулов."""
    message = json.dumps(
        {
            "endpoint": endpoint,
            "article_count": article_count,
            "duration_ms": round((perf_counter() - started_at) * 1000, 3),
            "found_count": found_count,
            "not_found_count": article_count - found_count,
            "status_code": status_code,
        },
        ensure_ascii=False,
    )
    db.add(ServiceLog(event="internal_api_request", message=message, level="info"))
    db.commit()


def require_token(
    db: Session,
    token: str | None,
    *,
    endpoint: str,
    article_count: int,
    started_at: float,
) -> None:
    if token_is_valid(token):
        return
    write_request_log(
        db,
        endpoint=endpoint,
        article_count=article_count,
        started_at=started_at,
        found_count=0,
        status_code=401,
    )
    raise HTTPException(status_code=401, detail="Неверный внутренний токен")


@router.get("/by-article/{article}", response_model=InternalProductResponse)
def internal_product_by_article(
    article: str,
    x_internal_token: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    started_at = perf_counter()
    endpoint = "GET /internal/products/by-article/{article}"
    require_token(
        db,
        x_internal_token,
        endpoint=endpoint,
        article_count=1,
        started_at=started_at,
    )
    item = products_by_articles(db, [article])[0]
    write_request_log(
        db,
        endpoint=endpoint,
        article_count=1,
        started_at=started_at,
        found_count=int(item["found"]),
        status_code=200,
    )
    return {"ok": True, **item}


@router.post("/by-articles", response_model=InternalProductsResponse)
def internal_products_by_articles(
    payload: InternalProductsRequest,
    x_internal_token: Annotated[str | None, Header()] = None,
    db: Session = Depends(get_db),
):
    started_at = perf_counter()
    endpoint = "POST /internal/products/by-articles"
    article_count = len(payload.articles)
    require_token(
        db,
        x_internal_token,
        endpoint=endpoint,
        article_count=article_count,
        started_at=started_at,
    )
    items = products_by_articles(db, payload.articles)
    found_count = sum(item["found"] for item in items)
    write_request_log(
        db,
        endpoint=endpoint,
        article_count=article_count,
        started_at=started_at,
        found_count=found_count,
        status_code=200,
    )
    return {"ok": True, "items": items}
