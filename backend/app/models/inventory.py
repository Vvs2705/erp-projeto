import uuid
from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import String, Numeric, DateTime, ForeignKey, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_products_sku_tenant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    stock_valuation: Mapped[Optional["StockValuation"]] = relationship(back_populates="product", cascade="all, delete-orphan")
    stock_moves: Mapped[list["StockMove"]] = relationship(back_populates="product", cascade="all, delete-orphan")


class StockMove(Base):
    __tablename__ = "stock_moves"
    __table_args__ = (
        CheckConstraint("move_type IN ('in', 'out')", name="chk_stock_moves_move_type"),
        CheckConstraint("quantity >= 0", name="chk_stock_moves_quantity"),
        CheckConstraint("unit_cost >= 0", name="chk_stock_moves_unit_cost"),
        CheckConstraint("total_cost >= 0", name="chk_stock_moves_total_cost"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="RESTRICT"), nullable=False)
    move_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'in' or 'out'
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reference: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="stock_moves")


class StockValuation(Base):
    __tablename__ = "stock_valuations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", name="uq_stock_valuations_product_tenant"),
        CheckConstraint("qty_on_hand >= 0", name="chk_stock_valuations_qty_on_hand"),
        CheckConstraint("average_unit_cost >= 0", name="chk_stock_valuations_average_unit_cost"),
        CheckConstraint("total_value >= 0", name="chk_stock_valuations_total_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    product_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False)
    qty_on_hand: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
    average_unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), default=Decimal("0.0000"), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="stock_valuation")
