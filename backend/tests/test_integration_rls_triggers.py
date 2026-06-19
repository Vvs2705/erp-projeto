"""Testes de INTEGRAÇÃO contra PostgreSQL real (RLS + triggers de imutabilidade).

O CI unitário roda em SQLite e NÃO cobre Row-Level Security nem triggers — foi
exatamente essa lacuna que deixou passar o bug do trigger (revertia updates).
Estes testes fecham a lacuna: rodam apenas quando ``TEST_PG_DSN`` aponta para um
Postgres com o schema migrado (``alembic upgrade head``).

Conectam como um papel NÃO-superusuário (superusuário ignora RLS) para provar o
isolamento de verdade.
"""

import asyncio
import os
import uuid
from collections.abc import Coroutine
from typing import Any, TypeVar

import asyncpg
import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from app.services.tenant_purge_service import purge_tenant

PG_DSN = os.environ.get("TEST_PG_DSN")
APP_ROLE = "erp_app_test"
APP_PASS = "erp_app_test_pwd"

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not PG_DSN, reason="requer Postgres real via TEST_PG_DSN"),
]

T = TypeVar("T")


def _run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _ensure_app_role(su: asyncpg.Connection) -> None:
    await su.execute(
        f"""
        DO $$ BEGIN
          IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
            CREATE ROLE {APP_ROLE} LOGIN PASSWORD '{APP_PASS}' NOSUPERUSER;
          END IF;
        END $$;
        """
    )
    await su.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    await su.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES "
        f"IN SCHEMA public TO {APP_ROLE}"
    )


async def _connect_app() -> asyncpg.Connection:
    assert PG_DSN is not None
    return await asyncpg.connect(dsn=PG_DSN, user=APP_ROLE, password=APP_PASS)


async def _rls_isolation() -> None:
    su = await asyncpg.connect(dsn=PG_DSN)
    t_a, t_b = uuid.uuid4(), uuid.uuid4()
    r_a, r_b = uuid.uuid4(), uuid.uuid4()
    try:
        await _ensure_app_role(su)
        await su.execute(
            "INSERT INTO tenants(id,name,slug,status,subscription_price,billing_limit,"
            "created_at,updated_at) VALUES "
            "($1,'A',$2,'active',0,0,now(),now()),($3,'B',$4,'active',0,0,now(),now())",
            t_a,
            f"rls-a-{t_a}",
            t_b,
            f"rls-b-{t_b}",
        )
        await su.execute(
            "INSERT INTO roles(id,tenant_id,name,is_system,created_at,updated_at) "
            "VALUES ($1,$2,'RoleA',false,now(),now()),($3,$4,'RoleB',false,now(),now())",
            r_a,
            t_a,
            r_b,
            t_b,
        )

        app = await _connect_app()
        try:
            # Tenant A vê apenas o seu papel.
            await app.execute(
                "SELECT set_config('app.current_tenant_id', $1, false)", str(t_a)
            )
            visible = {
                row["id"]
                for row in await app.fetch(
                    "SELECT id FROM roles WHERE id = ANY($1::uuid[])", [r_a, r_b]
                )
            }
            assert visible == {r_a}, f"vazou entre tenants: {visible}"

            # Tenant B vê apenas o seu papel.
            await app.execute(
                "SELECT set_config('app.current_tenant_id', $1, false)", str(t_b)
            )
            visible_b = {
                row["id"]
                for row in await app.fetch(
                    "SELECT id FROM roles WHERE id = ANY($1::uuid[])", [r_a, r_b]
                )
            }
            assert visible_b == {r_b}, f"vazou entre tenants: {visible_b}"

            # Sem tenant setado: nada é visível (deny by default).
            await app.execute("SELECT set_config('app.current_tenant_id', '', false)")
            visible_none = await app.fetch(
                "SELECT id FROM roles WHERE id = ANY($1::uuid[])", [r_a, r_b]
            )
            assert visible_none == [], f"deveria negar sem tenant: {visible_none}"
        finally:
            await app.close()
    finally:
        await su.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [t_a, t_b])
        await su.close()


