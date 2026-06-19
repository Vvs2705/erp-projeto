"""Cliente HTTP real de emissão fiscal (transmissão DF-e via provedor).

A assinatura ICP-Brasil e a transmissão à SEFAZ/municípios são delegadas a um
provedor especializado (ex.: Focus NFe). Configurado por env
(``FISCAL_PROVIDER_URL`` / ``FISCAL_PROVIDER_TOKEN``). Sem configuração, levanta
``EmissionNotConfigured`` — nunca produz saída fictícia.
"""

from __future__ import annotations

import httpx
from fiscal_engine.determination import Regime, determine
from fiscal_engine.emission import (
    EmissionRequest,
    EmissionResult,
    build_provider_payload,
    total_amount,
)

from app.core.config import settings


class EmissionNotConfigured(RuntimeError):
    """Provedor de emissão fiscal não configurado."""


class EmissionError(RuntimeError):
    """Falha de comunicação ou processamento com o provedor."""


class FiscalEmissionClient:
    """Cliente do provedor de transmissão de documentos fiscais eletrônicos."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = (base_url or settings.FISCAL_PROVIDER_URL or "").rstrip("/")
        self._token = token or settings.FISCAL_PROVIDER_TOKEN
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._base_url and self._token)

    async def emit(
        self, request: EmissionRequest, regime: Regime = Regime.PRESUMIDO
    ) -> EmissionResult:
        if not self.configured:
            raise EmissionNotConfigured(
                "Emissão fiscal indisponível: configure FISCAL_PROVIDER_URL e "
                "FISCAL_PROVIDER_TOKEN."
            )
        taxes = determine(
            total_amount(request), request.issue_date, request.operation, regime
        )
        payload = build_provider_payload(request, taxes)
        headers = {"Authorization": f"Token token={self._token}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base_url}/v2/nfe", json=payload, headers=headers
                )
        except httpx.HTTPError as exc:
            raise EmissionError(f"Falha ao contatar o provedor: {exc}") from exc

        if response.status_code >= 400:
            raise EmissionError(
                f"Provedor retornou HTTP {response.status_code}: {response.text}"
            )
        data = response.json()
        raw: dict[str, object] = data if isinstance(data, dict) else {"response": data}
        return EmissionResult(
            provider="focus_nfe",
            status=str(raw.get("status", "processing")),
            protocol=_opt_str(raw.get("protocolo")),
            access_key=_opt_str(raw.get("chave_nfe")),
            raw=raw,
        )


def _opt_str(value: object) -> str | None:
    return None if value is None else str(value)
