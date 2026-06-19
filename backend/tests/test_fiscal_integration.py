import asyncio
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from fiscal_engine.calculations import TaxEngine
from fiscal_engine.determination import Operation, determine
from fiscal_engine.emission import (
    EmissionRequest,
    Item,
    Party,
    build_provider_payload,
    total_amount,
)

from app.core.database import get_db
from app.main import app
from app.services.fiscal_emission import EmissionNotConfigured, FiscalEmissionClient

client = TestClient(app)


# 1. Determinação tributária (motor versionado) — antes e depois de 2026
def test_tax_engine_before_2026():
    amount = Decimal("1000.00")
    issue_date = date(2025, 12, 31)

    taxes = TaxEngine.calculate_taxes(amount, issue_date, is_service=False)
    assert taxes["icms"] == Decimal("180.00")
    assert taxes["ipi"] == Decimal("50.00")
    assert taxes["pis"] == Decimal("16.50")
    assert taxes["cofins"] == Decimal("76.00")
    assert taxes["iss"] == Decimal("0.00")
    assert taxes["cbs"] == Decimal("0.00")
    assert taxes["ibs"] == Decimal("0.00")
    assert taxes["total_taxes"] == Decimal("322.50")

    taxes_service = TaxEngine.calculate_taxes(amount, issue_date, is_service=True)
    assert taxes_service["iss"] == Decimal("50.00")
    assert taxes_service["pis"] == Decimal("16.50")
    assert taxes_service["cofins"] == Decimal("76.00")
    assert taxes_service["total_taxes"] == Decimal("142.50")


def test_tax_engine_after_2026():
    amount = Decimal("1000.00")
    issue_date = date(2026, 1, 1)

    taxes = TaxEngine.calculate_taxes(amount, issue_date, is_service=False)
    assert taxes["icms"] == Decimal("180.00")
    assert taxes["cbs"] == Decimal("9.00")  # 0,9%
    assert taxes["ibs"] == Decimal("1.00")  # 0,1%
    assert taxes["total_taxes"] == Decimal("332.50")

    taxes_service = TaxEngine.calculate_taxes(amount, issue_date, is_service=True)
    assert taxes_service["iss"] == Decimal("50.00")
    assert taxes_service["cbs"] == Decimal("9.00")
    assert taxes_service["ibs"] == Decimal("1.00")
    assert taxes_service["total_taxes"] == Decimal("152.50")


# 2. Emissão: montagem do payload do provedor (puro, sem rede/mocks)
def test_emission_payload_builder():
    req = EmissionRequest(
        issuer=Party(cnpj="12345678000199", name="Emissor SA"),
        recipient=Party(cnpj="98765432000188", name="Cliente SA"),
        operation=Operation.SALE_GOODS,
        issue_date=date(2026, 2, 15),
        nature="VENDA DE MERCADORIA",
        items=(
            Item(
                code="P1",
                description="Produto 1",
                ncm="12345678",
                cfop="5102",
                quantity=Decimal("2"),
                unit_value=Decimal("250.00"),
            ),
        ),
    )
    taxes = determine(total_amount(req), req.issue_date, req.operation)
    payload = build_provider_payload(req, taxes)

    assert payload["emitente"] == {"cnpj": "12345678000199", "nome": "Emissor SA"}
    assert payload["valor_total"] == "500.00"
    assert len(payload["itens"]) == 1
    assert "cbs" in payload["tributos"]  # 2026 -> RTC


# 3. Emissão sem provedor configurado: recusa com erro claro (nunca saída fake)
def test_emission_client_not_configured():
    req = EmissionRequest(
        issuer=Party(cnpj="12345678000199", name="E"),
        recipient=Party(cnpj="98765432000188", name="C"),
        operation=Operation.SALE_GOODS,
        issue_date=date(2026, 2, 15),
        nature="VENDA",
        items=(
            Item(
                code="P",
                description="P",
                ncm="1",
                cfop="5102",
                quantity=Decimal("1"),
                unit_value=Decimal("10.00"),
            ),
        ),
    )
    emission_client = FiscalEmissionClient(base_url=None, token=None)
    assert emission_client.configured is False
    with pytest.raises(EmissionNotConfigured):
        asyncio.run(emission_client.emit(req))


# 4. Webhooks bancários liquidando faturas (fluxo real do receiver)
@patch("integrations.banking.webhook_receiver.FinanceService")
def test_pix_webhook_liquidation_success(mock_finance_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_invoice = MagicMock()
    mock_invoice.id = uuid.uuid4()
    mock_invoice.status = "pending"
    mock_invoice.amount = Decimal("1000.00")
    mock_invoice.number = "INV-12345"

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_invoice
    mock_db.execute.return_value = mock_execute_result

    mock_payment = MagicMock()
    mock_payment.id = uuid.uuid4()
    mock_payment.journal_entry_id = uuid.uuid4()
    mock_finance_service.pay_invoice = AsyncMock(return_value=mock_payment)

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

    mock_db.commit.assert_called_once()
    mock_db.rollback.assert_not_called()
    mock_finance_service.pay_invoice.assert_called_once()

    app.dependency_overrides.pop(get_db, None)


@patch("integrations.banking.webhook_receiver.FinanceService")
def test_boleto_webhook_liquidation_success(mock_finance_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_invoice = MagicMock()
    mock_invoice.id = uuid.uuid4()
    mock_invoice.status = "pending"
    mock_invoice.amount = Decimal("850.00")
    mock_invoice.number = "3419999900085000"

    mock_execute_result = MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = mock_invoice
    mock_db.execute.return_value = mock_execute_result

    mock_payment = MagicMock()
    mock_payment.id = uuid.uuid4()
    mock_payment.journal_entry_id = uuid.uuid4()
    mock_finance_service.pay_invoice = AsyncMock(return_value=mock_payment)

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

    mock_db.commit.assert_called_once()
    mock_db.rollback.assert_not_called()
    mock_finance_service.pay_invoice.assert_called_once()

    app.dependency_overrides.pop(get_db, None)
