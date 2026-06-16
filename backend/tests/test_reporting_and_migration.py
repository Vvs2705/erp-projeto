import pytest
import uuid
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from app.services.reporting_service import ReportingService
from app.services.migration_service import MigrationService
from app.models.finance import Partner, BankTransaction

@pytest.fixture
def mock_db():
    return AsyncMock()

@pytest.mark.asyncio
async def test_trial_balance_success(mock_db):
    tenant_id = uuid.uuid4()
    start_date = date(2026, 6, 1)
    end_date = date(2026, 6, 30)

    # Mocking two accounts: asset and liability, balanced
    # Asset: debit balance
    row1 = MagicMock()
    row1.id = uuid.uuid4()
    row1.code = "1.1.01.001"
    row1.name = "Cash"
    row1.type = "asset"
    row1.debit_before = Decimal("100.00")
    row1.credit_before = Decimal("0.00")
    row1.debit_period = Decimal("50.00")
    row1.credit_period = Decimal("20.00")  # Net final: 130.00 DEBIT

    # Liability: credit balance
    row2 = MagicMock()
    row2.id = uuid.uuid4()
    row2.code = "2.1.01.001"
    row2.name = "AP Accounts"
    row2.type = "liability"
    row2.debit_before = Decimal("0.00")
    row2.credit_before = Decimal("100.00")
    row2.debit_period = Decimal("20.00")
    row2.credit_period = Decimal("50.00")  # Net final: 130.00 CREDIT

    mock_db.execute.return_value = MagicMock(all=lambda: [row1, row2])

    result = await ReportingService.get_trial_balance(mock_db, tenant_id, start_date, end_date)

    assert result["totals"]["is_balanced"] is True
    assert result["totals"]["final_debit"] == Decimal("130.00")
    assert result["totals"]["final_credit"] == Decimal("130.00")
    assert len(result["accounts"]) == 2

    # Check mapping
    cash_rep = next(a for a in result["accounts"] if a["name"] == "Cash")
    assert cash_rep["initial_balance"] == Decimal("100.00")
    assert cash_rep["initial_direction"] == "DEBIT"
    assert cash_rep["final_balance"] == Decimal("130.00")
    assert cash_rep["final_direction"] == "DEBIT"

    ap_rep = next(a for a in result["accounts"] if a["name"] == "AP Accounts")
    assert ap_rep["initial_balance"] == Decimal("100.00")
    assert ap_rep["initial_direction"] == "CREDIT"
    assert ap_rep["final_balance"] == Decimal("130.00")
    assert ap_rep["final_direction"] == "CREDIT"


@pytest.mark.asyncio
async def test_trial_balance_imbalance_raises_error(mock_db):
    tenant_id = uuid.uuid4()
    start_date = date(2026, 6, 1)
    end_date = date(2026, 6, 30)

    # Imbalanced rows
    row1 = MagicMock()
    row1.id = uuid.uuid4()
    row1.code = "1.1.01.001"
    row1.name = "Cash"
    row1.type = "asset"
    row1.debit_before = Decimal("100.00")
    row1.credit_before = Decimal("0.00")
    row1.debit_period = Decimal("10.00")
    row1.credit_period = Decimal("0.00")  # Final: 110.00 DEBIT

    row2 = MagicMock()
    row2.id = uuid.uuid4()
    row2.code = "2.1.01.001"
    row2.name = "AP Accounts"
    row2.type = "liability"
    row2.debit_before = Decimal("0.00")
    row2.credit_before = Decimal("100.00")
    row2.debit_period = Decimal("0.00")
    row2.credit_period = Decimal("0.00")  # Final: 100.00 CREDIT

    mock_db.execute.return_value = MagicMock(all=lambda: [row1, row2])

    with pytest.raises(ValueError, match="Arithmetic imbalance"):
        await ReportingService.get_trial_balance(mock_db, tenant_id, start_date, end_date)


