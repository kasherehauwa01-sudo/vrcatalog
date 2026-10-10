from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator, model_validator


class AnalyticsLookupItemIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    product_id: int | None = Field(default=None, strict=True, ge=1, le=2147483647)
    code: str | None = Field(default=None, strict=True, max_length=128)
    article: str | None = Field(default=None, strict=True, max_length=255)

    @field_validator("code", "article", mode="before")
    @classmethod
    def strip_identifier(cls, value):
        if isinstance(value, str):
            return value.strip() or None
        return value

    @model_validator(mode="after")
    def require_identifier(self):
        if self.product_id is None and not self.code and not self.article:
            raise ValueError("Укажите product_id, code или article")
        return self


class AnalyticsLookupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AnalyticsLookupItemIn] = Field(min_length=1, max_length=250)


class AnalyticsProductOut(BaseModel):
    product_id: int
    code: str
    article: str | None
    manufacturer: str | None
    brand: str | None
    category_id: int | None
    category: str | None
    subcategory: str | None
    legacy_category: str | None
    material: str | None
    horeca: bool
    updated_at: datetime

    @field_serializer("updated_at")
    def utc_timestamp(self, value: datetime) -> str:
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


class AnalyticsLookupItemOut(BaseModel):
    request_index: int
    status: Literal["matched", "not_found", "ambiguous"]
    matched_by: Literal["product_id", "code", "article"] | None = None
    product: AnalyticsProductOut | None = None


class AnalyticsLookupResponse(BaseModel):
    schema_version: Literal[1] = 1
    items: list[AnalyticsLookupItemOut]
