"""Testes da emissão fiscal: builder do payload + cliente do provedor.

Não chamam SEFAZ nem provedor real — o ``httpx.AsyncClient`` é substituído por
um fake. Cobrem: montagem do payload neutro, propriedade ``configured``, recusa
sem configuração e os caminhos de sucesso/erro HTTP/erro de rede do ``emit``.
"""

from datetime import date
from decimal import Decimal

import httpx
import pytest
from fiscal_engine import (
    EmissionRequest,
    Item,
    Operation,
    Party,
    Regime,
    build_provider_payload,
    determine,
    total_amount,
)

from app.core.config import settings
from app.services.fiscal_emission import (
    EmissionError,
    EmissionNotConfigured,
    FiscalEmissionClient,
)

# 2026: vigência com CBS/IBS ativos.
ISSUE_DATE = date(2026, 6, 15)


def _request() -> EmissionRequest:
    return EmissionRequest(
        issuer=Party(cnpj="12345678000199", name="Emitente LTDA"),
        recipient=Party(cnpj="98765432000188", name="Destinatário SA"),
        operation=Operation.SALE_GOODS,
        issue_date=ISSUE_DATE,
        nature="Venda de mercadoria",
        items=(
            Item(
                code="P1",
                description="Produto 1",
                ncm="12345678",
                cfop="5102",
                quantity=Decimal("2"),
                unit_value=Decimal("100.00"),
            ),
        ),
    )


class _FakeAsyncClient:
    """Substitui httpx.AsyncClient: captura a requisição e devolve/raise."""

    def __init__(
        self,
        response: httpx.Response | None = None,
        exc: Exception | None = None,
        captured: dict[str, object] | None = None,
        **kwargs: object,
    ) -> None:
        self._response = response
        self._exc = exc
        self._captured = captured

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False

    async def post(
        self,
        url: str,
        json: object = None,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        if self._captured is not None:
            self._captured.update(url=url, json=json, headers=headers)
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response: httpx.Response | None = None,
    exc: Exception | None = None,
    captured: dict[str, object] | None = None,
) -> None:
    def factory(**kwargs: object) -> _FakeAsyncClient:
        return _FakeAsyncClient(response=response, exc=exc, captured=captured)

    monkeypatch.setattr(httpx, "AsyncClient", factory)


# ── Builder (funções puras) ──────────────────────────────────────────────────


def test_total_amount_soma_itens() -> None:
    assert total_amount(_request()) == Decimal("200.00")


def test_item_total() -> None:
    item = Item(
        code="X",
        description="d",
        ncm="1",
        cfop="5102",
        quantity=Decimal("3"),
        unit_value=Decimal("10.50"),
    )
    assert item.total == Decimal("31.50")


def test_build_provider_payload_estrutura() -> None:
    request = _request()
    taxes = determine(
        total_amount(request), request.issue_date, request.operation, Regime.PRESUMIDO
    )
    payload = build_provider_payload(request, taxes)

    assert payload["operacao"] == "sale_goods"
    assert payload["natureza_operacao"] == "Venda de mercadoria"
    assert payload["data_emissao"] == "2026-06-15"
    assert payload["emitente"] == {"cnpj": "12345678000199", "nome": "Emitente LTDA"}
    assert payload["valor_total"] == "200.00"

    itens = payload["itens"]
    assert isinstance(itens, list) and len(itens) == 1
    assert itens[0]["valor_total"] == "200.00"
    assert itens[0]["cfop"] == "5102"

    tributos = payload["tributos"]
    assert isinstance(tributos, dict)
    # RTC ativa em 2026 + mercadoria/presumido.
    assert "cbs" in tributos and "ibs" in tributos and "icms" in tributos
    assert "total_taxes" in tributos


# ── Cliente do provedor ──────────────────────────────────────────────────────


def test_configured_property() -> None:
    assert FiscalEmissionClient(base_url="https://api.x", token="t").configured is True


@pytest.mark.asyncio
async def test_emit_sem_configuracao_recusa(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "FISCAL_PROVIDER_URL", None)
    monkeypatch.setattr(settings, "FISCAL_PROVIDER_TOKEN", None)
    client = FiscalEmissionClient()
    assert client.configured is False
    with pytest.raises(EmissionNotConfigured):
        await client.emit(_request())


@pytest.mark.asyncio
async def test_emit_sucesso(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}
    response = httpx.Response(
        200,
        json={"status": "autorizado", "protocolo": "P123", "chave_nfe": "NFe42"},
    )
    _patch_client(monkeypatch, response=response, captured=captured)

    client = FiscalEmissionClient(base_url="https://api.test/", token="tok")
    result = await client.emit(_request())

    assert result.provider == "focus_nfe"
    assert result.status == "autorizado"
    assert result.protocol == "P123"
    assert result.access_key == "NFe42"

    # Requisição montada corretamente.
    assert str(captured["url"]).endswith("/v2/nfe")
    headers = captured["headers"]
    assert isinstance(headers, dict)
    assert headers["Authorization"] == "Token token=tok"
    body = captured["json"]
    assert isinstance(body, dict)
    assert "cbs" in body["tributos"]


@pytest.mark.asyncio
async def test_emit_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(422, text="dados invalidos")
    _patch_client(monkeypatch, response=response)

    client = FiscalEmissionClient(base_url="https://api.test", token="tok")
    with pytest.raises(EmissionError) as exc_info:
        await client.emit(_request())
    assert "422" in str(exc_info.value)


@pytest.mark.asyncio
async def test_emit_erro_de_rede(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_client(monkeypatch, exc=httpx.ConnectError("boom"))

    client = FiscalEmissionClient(base_url="https://api.test", token="tok")
    with pytest.raises(EmissionError) as exc_info:
        await client.emit(_request())
    assert "Falha ao contatar" in str(exc_info.value)


@pytest.mark.asyncio
async def test_emit_resposta_nao_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    response = httpx.Response(200, json=[1, 2, 3])
    _patch_client(monkeypatch, response=response)

    client = FiscalEmissionClient(base_url="https://api.test", token="tok")
    result = await client.emit(_request())
    assert result.status == "processing"
    assert result.raw == {"response": [1, 2, 3]}
