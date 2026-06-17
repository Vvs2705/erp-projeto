import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from fiscal_engine.calculations import TaxEngine
from fiscal_engine.certificates import MockCertificateSigner
from fiscal_engine.nfe import generate_nfe_xml
from fiscal_engine.nfse import generate_nfse_xml

from app.core.database import get_db
from app.main import app

# Initialize TestClient
client = TestClient(app)


# 1. Test Tax Engine Calculations Before and After Jan/2026
def test_tax_engine_before_2026():
    """
    Taxes calculated before 2026-01-01 should NOT include CBS and IBS.
    """
    amount = Decimal("1000.00")
    issue_date = date(2025, 12, 31)

    # Test for product (is_service=False)
    taxes = TaxEngine.calculate_taxes(amount, issue_date, is_service=False)
    assert taxes["icms"] == Decimal("180.00")  # 18%
    assert taxes["ipi"] == Decimal("50.00")  # 5%
    assert taxes["pis"] == Decimal("16.50")  # 1.65%
    assert taxes["cofins"] == Decimal("76.00")  # 7.6%
    assert taxes["iss"] == Decimal("0.00")
    assert taxes["cbs"] == Decimal("0.00")  # No CBS before 2026
    assert taxes["ibs"] == Decimal("0.00")  # No IBS before 2026
    assert taxes["total_taxes"] == Decimal("322.50")

    # Test for service (is_service=True)
    taxes_service = TaxEngine.calculate_taxes(amount, issue_date, is_service=True)
    assert taxes_service["iss"] == Decimal("50.00")  # 5%
    assert taxes_service["pis"] == Decimal("16.50")  # 1.65%
    assert taxes_service["cofins"] == Decimal("76.00")  # 7.6%
    assert taxes_service["icms"] == Decimal("0.00")
    assert taxes_service["ipi"] == Decimal("0.00")
    assert taxes_service["cbs"] == Decimal("0.00")
    assert taxes_service["ibs"] == Decimal("0.00")
    assert taxes_service["total_taxes"] == Decimal("142.50")


def test_tax_engine_after_2026():
    """
    Taxes calculated on or after 2026-01-01 MUST include CBS (0.9%) and IBS (0.1%) highlight.
    """
    amount = Decimal("1000.00")
    issue_date = date(2026, 1, 1)

    # Test for product (is_service=False)
    taxes = TaxEngine.calculate_taxes(amount, issue_date, is_service=False)
    assert taxes["icms"] == Decimal("180.00")
    assert taxes["ipi"] == Decimal("50.00")
    assert taxes["pis"] == Decimal("16.50")
    assert taxes["cofins"] == Decimal("76.00")
    assert taxes["cbs"] == Decimal("9.00")  # 0.9% of 1000
    assert taxes["ibs"] == Decimal("1.00")  # 0.1% of 1000
    assert taxes["total_taxes"] == Decimal("332.50")

    # Test for service (is_service=True)
    taxes_service = TaxEngine.calculate_taxes(amount, issue_date, is_service=True)
    assert taxes_service["iss"] == Decimal("50.00")
    assert taxes_service["pis"] == Decimal("16.50")
    assert taxes_service["cofins"] == Decimal("76.00")
    assert taxes_service["cbs"] == Decimal("9.00")  # 0.9% of 1000
    assert taxes_service["ibs"] == Decimal("1.00")  # 0.1% of 1000
    assert taxes_service["total_taxes"] == Decimal("152.50")


# 2. Test Electronic Invoice (NF-e and NFS-e) XML Generation & Digital Signing
def test_nfe_xml_generation_and_signing():
    tx_id = "35260612345678901234550010000012341234567890"
    number = "1234"
    issuer_cnpj = "12345678000199"
    dest_cnpj = "98765432000188"
    amount = Decimal("500.00")
    issue_date = date(2026, 2, 15)

    taxes = TaxEngine.calculate_taxes(amount, issue_date, is_service=False)

    # Generate NF-e XML
    nfe_xml = generate_nfe_xml(
        tx_id=tx_id,
        number=number,
        issuer_cnpj=issuer_cnpj,
        dest_cnpj=dest_cnpj,
        amount=amount,
        taxes=taxes,
        issue_date=issue_date,
    )

    assert "NFe" in nfe_xml
    assert "<nNF>1234</nNF>" in nfe_xml
    assert f"<CNPJ>{issuer_cnpj}</CNPJ>" in nfe_xml
    assert f"<CNPJ>{dest_cnpj}</CNPJ>" in nfe_xml
    assert "<vCBS>4.50</vCBS>" in nfe_xml  # 0.9% of 500
    assert "<vIBS>0.50</vIBS>" in nfe_xml  # 0.1% of 500

    # Sign XML
    signer = MockCertificateSigner(pfx_data=b"dummy_cert_pfx", password="password123")
    signed_xml = signer.sign_xml(nfe_xml, tag_to_sign="infNFe")

    assert "<Signature" in signed_xml
    assert "<SignatureValue>" in signed_xml
    assert "MOCK_A1_CERTIFICATE_PUBLIC_KEY_DATA" in signed_xml


