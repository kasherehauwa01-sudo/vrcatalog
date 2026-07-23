from datetime import datetime
from pydantic import BaseModel, ConfigDict

class PriceOut(BaseModel):
    price_type: str
    value: float
    model_config = ConfigDict(from_attributes=True)
class StockOut(BaseModel):
    warehouse: str
    quantity: float
    model_config = ConfigDict(from_attributes=True)
class PropertyOut(BaseModel):
    property_code: str | None
    name: str
    value: str | None
    model_config = ConfigDict(from_attributes=True)
class AnalogOut(BaseModel):
    code: str | None
    name: str | None
    model_config = ConfigDict(from_attributes=True)
class BarcodeOut(BaseModel):
    value: str
    model_config = ConfigDict(from_attributes=True)
class ProductListOut(BaseModel):
    id: int; code: str; name: str; article: str | None; section: str | None; quantity: float; image_url: str | None = None
    retail_price: float | None = None
    prices: list[PriceOut] = []
    model_config = ConfigDict(from_attributes=True)
class ProductDetailOut(ProductListOut):
    description: str | None; manufacturer: str | None; brand: str | None; manager: str | None; country: str | None; material: str | None; color: str | None; certificate: str | None; tags: str | None
    prices: list[PriceOut]; stocks: list[StockOut]; properties: list[PropertyOut]; analogs: list[AnalogOut]; barcodes: list[BarcodeOut]
class MetaOut(BaseModel):
    last_import: datetime | None
    product_count: int
    import_status: str | None = None
    imported_count: int | None = None
    errors: str | None = None

class ServiceLogOut(BaseModel):
    id: int
    level: str
    event: str
    message: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    message: str
    created_at: datetime
    is_read: bool
    model_config = ConfigDict(from_attributes=True)
