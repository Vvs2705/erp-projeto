import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.finance import (
    Account,
    Bill,
    FiscalPeriod,
    Journal,
    JournalEntry,
)
from app.services.finance_service import (
    DoubleEntryImbalanceException,
    FinanceService,
    FiscalPeriodLockedException,
)


@pytest.fixture
def mock_db():
    return AsyncMock()


@pytest.mark.asyncio
async def test_create_journal_entry_success(mock_db):
    tenant_id = uuid.uuid4()
    journal_id = uuid.uuid4()
    acc1_id = uuid.uuid4()
    acc2_id = uuid.uuid4()

    # Mock FiscalPeriod query
    mock_period = FiscalPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-06",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        status="open",
    )
    # Mock Journal query
    mock_journal = Journal(
        id=journal_id, tenant_id=tenant_id, name="Cash Journal", code="CASH"
    )
    # Mock Accounts query
    mock_acc1 = Account(
        id=acc1_id, tenant_id=tenant_id, code="1.1.01.001", name="Cash", type="asset"
    )
    mock_acc2 = Account(
        id=acc2_id,
        tenant_id=tenant_id,
        code="4.1.01.001",
        name="Sales Revenue",
        type="revenue",
    )

    # Set up mock execute results sequentially
    # 1. Fiscal period, 2. Journal, 3. Account 1, 4. Account 2
    mock_execute_results = [
        MagicMock(scalar_one_or_none=lambda: mock_period),
        MagicMock(scalar_one_or_none=lambda: mock_journal),
        MagicMock(scalar_one_or_none=lambda: mock_acc1),
        MagicMock(scalar_one_or_none=lambda: mock_acc2),
    ]
    mock_db.execute.side_effect = mock_execute_results

    lines = [
        {"account_id": acc1_id, "amount": 100.0, "direction": "DEBIT"},
        {"account_id": acc2_id, "amount": 100.0, "direction": "CREDIT"},
    ]

    entry = await FinanceService.create_journal_entry(
        db=mock_db,
        tenant_id=tenant_id,
        entry_date=date(2026, 6, 15),
        journal_id=journal_id,
        description="Sale",
        lines=lines,
    )

    assert entry.status == "draft"
    assert entry.description == "Sale"
    assert len(entry.lines) == 2
    assert entry.lines[0].amount == Decimal("100.0")
    assert entry.lines[0].direction == "DEBIT"
    assert entry.lines[1].direction == "CREDIT"
    mock_db.add.assert_called_once_with(entry)


@pytest.mark.asyncio
async def test_create_journal_entry_imbalanced(mock_db):
    tenant_id = uuid.uuid4()
    journal_id = uuid.uuid4()
    acc1_id = uuid.uuid4()
    acc2_id = uuid.uuid4()

    mock_period = FiscalPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-06",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        status="open",
    )
    mock_journal = Journal(
        id=journal_id, tenant_id=tenant_id, name="Cash Journal", code="CASH"
    )
    mock_acc1 = Account(
        id=acc1_id, tenant_id=tenant_id, code="1.1.01.001", name="Cash", type="asset"
    )
    mock_acc2 = Account(
        id=acc2_id,
        tenant_id=tenant_id,
        code="4.1.01.001",
        name="Sales Revenue",
        type="revenue",
    )

    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_period),
        MagicMock(scalar_one_or_none=lambda: mock_journal),
        MagicMock(scalar_one_or_none=lambda: mock_acc1),
        MagicMock(scalar_one_or_none=lambda: mock_acc2),
    ]

    lines = [
        {"account_id": acc1_id, "amount": 100.0, "direction": "DEBIT"},
        {"account_id": acc2_id, "amount": 99.0, "direction": "CREDIT"},
    ]

    with pytest.raises(DoubleEntryImbalanceException):
        await FinanceService.create_journal_entry(
            db=mock_db,
            tenant_id=tenant_id,
            entry_date=date(2026, 6, 15),
            journal_id=journal_id,
            description="Imbalanced Sale",
            lines=lines,
        )


@pytest.mark.asyncio
async def test_create_journal_entry_locked_period(mock_db):
    tenant_id = uuid.uuid4()
    journal_id = uuid.uuid4()

    mock_period = FiscalPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-05",
        start_date=date(2026, 5, 1),
        end_date=date(2026, 5, 31),
        status="locked",
    )
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: mock_period)

    lines = [
        {"account_id": uuid.uuid4(), "amount": 100.0, "direction": "DEBIT"},
        {"account_id": uuid.uuid4(), "amount": 100.0, "direction": "CREDIT"},
    ]

    with pytest.raises(FiscalPeriodLockedException):
        await FinanceService.create_journal_entry(
            db=mock_db,
            tenant_id=tenant_id,
            entry_date=date(2026, 5, 15),
            journal_id=journal_id,
            description="Sale",
            lines=lines,
        )


@pytest.mark.asyncio
async def test_close_fiscal_period(mock_db):
    tenant_id = uuid.uuid4()
    period_id = uuid.uuid4()

    mock_period = FiscalPeriod(
        id=period_id,
        tenant_id=tenant_id,
        name="2026-06",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        status="open",
    )
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: mock_period)

    period = await FinanceService.close_fiscal_period(mock_db, tenant_id, period_id)
    assert period.status == "locked"


