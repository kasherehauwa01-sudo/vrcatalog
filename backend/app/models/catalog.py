from __future__ import annotations

from datetime import datetime
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
    description: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
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

    prices: Mapped[list["Price"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    stocks: Mapped[list["Stock"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    properties: Mapped[list["ProductProperty"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    analogs: Mapped[list["Analog"]] = relationship(cascade="all, delete-orphan", back_populates="product")
    barcodes: Mapped[list["Barcode"]] = relationship(cascade="all, delete-orphan", back_populates="product")


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
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class Notification(Base):
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(64), index=True)
    title: Mapped[str] = mapped_column(String(255))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
