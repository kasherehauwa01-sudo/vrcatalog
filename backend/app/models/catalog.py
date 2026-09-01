from __future__ import annotations

from datetime import datetime, timedelta
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base


class ImportRun(Base):
    __tablename__ = "import_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), default="running")
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(128), index=True, unique=True)
    name: Mapped[str] = mapped_column(String(512), index=True)
    article: Mapped[str | None] = mapped_column(String(255), index=True)
    section: Mapped[str | None] = mapped_column(String(255), index=True)
    product_type: Mapped[str | None] = mapped_column(String(255), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    manufacturer: Mapped[str | None] = mapped_column(String(255), index=True)
    brand: Mapped[str | None] = mapped_column(String(255), index=True)
    manager: Mapped[str | None] = mapped_column(String(255), index=True)
    country: Mapped[str | None] = mapped_column(String(255), index=True)
    material: Mapped[str | None] = mapped_column(String(255), index=True)
    color: Mapped[str | None] = mapped_column(String(255), index=True)
    certificate: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[str | None] = mapped_column(Text)
    search_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    @property
    def is_new(self) -> bool:
        """Определяет статус новинки динамически, без хранения отдельного флага."""
        return self.created_at >= datetime.utcnow() - timedelta(days=7)

    prices: Mapped[list["Price"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    stocks: Mapped[list["Stock"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    properties: Mapped[list["ProductProperty"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    analogs: Mapped[list["Analog"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    barcodes: Mapped[list["Barcode"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    images: Mapped[list["ProductImage"]] = relationship(cascade="all, delete-orphan", back_populates="product", order_by="ProductImage.image_order")


class Price(Base):
    __tablename__ = "prices"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    price_type: Mapped[str] = mapped_column(String(255), index=True)
    price_value: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    product: Mapped[Product] = relationship(back_populates="prices")

    @property
    def value(self) -> float:
        return self.price_value


class Stock(Base):
    __tablename__ = "stocks"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    warehouse: Mapped[str] = mapped_column(String(255), index=True)
    quantity: Mapped[float] = mapped_column(Float, default=0)
    product: Mapped[Product] = relationship(back_populates="stocks")


class ProductProperty(Base):
    __tablename__ = "product_properties"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    property_code: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[str | None] = mapped_column(Text)
    product: Mapped[Product] = relationship(back_populates="properties")


class Analog(Base):
    __tablename__ = "analogs"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    code: Mapped[str | None] = mapped_column(String(255), index=True)
    name: Mapped[str | None] = mapped_column(String(512))
    product: Mapped[Product] = relationship(back_populates="analogs")


class Barcode(Base):
    __tablename__ = "barcodes"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    value: Mapped[str] = mapped_column(String(255), index=True)
    product: Mapped[Product] = relationship(back_populates="barcodes")


class ProductImage(Base):
    __tablename__ = "product_images"
    __table_args__ = (UniqueConstraint("product_id", "image_order", name="uq_product_images_product_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    image_order: Mapped[int] = mapped_column(Integer)
    image_url: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    product: Mapped[Product] = relationship(back_populates="images")

    @property
    def order(self) -> int:
        return self.image_order

    @property
    def url(self) -> str:
        return self.image_url


class Favorite(Base):
    __tablename__ = "favorites"
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ViewHistory(Base):
    __tablename__ = "view_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    viewed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ServiceLog(Base):
    __tablename__ = "service_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(32), default="info", index=True)
    event: Mapped[str] = mapped_column(String(255), index=True)
    message: Mapped[str] = mapped_column(Text)
    error_type: Mapped[str | None] = mapped_column(String(255), index=True)
    traceback: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class XmlServerSetting(Base):
    __tablename__ = "xml_server_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    protocol: Mapped[str] = mapped_column(String(16), default="FTP")
    host: Mapped[str] = mapped_column(String(255), default="")
    port: Mapped[int] = mapped_column(Integer, default=21)
    username: Mapped[str] = mapped_column(String(255), default="")
    password: Mapped[str] = mapped_column(String(255), default="")
    xml_dir: Mapped[str] = mapped_column(String(512), default="/xml")
    connection_attempts: Mapped[int] = mapped_column(Integer, default=5)
    retry_delay_seconds: Mapped[int] = mapped_column(Integer, default=3)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class FtpConnectionLog(Base):
    __tablename__ = "ftp_connection_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    duration_ms: Mapped[float] = mapped_column(Float)
    attempt_number: Mapped[int] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    error_type: Mapped[str | None] = mapped_column(String(255))
    error_message: Mapped[str | None] = mapped_column(Text)


class AutoImportState(Base):
    __tablename__ = "auto_import_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    status: Mapped[str] = mapped_column(String(32), default="stopped")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    processed_files: Mapped[int] = mapped_column(Integer, default=0)
    successful_files: Mapped[int] = mapped_column(Integer, default=0)
    failed_files: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text)
    is_running: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WarehouseSetting(Base):
    __tablename__ = "warehouse_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductTypeSetting(Base):
    __tablename__ = "product_type_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ProductTypeChange(Base):
    __tablename__ = "product_type_changes"

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    product_code: Mapped[str | None] = mapped_column(String(255))
    article: Mapped[str | None] = mapped_column(String(255))
    product_name: Mapped[str] = mapped_column(String(512))
    old_value: Mapped[str | None] = mapped_column(String(255))
    new_value: Mapped[str | None] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(64), default="api")
    processed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
    event_key: Mapped[str | None] = mapped_column(String(512), unique=True, index=True)
    claim_token: Mapped[str | None] = mapped_column(String(64), index=True)


class ProductPromotionState(Base):
    __tablename__ = "product_promotion_states"

    id: Mapped[int] = mapped_column(primary_key=True)
    article_key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    promo: Mapped[bool] = mapped_column(Boolean, default=False)
    current_value: Mapped[str | None] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MailSetting(Base):
    __tablename__ = "mail_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    smtp_host: Mapped[str] = mapped_column(String(255), default="")
    smtp_port: Mapped[int] = mapped_column(Integer, default=587)
    encryption: Mapped[str] = mapped_column(String(16), default="starttls")
    username: Mapped[str] = mapped_column(String(255), default="")
    encrypted_password: Mapped[str] = mapped_column(Text, default="")
    sender_name: Mapped[str] = mapped_column(String(255), default="VR Catalog")
    sender_email: Mapped[str] = mapped_column(String(255), default="")
    connection_status: Mapped[str] = mapped_column(String(32), default="not_configured")
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationScenarioSetting(Base):
    __tablename__ = "notification_scenario_settings"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    send_time: Mapped[str] = mapped_column(String(5), default="22:00")
    recipients_json: Mapped[str] = mapped_column(Text, default="[]")
    last_run_date: Mapped[str | None] = mapped_column(String(10), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationEmailHistory(Base):
    __tablename__ = "notification_email_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_code: Mapped[str] = mapped_column(String(64), index=True)
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    recipients_json: Mapped[str] = mapped_column(Text)
    subject: Mapped[str] = mapped_column(String(512))
    body_html: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    duration_ms: Mapped[float] = mapped_column(Float, default=0)
