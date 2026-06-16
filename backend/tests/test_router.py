import pytest
from fastapi.testclient import TestClient
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.core.database import get_db
from app.core.security import get_current_tenant_and_user

# Setup FastAPI test client
client = TestClient(app)

# Create fixed mock IDs
mock_tenant_id = uuid.uuid4()
mock_user_id = uuid.uuid4()

# Override security dependency to return our mock values
app.dependency_overrides[get_current_tenant_and_user] = lambda: (mock_tenant_id, mock_user_id)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}

def test_tenant_middleware_invalid_uuid():
    # Pass an invalid UUID format in header
    headers = {"X-Tenant-ID": "invalid-uuid"}
    response = client.get("/health", headers=headers)
    assert response.status_code == 400
    assert "Invalid X-Tenant-ID header format" in response.json()["detail"]

@patch("app.routers.finance.FinanceService")
def test_create_journal_entry_endpoint(mock_finance_service):
    # 1. Setup mock DB session
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    # 2. Setup mock data object (not awaited)
    mock_entry = MagicMock()
    mock_entry.id = uuid.uuid4()
    mock_entry.status = "draft"
    mock_entry.description = "Mock Entry Description"
    mock_entry.entry_date = date(2026, 6, 15)
    
    # 3. Setup mock coroutine call
    mock_finance_service.create_journal_entry = AsyncMock(return_value=mock_entry)

    # 4. Perform request
    payload = {
        "entry_date": "2026-06-15",
        "journal_id": str(uuid.uuid4()),
        "description": "Mock Entry Description",
        "lines": [
            {"account_id": str(uuid.uuid4()), "amount": "100.0000", "direction": "DEBIT"},
            {"account_id": str(uuid.uuid4()), "amount": "100.0000", "direction": "CREDIT"}
        ]
    }
    
    headers = {"X-Tenant-ID": str(mock_tenant_id)}
    response = client.post(
        "/api/v1/finance/ledger/journal-entries",
        json=payload,
        headers=headers
    )

    assert response.status_code == 201
    json_data = response.json()
    assert json_data["status"] == "draft"
    assert json_data["description"] == "Mock Entry Description"
    
    # Verify rollback was not called and commit was called
    mock_db.commit.assert_called_once()
    mock_db.rollback.assert_not_called()

    # Reset dependency override for db
    app.dependency_overrides.pop(get_db, None)

@patch("app.routers.finance.FinanceService")
def test_post_journal_entry_endpoint(mock_finance_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_entry = MagicMock()
    mock_entry.id = uuid.uuid4()
    mock_entry.status = "posted"
    
    mock_finance_service.post_journal_entry = AsyncMock(return_value=mock_entry)

    headers = {"X-Tenant-ID": str(mock_tenant_id)}
    entry_uuid = uuid.uuid4()
    response = client.post(
        f"/api/v1/finance/ledger/journal-entries/{entry_uuid}/post",
        headers=headers
    )

    assert response.status_code == 200
    assert response.json()["status"] == "posted"
    mock_db.commit.assert_called_once()

    app.dependency_overrides.pop(get_db, None)

@patch("app.routers.finance.FinanceService")
def test_create_bill_endpoint(mock_finance_service):
    mock_db = AsyncMock()
    app.dependency_overrides[get_db] = lambda: mock_db

    mock_bill = MagicMock()
    mock_bill.id = uuid.uuid4()
    mock_bill.provider_name = "Supplier Corp"
    mock_bill.number = "NF-555"
    mock_bill.amount = Decimal("250.0000")
    mock_bill.status = "pending"
    
    mock_finance_service.create_bill = AsyncMock(return_value=mock_bill)

    payload = {
        "legal_entity_id": str(uuid.uuid4()),
        "provider_name": "Supplier Corp",
        "cnpj": "12345678000199",
        "number": "NF-555",
        "amount": "250.0000",
        "issue_date": "2026-06-16",
        "due_date": "2026-07-16",
        "journal_id": str(uuid.uuid4()),
        "expense_account_id": str(uuid.uuid4()),
        "ap_account_id": str(uuid.uuid4())
    }

    headers = {"X-Tenant-ID": str(mock_tenant_id)}
    response = client.post(
        "/api/v1/finance/ap/bills",
        json=payload,
        headers=headers
    )

    assert response.status_code == 201
    assert response.json()["provider_name"] == "Supplier Corp"
    assert response.json()["status"] == "pending"

    app.dependency_overrides.pop(get_db, None)