def test_nfse_xml_generation():
    tx_id = "999"
    number = "5678"
    issuer_cnpj = "12345678000199"
    dest_cnpj = "98765432000188"
    amount = Decimal("1200.00")
    issue_date = date(2026, 3, 20)

    taxes = TaxEngine.calculate_taxes(amount, issue_date, is_service=True)

    # Generate NFS-e XML
    nfse_xml = generate_nfse_xml(
        tx_id=tx_id,
        number=number,
        issuer_cnpj=issuer_cnpj,
        dest_cnpj=dest_cnpj,
        amount=amount,
        taxes=taxes,
        issue_date=issue_date,
    )

    assert "EnviarLoteRpsEnvio" in nfse_xml
    assert "<Numero>5678</Numero>" in nfse_xml
    assert f"<Cnpj>{issuer_cnpj}</Cnpj>" in nfse_xml
    assert "<ValorCBS>10.80</ValorCBS>" in nfse_xml  # 0.9% of 1200
    assert "<ValorIBS>1.20</ValorIBS>" in nfse_xml  # 0.1% of 1200


# 3. Test Webhook Endpoints Simulating Successful Liquidation of Invoice
@patch("integrations.banking.webhook_receiver.FinanceService")
def test_pix_webhook_liquidation_success(mock_finance_service):
    # 1. Setup mock database session
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    # 2. Setup mock Invoice
    mock_invoice = MagicMock()
    mock_invoice.id = uuid.uuid4()
    mock_invoice.status = "pending"
    mock_invoice.amount = Decimal("1000.00")
    mock_invoice.number = "INV-12345"

    # Mock lookup query execution
    # First: execute query for invoice (returns mock_invoice)
    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_invoice
    mock_db.execute.return_value = mock_execute_result

    # 3. Setup mock FinanceService payment return
    mock_payment = MagicMock()
    mock_payment.id = uuid.uuid4()
    mock_payment.journal_entry_id = uuid.uuid4()
    mock_finance_service.pay_invoice = AsyncMock(return_value=mock_payment)

    # 4. Perform POST request to Pix webhook receiver
    payload = {
        "event": "pix.completed",
        "txid": "INV-12345",
        "amount": "1000.0000",
        "payment_date": "2026-06-16",
        "tenant_id": str(uuid.uuid4()),
        "journal_id": str(uuid.uuid4()),
        "bank_account_id": str(uuid.uuid4()),
        "ar_account_id": str(uuid.uuid4()),
    }

    headers = {
        "X-Webhook-Token": "secret_webhook_token",
        "X-Tenant-ID": str(uuid.uuid4()),
    }

    response = client.post(
        "/api/v1/integrations/banking/webhook/pix", json=payload, headers=headers
    )

    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["status"] == "processed"
    assert "payment_id" in json_resp
    assert "journal_entry_id" in json_resp

    # Assert database operations
    mock_db.commit.assert_called_once()
    mock_db.rollback.assert_not_called()
    mock_finance_service.pay_invoice.assert_called_once()

    # Clean up dependency override
    app.dependency_overrides.pop(get_db, None)


@patch("integrations.banking.webhook_receiver.FinanceService")
def test_boleto_webhook_liquidation_success(mock_finance_service):
    # 1. Setup mock database session
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    # 2. Setup mock Invoice
    mock_invoice = MagicMock()
    mock_invoice.id = uuid.uuid4()
    mock_invoice.status = "pending"
    mock_invoice.amount = Decimal("850.00")
    mock_invoice.number = "3419999900085000"

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_invoice
    mock_db.execute.return_value = mock_execute_result

    # 3. Setup mock FinanceService payment return
    mock_payment = MagicMock()
    mock_payment.id = uuid.uuid4()
    mock_payment.journal_entry_id = uuid.uuid4()
    mock_finance_service.pay_invoice = AsyncMock(return_value=mock_payment)

    # 4. Perform POST request to Boleto webhook receiver
    payload = {
        "event": "boleto.paid",
        "our_number": "3419999900085000",
        "amount": "850.0000",
        "payment_date": "2026-06-16",
        "tenant_id": str(uuid.uuid4()),
        "journal_id": str(uuid.uuid4()),
        "bank_account_id": str(uuid.uuid4()),
        "ar_account_id": str(uuid.uuid4()),
    }

    headers = {"X-Webhook-Token": "secret_webhook_token"}

    response = client.post(
        "/api/v1/integrations/banking/webhook/boleto", json=payload, headers=headers
    )

    assert response.status_code == 200
    json_resp = response.json()
    assert json_resp["status"] == "processed"

    # Assert database operations
    mock_db.commit.assert_called_once()
    mock_db.rollback.assert_not_called()
    mock_finance_service.pay_invoice.assert_called_once()

    # Clean up dependency override
    app.dependency_overrides.pop(get_db, None)