@pytest.mark.asyncio
async def test_create_bill_and_provision(mock_db):
    tenant_id = uuid.uuid4()
    legal_entity_id = uuid.uuid4()
    journal_id = uuid.uuid4()
    expense_acc_id = uuid.uuid4()
    ap_acc_id = uuid.uuid4()

    # Mock checks for provision Journal Entry
    mock_period = FiscalPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-06",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        status="open",
    )
    mock_journal = Journal(
        id=journal_id, tenant_id=tenant_id, name="Purchases", code="PUR"
    )
    mock_expense = Account(
        id=expense_acc_id, tenant_id=tenant_id, code="5.1", name="Exp", type="expense"
    )
    mock_ap = Account(
        id=ap_acc_id, tenant_id=tenant_id, code="2.1", name="AP", type="liability"
    )

    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_period),
        MagicMock(scalar_one_or_none=lambda: mock_journal),
        MagicMock(scalar_one_or_none=lambda: mock_expense),
        MagicMock(scalar_one_or_none=lambda: mock_ap),
    ]

    bill = await FinanceService.create_bill(
        db=mock_db,
        tenant_id=tenant_id,
        legal_entity_id=legal_entity_id,
        provider_name="Supplier Inc",
        cnpj="12345678000199",
        number="NF-123",
        amount=Decimal("500.00"),
        issue_date=date(2026, 6, 15),
        due_date=date(2026, 7, 15),
        journal_id=journal_id,
        expense_account_id=expense_acc_id,
        ap_account_id=ap_acc_id,
    )

    assert bill.status == "pending"
    assert bill.amount == Decimal("500.00")
    # Verify that add was called for both the bill and the journal entry
    assert mock_db.add.call_count >= 2


@pytest.mark.asyncio
async def test_pay_bill_and_entry(mock_db):
    tenant_id = uuid.uuid4()
    bill_id = uuid.uuid4()
    journal_id = uuid.uuid4()
    bank_acc_id = uuid.uuid4()
    ap_acc_id = uuid.uuid4()

    mock_bill = Bill(
        id=bill_id,
        tenant_id=tenant_id,
        legal_entity_id=uuid.uuid4(),
        provider_name="Supplier Inc",
        cnpj="12345678000199",
        number="NF-123",
        amount=Decimal("500.00"),
        status="pending",
    )

    # Mocks for payment check, total paid check, journal creation
    mock_period = FiscalPeriod(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="2026-06",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 30),
        status="open",
    )
    mock_journal = Journal(id=journal_id, tenant_id=tenant_id, name="Cash", code="CSH")
    mock_ap = Account(
        id=ap_acc_id, tenant_id=tenant_id, code="2.1", name="AP", type="liability"
    )
    mock_bank = Account(
        id=bank_acc_id, tenant_id=tenant_id, code="1.1", name="Bank", type="asset"
    )

    mock_db.execute.side_effect = [
        MagicMock(scalar_one_or_none=lambda: mock_bill),
        MagicMock(scalar=lambda: Decimal("0.0")),  # total paid previously
        MagicMock(scalar_one_or_none=lambda: mock_period),
        MagicMock(scalar_one_or_none=lambda: mock_journal),
        MagicMock(scalar_one_or_none=lambda: mock_ap),
        MagicMock(scalar_one_or_none=lambda: mock_bank),
    ]

    payment = await FinanceService.pay_bill(
        db=mock_db,
        tenant_id=tenant_id,
        bill_id=bill_id,
        amount=Decimal("500.00"),
        payment_date=date(2026, 6, 20),
        payment_method="pix",
        bank_account_info="Bank A",
        journal_id=journal_id,
        bank_account_id=bank_acc_id,
        ap_account_id=ap_acc_id,
    )

    assert payment.amount == Decimal("500.00")
    assert mock_bill.status == "paid"


@pytest.mark.asyncio
async def test_reconcile_bank_transaction(mock_db):
    tenant_id = uuid.uuid4()
    entry_id = uuid.uuid4()

    mock_entry = JournalEntry(
        id=entry_id,
        tenant_id=tenant_id,
        entry_date=date(2026, 6, 15),
        description="Sale",
        status="posted",
    )
    # Add lines: 1 debit of 100, 1 credit of 100
    mock_entry.lines = [
        MagicMock(direction="DEBIT", amount=Decimal("100.00")),
        MagicMock(direction="CREDIT", amount=Decimal("100.00")),
    ]

    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: mock_entry)

    # Matching transaction
    reconciled = await FinanceService.reconcile_bank_transaction(
        db=mock_db,
        tenant_id=tenant_id,
        journal_entry_id=entry_id,
        statement_date=date(2026, 6, 16),
        statement_amount=Decimal("100.00"),
    )
    assert reconciled is True

    # Mismatched amount
    reconciled_fail_amount = await FinanceService.reconcile_bank_transaction(
        db=mock_db,
        tenant_id=tenant_id,
        journal_entry_id=entry_id,
        statement_date=date(2026, 6, 16),
        statement_amount=Decimal("200.00"),
    )
    assert reconciled_fail_amount is False

    # Date out of 3-day window
    reconciled_fail_date = await FinanceService.reconcile_bank_transaction(
        db=mock_db,
        tenant_id=tenant_id,
        journal_entry_id=entry_id,
        statement_date=date(2026, 6, 25),
        statement_amount=Decimal("100.00"),
    )
    assert reconciled_fail_date is False