@pytest.mark.asyncio
async def test_income_statement(mock_db):
    tenant_id = uuid.uuid4()
    start_date = date(2026, 6, 1)
    end_date = date(2026, 6, 30)

    # Revenue row (Credit normal)
    row_rev = MagicMock()
    row_rev.id = uuid.uuid4()
    row_rev.code = "4.1.01.001"
    row_rev.name = "Sales Revenue"
    row_rev.type = "revenue"
    row_rev.debit_period = Decimal("10.00")
    row_rev.credit_period = Decimal("500.00")  # Net revenue: 490.00

    # Expense row (Debit normal)
    row_exp = MagicMock()
    row_exp.id = uuid.uuid4()
    row_exp.code = "5.1.01.001"
    row_exp.name = "Office Rent"
    row_exp.type = "expense"
    row_exp.debit_period = Decimal("200.00")
    row_exp.credit_period = Decimal("0.00")   # Net expense: 200.00

    mock_db.execute.return_value = MagicMock(all=lambda: [row_rev, row_exp])

    result = await ReportingService.get_income_statement(mock_db, tenant_id, start_date, end_date)

    assert result["gross_revenue"] == Decimal("490.00")
    assert result["total_expenses"] == Decimal("200.00")
    assert result["net_result"] == Decimal("290.00")


@pytest.mark.asyncio
async def test_ageing_report_ap(mock_db):
    tenant_id = uuid.uuid4()
    reference_date = date(2026, 6, 15)

    # Setup Bills:
    # 1. Not yet due (due_date=2026-06-20)
    bill1 = MagicMock()
    bill1.id = uuid.uuid4()
    bill1.number = "NF-01"
    bill1.partner_name = "Supplier A"
    bill1.cnpj = "12345678000100"
    bill1.amount = Decimal("100.00")
    bill1.issue_date = date(2026, 6, 10)
    bill1.due_date = date(2026, 6, 20)
    bill1.paid_amount = Decimal("0.00")

    # 2. Overdue 1-30 days (due_date=2026-06-05, days_overdue = 10)
    bill2 = MagicMock()
    bill2.id = uuid.uuid4()
    bill2.number = "NF-02"
    bill2.partner_name = "Supplier B"
    bill2.cnpj = "12345678000111"
    bill2.amount = Decimal("200.00")
    bill2.issue_date = date(2026, 5, 5)
    bill2.due_date = date(2026, 6, 5)
    bill2.paid_amount = Decimal("50.00")  # Open balance = 150.00

    # 3. Overdue 31-60 days (due_date=2026-05-10, days_overdue = 36)
    bill3 = MagicMock()
    bill3.id = uuid.uuid4()
    bill3.number = "NF-03"
    bill3.partner_name = "Supplier C"
    bill3.cnpj = "12345678000122"
    bill3.amount = Decimal("300.00")
    bill3.issue_date = date(2026, 4, 10)
    bill3.due_date = date(2026, 5, 10)
    bill3.paid_amount = Decimal("0.00")

    # 4. Overdue 61-90 days (due_date=2026-04-10, days_overdue = 66)
    bill4 = MagicMock()
    bill4.id = uuid.uuid4()
    bill4.number = "NF-04"
    bill4.partner_name = "Supplier D"
    bill4.cnpj = "12345678000133"
    bill4.amount = Decimal("400.00")
    bill4.issue_date = date(2026, 3, 10)
    bill4.due_date = date(2026, 4, 10)
    bill4.paid_amount = Decimal("0.00")

    # 5. Overdue >90 days (due_date=2026-02-10, days_overdue = 125)
    bill5 = MagicMock()
    bill5.id = uuid.uuid4()
    bill5.number = "NF-05"
    bill5.partner_name = "Supplier E"
    bill5.cnpj = "12345678000144"
    bill5.amount = Decimal("500.00")
    bill5.issue_date = date(2026, 1, 10)
    bill5.due_date = date(2026, 2, 10)
    bill5.paid_amount = Decimal("0.00")

    mock_db.execute.return_value = MagicMock(all=lambda: [bill1, bill2, bill3, bill4, bill5])

    result = await ReportingService.get_ageing_report(mock_db, tenant_id, "AP", reference_date)

    summary = result["summary"]
    assert summary["not_yet_due"] == Decimal("100.00")
    assert summary["overdue_1_30"] == Decimal("150.00")
    assert summary["overdue_31_60"] == Decimal("300.00")
    assert summary["overdue_61_90"] == Decimal("400.00")
    assert summary["overdue_above_90"] == Decimal("500.00")
    assert summary["total_open"] == Decimal("1450.00")


