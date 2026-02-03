from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Vendor(Base):
    __tablename__ = "vendors"

    vendor_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    phone_number: Mapped[str | None] = mapped_column(String(64), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    lead_time_days: Mapped[int] = mapped_column(Integer)
    minimum_order: Mapped[float] = mapped_column(Float)
    rating: Mapped[float] = mapped_column(Float)


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    sku: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(64))
    current_stock: Mapped[int] = mapped_column(Integer)
    reorder_point: Mapped[int] = mapped_column(Integer)
    daily_sales_velocity: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float)
    selling_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    gross_margin_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    holding_cost_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    substitute_skus: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    vendor_id: Mapped[str] = mapped_column(String(32), ForeignKey("vendors.vendor_id"))
    lead_time_days: Mapped[int] = mapped_column(Integer)
    last_updated: Mapped[date | None] = mapped_column(Date, nullable=True)


class VendorCallLog(Base):
    __tablename__ = "vendor_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    vendor_id: Mapped[str] = mapped_column(String(32))
    contact_time: Mapped[datetime] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)


class ReplenishmentPlan(Base):
    __tablename__ = "replenishment_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    total_cost: Mapped[float] = mapped_column(Float)
    vendor_groups: Mapped[dict] = mapped_column(JSON)
