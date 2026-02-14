from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
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
    duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    recording_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)


class ReplenishmentPlan(Base):
    __tablename__ = "replenishment_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_cost: Mapped[float] = mapped_column(Float)
    vendor_groups: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(64), nullable=True)


class TeamRun(Base):
    __tablename__ = "team_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    objective: Mapped[str] = mapped_column(Text)
    topology_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    orchestration_options: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TeamSharedState(Base):
    __tablename__ = "team_shared_state"
    __table_args__ = (UniqueConstraint("run_id", "state_key", name="uq_team_shared_state_run_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    state_key: Mapped[str] = mapped_column(String(128))
    state_value: Mapped[Any] = mapped_column(JSON)
    version: Mapped[int] = mapped_column(Integer)
    producer_member: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime)


class TeamMemberMemory(Base):
    __tablename__ = "team_member_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    scope: Mapped[str] = mapped_column(String(64), index=True)
    content: Mapped[str] = mapped_column(Text)
    memory_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)


class TeamArtifact(Base):
    __tablename__ = "team_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), index=True)
    member_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(64))
    file_name: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(1024))
    content_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    artifact_meta: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime)