@pytest.mark.asyncio
async def test_import_partners_csv(mock_db):
    tenant_id = uuid.uuid4()
    
    # Semicolon delimited CSV with formatting in CNPJ
    csv_content = """Name;Cnpj;Type
Supplier X;12.345.678/0001-99;supplier
Customer Y;98.765.432/0001-88;customer
"""
    # Mock no existing partners in database (returns None)
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    partners = await MigrationService.import_partners_csv(mock_db, tenant_id, csv_content)

    assert len(partners) == 2
    assert partners[0].name == "Supplier X"
    assert partners[0].cnpj == "12345678000199"
    assert partners[0].type == "supplier"
    assert partners[1].name == "Customer Y"
    assert partners[1].cnpj == "98765432000188"
    assert partners[1].type == "customer"

    # Verify db.add calls
    assert mock_db.add.call_count == 2


@pytest.mark.asyncio
async def test_import_partners_csv_invalid_raises_error(mock_db):
    tenant_id = uuid.uuid4()
    
    # CSV with invalid type
    csv_content = "Name,Cnpj,Type\nBad Partner,12345678000199,invalid_type"
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    with pytest.raises(ValueError, match="Invalid partner type"):
        await MigrationService.import_partners_csv(mock_db, tenant_id, csv_content)


@pytest.mark.asyncio
async def test_import_bank_statement_ofx(mock_db):
    tenant_id = uuid.uuid4()
    ofx_content = """
    <OFX>
      <BANKMSGSRSV1>
        <STMTTRN>
          <TRNTYPE>DEBIT</TRNTYPE>
          <DTPOSTED>20260615120000</DTPOSTED>
          <TRNAMT>-150.00</TRNAMT>
          <FITID>tx-987654</FITID>
          <NAME>Supermarket Purchase</NAME>
          <MEMO>Weekly groceries</MEMO>
        </STMTTRN>
        <STMTTRN>
          <TRNTYPE>CREDIT</TRNTYPE>
          <DTPOSTED>20260616120000</DTPOSTED>
          <TRNAMT>1200.00</TRNAMT>
          <FITID>tx-987655</FITID>
          <NAME>Client Invoice Receipt</NAME>
        </STMTTRN>
      </BANKMSGSRSV1>
    </OFX>
    """
    
    # Mock FITID check: not existing
    mock_db.execute.return_value = MagicMock(scalar_one_or_none=lambda: None)

    txs = await MigrationService.import_bank_statement_ofx(mock_db, tenant_id, ofx_content)

    assert len(txs) == 2
    assert txs[0].fitid == "tx-987654"
    assert txs[0].amount == Decimal("-150.00")
    assert txs[0].transaction_date == date(2026, 6, 15)
    assert txs[0].description == "Supermarket Purchase - Weekly groceries"
    assert txs[0].reconciled is False

    assert txs[1].fitid == "tx-987655"
    assert txs[1].amount == Decimal("1200.00")
    assert txs[1].transaction_date == date(2026, 6, 16)
    assert txs[1].description == "Client Invoice Receipt"
    assert txs[1].reconciled is False

    assert mock_db.add.call_count == 2


# --- FastAPI Endpoint Integration Tests ---

