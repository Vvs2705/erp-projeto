import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

# Modos de rastreamento de estoque suportados (custo de saída por modo):
# - ``none``: custo médio ponderado móvel (MPM) — padrão.
# - ``lot``: rastreio por lote; saída por PEPS/FIFO (custo real dos lotes).
# - ``serial``: rastreio por número de série; saída por identificação específica.
TRACKING_MODES = ("none", "lot", "serial")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("tenant_id", "sku", name="uq_products_sku_tenant"),
        CheckConstraint(
            "tracking_mode IN ('none', 'lot', 'serial')",
            name="chk_products_tracking_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_of_measure: Mapped[str] = mapped_column(String(50), nullable=False)
    tracking_mode: Mapped[str] = mapped_column(
        String(10), default="none", server_default="none", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    stock_valuation: Mapped[Optional["StockValuation"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    stock_moves: Mapped[list["StockMove"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    stock_lots: Mapped[list["StockLot"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    stock_serials: Mapped[list["StockSerial"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )


class StockMove(Base):
    __tablename__ = "stock_moves"
    __table_args__ = (
        CheckConstraint("move_type IN ('in', 'out')", name="chk_stock_moves_move_type"),
        CheckConstraint("quantity >= 0", name="chk_stock_moves_quantity"),
        CheckConstraint("unit_cost >= 0", name="chk_stock_moves_unit_cost"),
        CheckConstraint("total_cost >= 0", name="chk_stock_moves_total_cost"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="RESTRICT"),
        nullable=False,
    )
    move_type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'in' or 'out'
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    reference: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="stock_moves")


class StockValuation(Base):
    __tablename__ = "stock_valuations"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "product_id", name="uq_stock_valuations_product_tenant"
        ),
        CheckConstraint("qty_on_hand >= 0", name="chk_stock_valuations_qty_on_hand"),
        CheckConstraint(
            "average_unit_cost >= 0", name="chk_stock_valuations_average_unit_cost"
        ),
        CheckConstraint("total_value >= 0", name="chk_stock_valuations_total_value"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    qty_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    average_unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="stock_valuation")


class StockLot(Base):
    """Camada de custo por lote (rastreio ``lot``).

    Cada entrada de um produto rastreado por lote alimenta um ``StockLot`` com a
    quantidade em mãos e o custo unitário daquele lote. As saídas consomem os
    lotes por PEPS/FIFO (validade mais próxima primeiro, depois ordem de entrada),
    de forma que o CMV reflete o custo real dos lotes baixados.
    """

    __tablename__ = "stock_lots"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "lot_number",
            name="uq_stock_lots_product_lot",
        ),
        CheckConstraint("qty_on_hand >= 0", name="chk_stock_lots_qty_on_hand"),
        CheckConstraint("unit_cost >= 0", name="chk_stock_lots_unit_cost"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    lot_number: Mapped[str] = mapped_column(String(100), nullable=False)
    qty_on_hand: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    expiry_date: Mapped[date | None] = mapped_column(Date(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="stock_lots")


class StockSerial(Base):
    """Unidade serializada (rastreio ``serial``).

    Cada unidade de um produto rastreado por série é uma linha com número único e
    custo próprio. A saída exige os números de série baixados (identificação
    específica), de modo que o CMV é o custo exato daquelas unidades.
    """

    __tablename__ = "stock_serials"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "product_id",
            "serial_number",
            name="uq_stock_serials_product_serial",
        ),
        CheckConstraint(
            "status IN ('in_stock', 'consumed')",
            name="chk_stock_serials_status",
        ),
        CheckConstraint("unit_cost >= 0", name="chk_stock_serials_unit_cost"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
    )
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 4), default=Decimal("0.0000"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), default="in_stock", server_default="in_stock", nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    product: Mapped["Product"] = relationship(back_populates="stock_serials")
