from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_serializer


PRODUCT_DATE_FORMAT = "%d.%m.%Y %H:%M"

class PriceOut(BaseModel):
    price_type: str
    value: float
    model_config = ConfigDict(from_attributes=True)
class StockOut(BaseModel):
    warehouse: str
    warehouse_name: str | None = None
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
class ProductImageOut(BaseModel):
    order: int
    url: str
    model_config = ConfigDict(from_attributes=True)
class ProductListOut(BaseModel):
    id: int; code: str; name: str; article: str | None; section: str | None; product_type: str | None = None; product_type_name: str | None = None; quantity: float
    is_new: bool
    images: list[ProductImageOut] = []
    retail_price: float | None = None
    prices: list[PriceOut] = []
    model_config = ConfigDict(from_attributes=True)


class PaginationOut(BaseModel):
    page: int
    pageSize: int
    totalItems: int
    totalPages: int


class ProductPageOut(BaseModel):
    items: list[ProductListOut]
    pagination: PaginationOut
class ProductDetailOut(ProductListOut):
    description: str | None; manufacturer: str | None; brand: str | None; manager: str | None; country: str | None; material: str | None; color: str | None; certificate: str | None; tags: str | None
    created_at: datetime
    updated_at: datetime
    prices: list[PriceOut]; stocks: list[StockOut]; properties: list[PropertyOut]; analogs: list[AnalogOut]; barcodes: list[BarcodeOut]

    @field_serializer("created_at", "updated_at")
    def serialize_product_date(self, value: datetime) -> str:
        """Возвращает даты карточки товара в едином человекочитаемом формате."""
        return value.strftime(PRODUCT_DATE_FORMAT)
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
    error_type: str | None = None
    traceback: str | None = None
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


class WarehouseSettingIn(BaseModel):
    code: str
    name: str

class WarehouseSettingOut(WarehouseSettingIn):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class ProductTypeSettingIn(BaseModel):
    code: str
    name: str

class ProductTypeSettingOut(ProductTypeSettingIn):
    id: int
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)

class XmlServerSettingIn(BaseModel):
    protocol: str = "FTP"
    host: str
    port: int
    username: str
    password: str
    xml_dir: str

class XmlServerSettingOut(XmlServerSettingIn):
    id: int
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)

class AutoImportStateOut(BaseModel):
    status: str
    last_run_at: datetime | None = None
    processed_files: int = 0
    successful_files: int = 0
    failed_files: int = 0
    last_error: str | None = None
    is_running: bool = False
    updated_at: datetime | None = None
    model_config = ConfigDict(from_attributes=True)

class FtpConnectionTestOut(BaseModel):
    success: bool
    message: str