async def _immutability_triggers() -> None:
    su = await asyncpg.connect(dsn=PG_DSN)
    t = uuid.uuid4()
    j = uuid.uuid4()
    e_draft = uuid.uuid4()
    e_posted = uuid.uuid4()
    try:
        await su.execute(
            "INSERT INTO tenants(id,name,slug,status,subscription_price,billing_limit,"
            "created_at,updated_at) VALUES ($1,'T',$2,'active',0,0,now(),now())",
            t,
            f"trg-{t}",
        )
        await su.execute(
            "INSERT INTO journals(id,tenant_id,name,code,created_at,updated_at) "
            "VALUES ($1,$2,'J','J1',now(),now())",
            j,
            t,
        )
        # Rascunho: postar deve PERSISTIR.
        await su.execute(
            "INSERT INTO journal_entries(id,tenant_id,entry_date,journal_id,description,"
            "status,created_at,updated_at) "
            "VALUES ($1,$2,current_date,$3,'d','draft',now(),now())",
            e_draft,
            t,
            j,
        )
        await su.execute(
            "UPDATE journal_entries SET status='posted' WHERE id=$1", e_draft
        )
        status = await su.fetchval(
            "SELECT status FROM journal_entries WHERE id=$1", e_draft
        )
        assert status == "posted", f"postar rascunho não persistiu: {status}"

        # Postado: editar deve FALHAR.
        await su.execute(
            "INSERT INTO journal_entries(id,tenant_id,entry_date,journal_id,description,"
            "status,created_at,updated_at) "
            "VALUES ($1,$2,current_date,$3,'orig','posted',now(),now())",
            e_posted,
            t,
            j,
        )
        with pytest.raises(asyncpg.PostgresError):
            await su.execute(
                "UPDATE journal_entries SET description='hack' WHERE id=$1", e_posted
            )
    finally:
        # Lançamentos postados são imutáveis (até via cascade), então a limpeza
        # desliga os triggers só nesta sessão (resetado ao fechar a conexão).
        await su.execute("SET session_replication_role = replica")
        await su.execute("DELETE FROM journal_entries WHERE tenant_id=$1", t)
        await su.execute("DELETE FROM journals WHERE tenant_id=$1", t)
        await su.execute("DELETE FROM tenants WHERE id=$1", t)
        await su.close()


async def _rls_fiscal_document_taxes() -> None:
    su = await asyncpg.connect(dsn=PG_DSN)
    t_a, t_b = uuid.uuid4(), uuid.uuid4()
    x_a, x_b = uuid.uuid4(), uuid.uuid4()
    try:
        await _ensure_app_role(su)
        await su.execute(
            "INSERT INTO tenants(id,name,slug,status,subscription_price,billing_limit,"
            "created_at,updated_at) VALUES "
            "($1,'A',$2,'active',0,0,now(),now()),($3,'B',$4,'active',0,0,now(),now())",
            t_a,
            f"fdt-a-{t_a}",
            t_b,
            f"fdt-b-{t_b}",
        )
        await su.execute(
            "INSERT INTO fiscal_document_taxes(id,tenant_id,document_type,document_id,"
            "document_number,direction,tax,base,rate,amount,issue_date,created_at) "
            "VALUES "
            "($1,$2,'sale',$3,'NF-A','debit','cbs',1000,0.009,9,current_date,now()),"
            "($4,$5,'sale',$6,'NF-B','debit','cbs',1000,0.009,9,current_date,now())",
            x_a,
            t_a,
            uuid.uuid4(),
            x_b,
            t_b,
            uuid.uuid4(),
        )

        app = await _connect_app()
        try:
            # Tenant A vê apenas o seu tributo.
            await app.execute(
                "SELECT set_config('app.current_tenant_id', $1, false)", str(t_a)
            )
            visible = {
                row["id"]
                for row in await app.fetch(
                    "SELECT id FROM fiscal_document_taxes WHERE id = ANY($1::uuid[])",
                    [x_a, x_b],
                )
            }
            assert visible == {x_a}, f"vazou entre tenants: {visible}"

            # Sem tenant setado: nada é visível (deny by default).
            await app.execute("SELECT set_config('app.current_tenant_id', '', false)")
            visible_none = await app.fetch(
                "SELECT id FROM fiscal_document_taxes WHERE id = ANY($1::uuid[])",
                [x_a, x_b],
            )
            assert visible_none == [], f"deveria negar sem tenant: {visible_none}"
        finally:
            await app.close()
    finally:
        await su.execute(
            "DELETE FROM fiscal_document_taxes WHERE tenant_id = ANY($1::uuid[])",
            [t_a, t_b],
        )
        await su.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", [t_a, t_b])
        await su.close()


def _sqlalchemy_url() -> str:
    assert PG_DSN is not None
    return PG_DSN.replace("postgresql://", "postgresql+asyncpg://", 1)


