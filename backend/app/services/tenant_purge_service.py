"""Purge definitivo de tenant (LGPD / offboarding) — operação privilegiada.

O direito ao esquecimento (LGPD) exige remover TODOS os dados de um tenant. Mas
os lançamentos contábeis postados são imutáveis por trigger (não podem sofrer
UPDATE/DELETE), o que bloqueia o ``DELETE`` em cascata do tenant. A saída segura
é executar a purga numa transação privilegiada com
``SET LOCAL session_replication_role = replica``: nesse modo os triggers de
origem (inclusive os de imutabilidade) e a verificação de FK ficam suspensos —
então removemos cada tabela tenant-scoped por ``tenant_id`` e, por fim, o tenant.

REQUISITOS:
- Conexão com papel PRIVILEGIADO (superusuário ou owner com replication): só ele
  pode ``SET session_replication_role``. O papel da aplicação é NOSUPERUSER e
  NÃO deve executar esta rotina no fluxo normal.
- Deve rodar DENTRO de uma transação (``async with engine.begin() as conn``),
  para que ``SET LOCAL`` seja revertido ao final e a purga seja atômica.

As tabelas tenant-scoped são descobertas pelo catálogo (toda tabela com coluna
``tenant_id``), então a rotina não precisa de manutenção quando o schema evolui.
"""

import re
import uuid

from sqlalchemy import column, delete, table, text
from sqlalchemy.ext.asyncio import AsyncConnection

# Nome de tabela/identificador válido no Postgres (defensivo, embora os nomes
# venham do catálogo e não de entrada do usuário).
_IDENT = re.compile(r"^[a-z_][a-z0-9_]*$")


class TenantPurgeError(RuntimeError):
    """Falha ao purgar um tenant."""


async def _tenant_scoped_tables(conn: AsyncConnection) -> list[str]:
    """Lista as tabelas-base do schema public que possuem coluna ``tenant_id``."""
    result = await conn.execute(
        text(
            "SELECT c.table_name "
            "FROM information_schema.columns c "
            "JOIN information_schema.tables t "
            "  ON t.table_schema = c.table_schema "
            " AND t.table_name = c.table_name "
            "WHERE c.table_schema = 'public' "
            "  AND c.column_name = 'tenant_id' "
            "  AND t.table_type = 'BASE TABLE' "
            "ORDER BY c.table_name"
        )
    )
    return [row[0] for row in result.all()]


async def purge_tenant(conn: AsyncConnection, tenant_id: uuid.UUID) -> dict[str, int]:
    """Apaga DEFINITIVAMENTE um tenant e todos os seus dados.

    Deve ser chamada com uma conexão privilegiada DENTRO de uma transação. Em
    modo ``replica`` os triggers de imutabilidade e a checagem de FK ficam
    suspensos; como a FK não é validada, a ordem de remoção é irrelevante.

    Devolve um mapa ``tabela -> linhas removidas`` (inclui ``tenants``).
    """
    if not conn.in_transaction():
        raise TenantPurgeError(
            "purge_tenant deve rodar dentro de uma transação "
            "(use 'async with engine.begin() as conn')."
        )

    await conn.execute(text("SET LOCAL session_replication_role = replica"))

    deleted: dict[str, int] = {}
    for table_name in await _tenant_scoped_tables(conn):
        if not _IDENT.match(table_name):  # pragma: no cover - defensivo
            raise TenantPurgeError(f"Nome de tabela inesperado: {table_name!r}")
        # Expressão SQLAlchemy: o identificador é citado com segurança pelo
        # dialeto e o tenant_id vai como parâmetro (sem SQL montado por string).
        tbl = table(table_name, column("tenant_id"))
        result = await conn.execute(delete(tbl).where(tbl.c.tenant_id == tenant_id))
        deleted[table_name] = result.rowcount

    tenants = table("tenants", column("id"))
    result = await conn.execute(delete(tenants).where(tenants.c.id == tenant_id))
    deleted["tenants"] = result.rowcount
    return deleted
