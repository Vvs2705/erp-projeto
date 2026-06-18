"""Testes do motor de determinação tributária versionado por vigência."""

from datetime import date
from decimal import Decimal

import pytest
from fiscal_engine.determination import (
    Operation,
    Regime,
    determine,
    select_rate_set,
)


def test_sem_cbs_ibs_antes_de_2026() -> None:
    r = determine(Decimal("1000.00"), date(2025, 12, 31), Operation.SALE_GOODS)
    d = r.as_dict()
    assert "cbs" not in d
    assert "ibs" not in d
    assert d["icms"] == Decimal("180.00")
    assert d["total_taxes"] == Decimal("322.50")


def test_cbs_ibs_a_partir_de_2026() -> None:
    r = determine(Decimal("1000.00"), date(2026, 1, 1), Operation.SALE_GOODS)
    d = r.as_dict()
    assert d["cbs"] == Decimal("9.00")  # 0,9%
    assert d["ibs"] == Decimal("1.00")  # 0,1%
    assert d["total_taxes"] == Decimal("332.50")


def test_servico_usa_iss_e_nao_icms() -> None:
    r = determine(Decimal("1000.00"), date(2026, 1, 1), Operation.SALE_SERVICE)
    d = r.as_dict()
    assert d["iss"] == Decimal("50.00")
    assert "icms" not in d
    assert "ipi" not in d


def test_simples_nao_destaca_pis_cofins() -> None:
    r = determine(
        Decimal("1000.00"), date(2026, 1, 1), Operation.SALE_GOODS, Regime.SIMPLES
    )
    d = r.as_dict()
    assert "pis" not in d
    assert "cofins" not in d
    assert d["icms"] == Decimal("180.00")


def test_arredondamento_half_up() -> None:
    # 333,33 * 0,009 (CBS) = 2,99997 -> 3,00
    r = determine(Decimal("333.33"), date(2026, 1, 1), Operation.SALE_GOODS)
    assert r.as_dict()["cbs"] == Decimal("3.00")


def test_base_negativa_rejeitada() -> None:
    with pytest.raises(ValueError):
        determine(Decimal("-1"), date(2026, 1, 1))


def test_vigencia_inexistente_para_data_antiga() -> None:
    with pytest.raises(ValueError):
        select_rate_set(date(1990, 1, 1))


def test_total_bate_com_soma_das_linhas() -> None:
    r = determine(Decimal("1000.00"), date(2026, 1, 1), Operation.SALE_GOODS)
    assert r.total_taxes == sum((ln.amount for ln in r.lines), Decimal("0.00"))