from fastapi.testclient import TestClient
from app.main import app
from app.core.database import get_db
from app.core.security import get_current_tenant_and_user
from unittest.mock import patch

client = TestClient(app)
mock_tenant_id = uuid.uuid4()
mock_user_id = uuid.uuid4()

# Override security dependency to return our mock values
app.dependency_overrides[get_current_tenant_and_user] = lambda: (mock_tenant_id, mock_user_id)

@patch("app.routers.reporting.ReportingService")
def test_get_trial_balance_endpoint(mock_service):
    # Setup mock db session
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    # Setup mock service response
    mock_service.get_trial_balance = AsyncMock(return_value={"status": "mocked_tb"})

    headers = {"X-Tenant-ID": str(mock_tenant_id)}
    response = client.get(
        "/api/v1/reporting/trial-balance?start_date=2026-06-01&end_date=2026-06-30",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {"status": "mocked_tb"}
    app.dependency_overrides.pop(get_db, None)

@patch("app.routers.reporting.ReportingService")
def test_get_income_statement_endpoint(mock_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_service.get_income_statement = AsyncMock(return_value={"status": "mocked_dre"})

    headers = {"X-Tenant-ID": str(mock_tenant_id)}
    response = client.get(
        "/api/v1/reporting/income-statement?start_date=2026-06-01&end_date=2026-06-30",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {"status": "mocked_dre"}
    app.dependency_overrides.pop(get_db, None)

@patch("app.routers.reporting.ReportingService")
def test_get_ageing_endpoint(mock_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_service.get_ageing_report = AsyncMock(return_value={"status": "mocked_ageing"})

    headers = {"X-Tenant-ID": str(mock_tenant_id)}
    response = client.get(
        "/api/v1/reporting/ageing?ageing_type=AP&reference_date=2026-06-15",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json() == {"status": "mocked_ageing"}
    app.dependency_overrides.pop(get_db, None)

@patch("app.routers.migration.MigrationService")
def test_import_partners_endpoint(mock_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_partner = MagicMock()
    mock_partner.id = uuid.uuid4()
    mock_partner.name = "Partner 1"
    mock_partner.cnpj = "12345678000199"
    mock_partner.type = "both"

    mock_service.import_partners_csv = AsyncMock(return_value=[mock_partner])

    payload = {"csv_content": "name,cnpj,type\nPartner 1,12345678000199,both"}
    headers = {"X-Tenant-ID": str(mock_tenant_id)}

    response = client.post(
        "/api/v1/migration/partners/csv",
        json=payload,
        headers=headers
    )

    assert response.status_code == 201
    resp_json = response.json()
    assert resp_json["status"] == "success"
    assert len(resp_json["partners"]) == 1
    assert resp_json["partners"][0]["name"] == "Partner 1"
    
    mock_db.commit.assert_called_once()
    app.dependency_overrides.pop(get_db, None)

@patch("app.routers.migration.MigrationService")
def test_import_ofx_endpoint(mock_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_tx = MagicMock()
    mock_tx.id = uuid.uuid4()
    mock_tx.fitid = "tx-123"
    mock_tx.transaction_date = date(2026, 6, 15)
    mock_tx.amount = Decimal("-10.00")
    mock_tx.description = "Test Tx"
    mock_tx.reconciled = False

    mock_service.import_bank_statement_ofx = AsyncMock(return_value=[mock_tx])

    payload = {"ofx_content": "<OFX>...</OFX>"}
    headers = {"X-Tenant-ID": str(mock_tenant_id)}

    response = client.post(
        "/api/v1/migration/bank-statement/ofx",
        json=payload,
        headers=headers
    )

    assert response.status_code == 201
    resp_json = response.json()
    assert resp_json["status"] == "success"
    assert len(resp_json["transactions"]) == 1
    assert resp_json["transactions"][0]["fitid"] == "tx-123"
    
    mock_db.commit.assert_called_once()
    app.dependency_overrides.pop(get_db, None)

