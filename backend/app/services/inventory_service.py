import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.inventory import (
    Product,
    StockLot,
    StockMove,
    StockSerial,
    StockValuation,
)

_ZERO = Decimal("0.0000")


class InventoryException(Exception):
    """Base exception for inventory service"""

    pass


class InsufficientStockException(InventoryException):
    pass


class ProductNotFoundException(InventoryException):
    pass


class LotTrackingException(InventoryException):
    """Erro de rastreamento por lote (lote ausente/inexistente/sem saldo)."""


class SerialTrackingException(InventoryException):
    """Erro de rastreamento por série (séries ausentes/duplicadas/já baixadas)."""


class InventoryService:
    @staticmethod
    async def get_or_create_valuation(
        db: AsyncSession, tenant_id: uuid.UUID, product_id: uuid.UUID
    ) -> StockValuation:
        stmt = select(StockValuation).where(
            StockValuation.tenant_id == tenant_id,
            StockValuation.product_id == product_id,
        )
        res = await db.execute(stmt)
        val = res.scalar_one_or_none()
        if not val:
            val = StockValuation(
                tenant_id=tenant_id,
                product_id=product_id,
                qty_on_hand=_ZERO,
                average_unit_cost=_ZERO,
                total_value=_ZERO,
            )
            db.add(val)
            await db.flush()
        return val

    @staticmethod
    def _apply_in(valuation: StockValuation, qty: Decimal, u_cost: Decimal) -> None:
        """Soma uma entrada ao agregado e recalcula o custo médio."""
        valuation.qty_on_hand += qty
        valuation.total_value += qty * u_cost
        if valuation.qty_on_hand > _ZERO:
            valuation.average_unit_cost = valuation.total_value / valuation.qty_on_hand
        else:
            valuation.average_unit_cost = _ZERO

    @staticmethod
    def _apply_out(valuation: StockValuation, qty: Decimal, out_cost: Decimal) -> None:
        """Baixa uma saída do agregado pelo custo real apurado (``out_cost``)."""
        valuation.qty_on_hand -= qty
        valuation.total_value -= out_cost
        if valuation.qty_on_hand > _ZERO:
            valuation.average_unit_cost = valuation.total_value / valuation.qty_on_hand
        else:
            valuation.average_unit_cost = _ZERO
            # Sem saldo, zera resíduos de arredondamento para não deixar valor solto.
            valuation.total_value = _ZERO

    @staticmethod
    async def _lot_in(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        qty: Decimal,
        u_cost: Decimal,
        lot_number: str | None,
        expiry_date: date | None,
    ) -> None:
        if not lot_number:
            raise LotTrackingException(
                "Produto rastreado por lote exige 'lot_number' na entrada."
            )
        stmt = select(StockLot).where(
            StockLot.tenant_id == tenant_id,
            StockLot.product_id == product_id,
            StockLot.lot_number == lot_number,
        )
        lot = (await db.execute(stmt)).scalar_one_or_none()
        if lot is None:
            lot = StockLot(
                tenant_id=tenant_id,
                product_id=product_id,
                lot_number=lot_number,
                qty_on_hand=qty,
                unit_cost=u_cost,
                expiry_date=expiry_date,
            )
            db.add(lot)
        else:
            # Reentrada no mesmo lote: média ponderada dentro do lote.
            new_qty = lot.qty_on_hand + qty
            if new_qty > _ZERO:
                lot.unit_cost = (
                    lot.qty_on_hand * lot.unit_cost + qty * u_cost
                ) / new_qty
            lot.qty_on_hand = new_qty
            if expiry_date is not None and lot.expiry_date is None:
                lot.expiry_date = expiry_date
        await db.flush()

    @staticmethod
    async def _lot_out(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        qty: Decimal,
        lot_number: str | None,
    ) -> Decimal:
        """Consome lotes e devolve o custo total real da saída.

        Com ``lot_number`` baixa o lote indicado; sem ele, PEPS/FIFO (validade
        mais próxima primeiro, depois ordem de entrada).
        """
        stmt = select(StockLot).where(
            StockLot.tenant_id == tenant_id,
            StockLot.product_id == product_id,
            StockLot.qty_on_hand > _ZERO,
        )
        if lot_number:
            stmt = stmt.where(StockLot.lot_number == lot_number)
        stmt = stmt.order_by(
            StockLot.expiry_date.asc().nulls_last(),
            StockLot.created_at.asc(),
        )
        lots = list((await db.execute(stmt)).scalars().all())

        available = sum((lot.qty_on_hand for lot in lots), _ZERO)
        if available < qty:
            target = f"lote {lot_number}" if lot_number else "lotes disponíveis"
            raise InsufficientStockException(
                f"Estoque insuficiente em {target} para o produto {product_id}. "
                f"Disponível: {available}, solicitado: {qty}"
            )

        remaining = qty
        out_cost = _ZERO
        for lot in lots:
            if remaining <= _ZERO:
                break
            take = min(lot.qty_on_hand, remaining)
            out_cost += take * lot.unit_cost
            lot.qty_on_hand -= take
            remaining -= take
        await db.flush()
        return out_cost

    @staticmethod
    async def _serial_in(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        qty: Decimal,
        u_cost: Decimal,
        serial_numbers: list[str] | None,
    ) -> None:
        serials = serial_numbers or []
        if Decimal(len(serials)) != qty:
            raise SerialTrackingException(
                "Produto rastreado por série exige um 'serial_number' por unidade: "
                f"recebidos {len(serials)} para quantidade {qty}."
            )
        if len(set(serials)) != len(serials):
            raise SerialTrackingException("Números de série duplicados na entrada.")
        existing = (
            (
                await db.execute(
                    select(StockSerial.serial_number).where(
                        StockSerial.tenant_id == tenant_id,
                        StockSerial.product_id == product_id,
                        StockSerial.serial_number.in_(serials),
                    )
                )
            )
            .scalars()
            .all()
        )
        if existing:
            raise SerialTrackingException(
                f"Números de série já existentes: {sorted(existing)}."
            )
        for serial in serials:
            db.add(
                StockSerial(
                    tenant_id=tenant_id,
                    product_id=product_id,
                    serial_number=serial,
                    unit_cost=u_cost,
                    status="in_stock",
                )
            )
        await db.flush()

    @staticmethod
    async def _serial_out(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        product_id: uuid.UUID,
        qty: Decimal,
        serial_numbers: list[str] | None,
    ) -> Decimal:
        serials = serial_numbers or []
        if Decimal(len(serials)) != qty:
            raise SerialTrackingException(
                "Produto rastreado por série exige um 'serial_number' por unidade: "
                f"informados {len(serials)} para quantidade {qty}."
            )
        if len(set(serials)) != len(serials):
            raise SerialTrackingException("Números de série duplicados na saída.")
        rows = list(
            (
                await db.execute(
                    select(StockSerial).where(
                        StockSerial.tenant_id == tenant_id,
                        StockSerial.product_id == product_id,
                        StockSerial.serial_number.in_(serials),
                        StockSerial.status == "in_stock",
                    )
                )
            )
            .scalars()
            .all()
        )
        found = {row.serial_number for row in rows}
        missing = [s for s in serials if s not in found]
        if missing:
            raise SerialTrackingException(
                f"Séries indisponíveis (inexistentes ou já baixadas): {missing}."
            )
        now = datetime.utcnow()
        out_cost = _ZERO
        for row in rows:
            out_cost += row.unit_cost
            row.status = "consumed"
            row.consumed_at = now
        await db.flush()
        return out_cost

    @staticmethod
    async def register_stock_move(
        db: AsyncSession,
        tenant_id: uuid.UUID,
        organization_id: uuid.UUID,
        product_id: uuid.UUID,
        move_type: str,
        quantity: Decimal,
        unit_cost: Decimal,
        reference: str,
        lot_number: str | None = None,
        expiry_date: date | None = None,
        serial_numbers: list[str] | None = None,
    ) -> StockMove:
        """Registra uma movimentação de estoque e atualiza a valoração.

        O custo de saída depende do ``tracking_mode`` do produto:
        - ``none``: custo médio ponderado móvel (MPM);
        - ``lot``: PEPS/FIFO sobre os lotes (custo real dos lotes baixados);
        - ``serial``: identificação específica das unidades baixadas.

        Em todos os modos o agregado ``StockValuation`` permanece como fonte da
        verdade de quantidade e valor; lotes/séries são as camadas de custo.
        """
        if move_type not in ("in", "out"):
            raise InventoryException(
                f"Invalid move_type: {move_type}. Must be 'in' or 'out'."
            )

        prod = (
            await db.execute(
                select(Product).where(
                    Product.tenant_id == tenant_id, Product.id == product_id
                )
            )
        ).scalar_one_or_none()
        if prod is None:
            raise ProductNotFoundException(f"Product with ID {product_id} not found.")

        qty = Decimal(str(quantity))
        u_cost = Decimal(str(unit_cost))
        if qty <= _ZERO:
            raise InventoryException("Quantity must be greater than zero.")

        mode = prod.tracking_mode
        # Rejeita parâmetros incoerentes com o modo (sem ignorar em silêncio).
        if mode != "lot" and lot_number is not None:
            raise LotTrackingException(
                f"Produto não é rastreado por lote (modo '{mode}'); "
                "não informe 'lot_number'."
            )
        if mode != "serial" and serial_numbers is not None:
            raise SerialTrackingException(
                f"Produto não é rastreado por série (modo '{mode}'); "
                "não informe 'serial_numbers'."
            )

        valuation = await InventoryService.get_or_create_valuation(
            db, tenant_id, product_id
        )

        if move_type == "in":
            if mode == "lot":
                await InventoryService._lot_in(
                    db, tenant_id, product_id, qty, u_cost, lot_number, expiry_date
                )
            elif mode == "serial":
                await InventoryService._serial_in(
                    db, tenant_id, product_id, qty, u_cost, serial_numbers
                )
            InventoryService._apply_in(valuation, qty, u_cost)
            actual_unit_cost = u_cost
            total_cost = qty * u_cost
        else:  # out
            if mode == "lot":
                out_cost = await InventoryService._lot_out(
                    db, tenant_id, product_id, qty, lot_number
                )
            elif mode == "serial":
                out_cost = await InventoryService._serial_out(
                    db, tenant_id, product_id, qty, serial_numbers
                )
            else:
                if valuation.qty_on_hand < qty:
                    raise InsufficientStockException(
                        f"Insufficient stock for product {product_id}. "
                        f"Available: {valuation.qty_on_hand}, Requested: {qty}"
                    )
                out_cost = qty * valuation.average_unit_cost
            InventoryService._apply_out(valuation, qty, out_cost)
            actual_unit_cost = out_cost / qty if qty > _ZERO else _ZERO
            total_cost = out_cost

        stock_move = StockMove(
            tenant_id=tenant_id,
            organization_id=organization_id,
            product_id=product_id,
            move_type=move_type,
            quantity=qty,
            unit_cost=actual_unit_cost,
            total_cost=total_cost,
            reference=reference,
        )
        db.add(stock_move)
        await db.flush()

        return stock_move
