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
    include_warehouse_stocks: bool = False,
    include_zero_stock: bool = False,
    include_section: bool = False,
    section_count: int = 0,
    section_missing_count: int = 0,
    stock_rows_count: int = 0,
    warehouse_names: list[str] | None = None,
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
            "include_warehouse_stocks": include_warehouse_stocks,
            "include_zero_stock": include_zero_stock,
            "include_section": include_section,
            "section_count": section_count,
            "section_missing_count": section_missing_count,
            "stock_rows_count": stock_rows_count,
            "warehouses": warehouse_names or [],
            "stock_diagnostics": (
                "warehouse stocks were not requested"
                if not include_warehouse_stocks
                else (
                    "warehouse stocks added to response"
                    if stock_rows_count
                    else "no warehouse stocks for found products"
                )
            ),
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


@router.get("/by-article/{article}", response_model=InternalProductResponse, response_model_exclude_unset=True)
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


@router.post("/by-articles", response_model=InternalProductsResponse, response_model_exclude_unset=True)
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
    items = products_by_articles(
        db,
        payload.articles,
        include_zero_stock=payload.include_zero_stock,
        include_warehouse_stocks=payload.include_warehouse_stocks,
        include_section=payload.include_section,
    )
    found_count = sum(item["found"] for item in items)
    section_count = sum(bool(item.get("section")) for item in items if item["found"])
    section_missing_count = found_count - section_count if payload.include_section else 0
    stock_rows = [stock for item in items for stock in item.get("stocks", [])]
    warehouses = sorted({stock["warehouse_name"] for stock in stock_rows})
    write_request_log(
        db,
        endpoint=endpoint,
        article_count=article_count,
        started_at=started_at,
        found_count=found_count,
        status_code=200,
        include_warehouse_stocks=payload.include_warehouse_stocks,
        include_zero_stock=payload.include_zero_stock,
        include_section=payload.include_section,
        section_count=section_count,
        section_missing_count=section_missing_count,
        stock_rows_count=len(stock_rows),
        warehouse_names=warehouses,
    )
    return {"ok": True, "items": items}