async def _purge_tenant_remove_tudo() -> None:
    su = await asyncpg.connect(dsn=PG_DSN)
    t_a, t_b = uuid.uuid4(), uuid.uuid4()
    acc, jrn, ent, line = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    fdt = uuid.uuid4()
    r_a, r_b = uuid.uuid4(), uuid.uuid4()
    try:
        await su.execute(
            "INSERT INTO tenants(id,name,slug,status,subscription_price,billing_limit,"
            "created_at,updated_at) VALUES "
            "($1,'A',$2,'active',0,0,now(),now()),($3,'B',$4,'active',0,0,now(),now())",
            t_a,
            f"purge-a-{t_a}",
            t_b,
            f"purge-b-{t_b}",
        )
        await su.execute(
            "INSERT INTO roles(id,tenant_id,name,is_system,created_at,updated_at) "
            "VALUES ($1,$2,'RoleA',false,now(),now()),($3,$4,'RoleB',false,now(),now())",
            r_a,
            t_a,
            r_b,
            t_b,
        )
        # Tenant A com lançamento POSTADO (imutável) — bloqueia o DELETE normal.
        await su.execute(
            "INSERT INTO accounts(id,tenant_id,code,name,type,nature,allow_posting,"
            "status,created_at,updated_at) "
            "VALUES ($1,$2,'1.1','Caixa','asset','debit',true,'active',now(),now())",
            acc,
            t_a,
        )
        await su.execute(
            "INSERT INTO journals(id,tenant_id,name,code,created_at,updated_at) "
            "VALUES ($1,$2,'J','J1',now(),now())",
            jrn,
            t_a,
        )
        await su.execute(
            "INSERT INTO journal_entries(id,tenant_id,entry_date,journal_id,"
            "description,status,created_at,updated_at) "
            "VALUES ($1,$2,current_date,$3,'e','posted',now(),now())",
            ent,
            t_a,
            jrn,
        )
        await su.execute(
            "INSERT INTO journal_lines(id,tenant_id,journal_entry_id,account_id,"
            "amount,direction,description,created_at,updated_at) "
            "VALUES ($1,$2,$3,$4,100,'DEBIT','l',now(),now())",
            line,
            t_a,
            ent,
            acc,
        )
        await su.execute(
            "INSERT INTO fiscal_document_taxes(id,tenant_id,document_type,document_id,"
            "document_number,direction,tax,base,rate,amount,issue_date,created_at) "
            "VALUES ($1,$2,'sale',$3,'NF-A','debit','cbs',1000,0.009,9,current_date,now())",
            fdt,
            t_a,
            uuid.uuid4(),
        )

        # O DELETE normal é bloqueado pelo trigger de imutabilidade (cascata).
        with pytest.raises(asyncpg.PostgresError):
            await su.execute("DELETE FROM tenants WHERE id=$1", t_a)

        # Purga privilegiada remove tudo do tenant A.
        engine = create_async_engine(_sqlalchemy_url())
        try:
            async with engine.begin() as conn:
                counts = await purge_tenant(conn, t_a)
        finally:
            await engine.dispose()

        assert counts["tenants"] == 1
        assert counts["journal_entries"] >= 1
        assert counts["journal_lines"] >= 1

        # Tenant A: nada sobra.
        assert (await su.fetchval("SELECT count(*) FROM tenants WHERE id=$1", t_a)) == 0
        assert (
            await su.fetchval(
                "SELECT count(*) FROM journal_entries WHERE tenant_id=$1", t_a
            )
        ) == 0
        assert (
            await su.fetchval(
                "SELECT count(*) FROM fiscal_document_taxes WHERE tenant_id=$1", t_a
            )
        ) == 0
        # Tenant B: intacto (sem dano colateral).
        assert (await su.fetchval("SELECT count(*) FROM roles WHERE id=$1", r_b)) == 1
    finally:
        # Limpeza resiliente: triggers off nesta sessão (resetado ao fechar).
        ids = [t_a, t_b]
        await su.execute("SET session_replication_role = replica")
        await su.execute(
            "DELETE FROM journal_lines WHERE tenant_id = ANY($1::uuid[])", ids
        )
        await su.execute(
            "DELETE FROM journal_entries WHERE tenant_id = ANY($1::uuid[])", ids
        )
        await su.execute("DELETE FROM journals WHERE tenant_id = ANY($1::uuid[])", ids)
        await su.execute("DELETE FROM accounts WHERE tenant_id = ANY($1::uuid[])", ids)
        await su.execute(
            "DELETE FROM fiscal_document_taxes WHERE tenant_id = ANY($1::uuid[])", ids
        )
        await su.execute("DELETE FROM roles WHERE tenant_id = ANY($1::uuid[])", ids)
        await su.execute("DELETE FROM tenants WHERE id = ANY($1::uuid[])", ids)
        await su.close()


def test_rls_isolation_entre_tenants() -> None:
    _run(_rls_isolation())


def test_imutabilidade_de_lancamentos_postados() -> None:
    _run(_immutability_triggers())


def test_rls_fiscal_document_taxes() -> None:
    _run(_rls_fiscal_document_taxes())


def test_purge_tenant_remove_tudo() -> None:
    _run(_purge_tenant_remove_tudo())
