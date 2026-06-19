# backend

(Futuro) Modular monolith FastAPI. Um pacote Python por bounded context (org, masterdata, finance, procurement, sales, inventory, workflow). Imports entre contexts proibidos exceto via interfaces/eventos (outbox). NAO codificar antes do fecho do marco 20% (Architecture Gate).

## Emissão fiscal (DF-e)

A determinação dos tributos é feita pelo motor próprio (`fiscal-engine`,
versionado por vigência). A **assinatura ICP-Brasil** e a **transmissão à
SEFAZ/municípios** são delegadas a um provedor especializado (ex.: Focus NFe /
PlugNotas) via `FiscalEmissionClient` (`app/services/fiscal_emission.py`).

Configure por variável de ambiente (nunca commitar segredos):

| Variável | Obrigatória | Descrição |
|---|---|---|
| `FISCAL_PROVIDER_URL` | sim (para emitir) | URL base da API do provedor DF-e (ex.: `https://api.focusnfe.com.br`). |
| `FISCAL_PROVIDER_TOKEN` | sim (para emitir) | Token de autenticação do provedor (enviado como `Authorization: Token token=<TOKEN>`). |

Sem **ambas** configuradas, `emit()` levanta `EmissionNotConfigured` — a emissão
é recusada com erro claro, **nunca** produz saída fictícia. A integração
ponta-a-ponta com a SEFAZ só ocorre quando há conta ativa no provedor.

### Outras variáveis relevantes

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | local docker | DSN async do PostgreSQL (`postgresql+asyncpg://...`). |
| `SECRET_KEY` | dev inseguro | Chave de assinatura JWT — **trocar em produção**. |
| `SENTRY_DSN` | vazio | Sentry (no-op se ausente). |
| `OTEL_EXPORTER_OTLP_ENDPOINT` / `OTEL_ENABLED` | vazio / `false` | OpenTelemetry (no-op se desabilitado). |