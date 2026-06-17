"""Central permission catalog and Segregation-of-Duties (SoD) rules.

Permission codes follow ``<domain>.<resource>.<action>``. This module is the
single source of truth: it is seeded into the ``permissions`` table and used to
enforce SoD when roles are assigned to a user.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class PermissionDef:
    code: str
    category: str
    description: str


PERMISSIONS: tuple[PermissionDef, ...] = (
    # Finance
    PermissionDef(
        "finance.journal.create", "finance", "Criar lançamentos contábeis (rascunho)"
    ),
    PermissionDef(
        "finance.journal.post", "finance", "Contabilizar (postar) lançamentos"
    ),
    PermissionDef("finance.period.close", "finance", "Fechar/trancar período fiscal"),
    PermissionDef("finance.bill.create", "finance", "Criar contas a pagar"),
    PermissionDef("finance.bill.pay", "finance", "Efetuar pagamento de contas a pagar"),
    PermissionDef("finance.invoice.create", "finance", "Criar contas a receber"),
    PermissionDef("finance.invoice.receive", "finance", "Baixar recebimentos"),
    PermissionDef("finance.report.read", "finance", "Ler relatórios financeiros"),
    # Procurement
    PermissionDef("purchase.order.create", "purchase", "Criar pedidos de compra"),
    PermissionDef("purchase.order.approve", "purchase", "Aprovar pedidos de compra"),
    PermissionDef(
        "purchase.receipt.create", "purchase", "Registrar recebimento de mercadoria"
    ),
    # Sales
    PermissionDef("sales.order.create", "sales", "Criar pedidos de venda"),
    PermissionDef("sales.order.approve", "sales", "Aprovar pedidos de venda"),
    PermissionDef("sales.shipment.create", "sales", "Expedir pedidos de venda"),
    # Inventory
    PermissionDef("inventory.movement.create", "inventory", "Movimentar estoque"),
    PermissionDef("inventory.read", "inventory", "Consultar estoque"),
    # Fiscal
    PermissionDef(
        "fiscal.document.issue", "fiscal", "Emitir documentos fiscais (DF-e)"
    ),
    PermissionDef("fiscal.document.cancel", "fiscal", "Cancelar documentos fiscais"),
    PermissionDef("fiscal.read", "fiscal", "Consultar documentos fiscais"),
    # Master data
    PermissionDef(
        "masterdata.partner.manage", "masterdata", "Gerenciar clientes e fornecedores"
    ),
    PermissionDef("masterdata.item.manage", "masterdata", "Gerenciar itens e produtos"),
    # Identity & access management
    PermissionDef("iam.user.manage", "iam", "Gerenciar usuários"),
    PermissionDef("iam.role.manage", "iam", "Gerenciar papéis e permissões"),
    PermissionDef("iam.audit.read", "iam", "Ler trilha de auditoria"),
)

ALL_PERMISSION_CODES: frozenset[str] = frozenset(p.code for p in PERMISSIONS)


# Segregation of Duties: each entry is a set of permissions that must NOT be
# held simultaneously by the same user (classic fraud-prevention controls).
SOD_CONFLICTS: tuple[tuple[frozenset[str], str], ...] = (
    (
        frozenset({"finance.bill.create", "finance.bill.pay"}),
        "Quem cria a conta a pagar não pode efetuar o pagamento.",
    ),
    (
        frozenset({"purchase.order.create", "purchase.order.approve"}),
        "Quem cria o pedido de compra não pode aprová-lo.",
    ),
    (
        frozenset({"sales.order.create", "sales.order.approve"}),
        "Quem cria o pedido de venda não pode aprová-lo.",
    ),
    (
        frozenset({"finance.journal.post", "finance.period.close"}),
        "Quem posta lançamentos não pode fechar o próprio período.",
    ),
    (
        frozenset({"iam.role.manage", "finance.bill.pay"}),
        "Quem administra papéis não pode também executar pagamentos.",
    ),
)


def find_sod_violations(granted: set[str]) -> list[str]:
    """Return human-readable reasons for any SoD conflicts present in ``granted``."""
    return [reason for combo, reason in SOD_CONFLICTS if combo <= granted]
