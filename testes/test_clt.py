# -*- coding: utf-8 -*-
"""TDD — regras CLT e apuração de jornada (porte do PontoBio para o ponto).

Testa o módulo PURO `clt.py`: adicional noturno (Art. 73), hora extra 50%/100%
(Art. 59 e 59-B), tolerância diária (Art. 58 §1º), intervalo intrajornada
suprimido (Art. 71 §4º) e teto de extras. Portado do `timeCalculation.ts` e
`cltRulesService.ts` do PontoBio (valores e artigos da CLT preservados).
"""
import sys

sys.path.insert(0, "/opt/ponto")

import clt  # noqa: E402


# ---------------------------------------------------------------------------
# Adicional noturno (22h às 5h, fator hora ficta 60/52.5 — Art. 73 CLT)
# ---------------------------------------------------------------------------
def test_noturno_dentro_da_faixa_22_23():
    # 22:00 -> 23:00 = 60 min reais * (60/52.5) = 68.57 -> 69 min noturnos
    assert clt.minutos_noturnos("2026-01-01 22:00:00", "2026-01-01 23:00:00") == 69


def test_noturno_diurno_vale_zero():
    assert clt.minutos_noturnos("2026-01-01 08:00:00", "2026-01-01 17:00:00") == 0


def test_noturno_atravessa_meia_noite():
    # 23:00 -> 06:00: 1h (23-24) + 5h (00-05) = 6h = 360 min * fator = 411
    assert clt.minutos_noturnos("2026-01-01 23:00:00", "2026-01-02 06:00:00") == 411


def test_noturno_inicio_apos_fim_vale_zero():
    assert clt.minutos_noturnos("2026-01-02 06:00:00", "2026-01-01 23:00:00") == 0


# ---------------------------------------------------------------------------
# Apuração diária CLT
# ---------------------------------------------------------------------------
def _batidas(entrada, pausa=None, volta=None, termino=None):
    rows = [("entrada", entrada)]
    if pausa:
        rows.append(("pausa", pausa))
    if volta:
        rows.append(("volta", volta))
    if termino:
        rows.append(("termino", termino))
    return rows


def test_dia_normal_sem_extra():
    # 08:00 -> 12:00 (pausa) 13:00 -> 17:00 = 8h = 480 min, jornada 480
    b = _batidas("2026-01-05 08:00:00", "2026-01-05 12:00:00",
                 "2026-01-05 13:00:00", "2026-01-05 17:00:00")
    r = clt.apurar_dia(b, 480, dia_util=True)
    assert r["status"] == "NORMAL"
    assert r["regular_min"] == 480
    assert r["extra_50_min"] == 0
    assert r["extra_100_min"] == 0
    assert r["deficit_min"] == 0


def test_hora_extra_50_acima_da_tolerancia():
    # trabalhou 510 min (30 min além), tolerância 10 -> extra 50% = 30 min
    b = _batidas("2026-01-05 08:00:00", "2026-01-05 12:00:00",
                 "2026-01-05 13:00:00", "2026-01-05 17:30:00")
    r = clt.apurar_dia(b, 480, dia_util=True)
    assert r["status"] == "OVERTIME"
    assert r["extra_50_min"] == 30


def test_dentro_da_tolerancia_nao_gera_extra():
    # trabalhou 490 min (10 min além) = dentro da tolerância -> sem extra
    b = _batidas("2026-01-05 08:00:00", "2026-01-05 12:00:00",
                 "2026-01-05 13:00:00", "2026-01-05 17:10:00")
    r = clt.apurar_dia(b, 480, dia_util=True)
    assert r["status"] == "NORMAL"
    assert r["extra_50_min"] == 0


def test_deficit_quando_trabalha_menos():
    # trabalhou 460 min (20 min a menos) -> deficit 20
    b = _batidas("2026-01-05 08:00:00", "2026-01-05 12:00:00",
                 "2026-01-05 13:00:00", "2026-01-05 16:40:00")
    r = clt.apurar_dia(b, 480, dia_util=True)
    assert r["status"] == "DEFICIT"
    assert r["deficit_min"] == 20


def test_folga_com_trabalho_vira_extra_100():
    # dia de folga/DSR trabalhado -> 100% (Art. 59-B)
    b = _batidas("2026-01-04 08:00:00", None, None, "2026-01-04 10:00:00")
    r = clt.apurar_dia(b, 0, dia_util=False)
    assert r["status"] == "OVERTIME"
    assert r["extra_100_min"] == 120


def test_almoco_suprimido_gera_indenizacao_50():
    # jornada > 6h, almoço batido 30 min (< 60 obrigatório) -> 30 min indenizados 50%
    b = _batidas("2026-01-05 08:00:00", "2026-01-05 12:30:00",
                 "2026-01-05 13:00:00", "2026-01-05 17:00:00")
    # trabalhou: 08-12:30 (4.5h) + 13-17 (4h) = 8.5h = 510 min; almoço 30 min
    r = clt.apurar_dia(b, 480, dia_util=True)
    assert r["almoco_suprimido_min"] == 30
    assert r["extra_50_min"] >= 30  # extra normal + indenização do almoço


def test_teto_de_extra_diaria_sinaliza():
    # trabalhou 150 min além (acima do teto 120) -> is_teto_excedido
    b = _batidas("2026-01-05 08:00:00", "2026-01-05 12:00:00",
                 "2026-01-05 13:00:00", "2026-01-05 19:30:00")
    # 08-12 (4h) + 13-19:30 (6.5h) = 10.5h = 630 min; extra = 150 min
    r = clt.apurar_dia(b, 480, dia_util=True)
    assert r["extra_50_min"] == 150
    assert r["teto_excedido"] is True
    assert r["teto_excedido_min"] == 30


# ---------------------------------------------------------------------------
# Fechamento mensal (espelho de ponto)
# ---------------------------------------------------------------------------
def test_fechamento_mensal_totaliza():
    batidas = [
        ("entrada", "2026-01-05 08:00:00"), ("pausa", "2026-01-05 12:00:00"),
        ("volta", "2026-01-05 13:00:00"), ("termino", "2026-01-05 17:00:00"),
        ("entrada", "2026-01-06 08:00:00"), ("pausa", "2026-01-06 12:00:00"),
        ("volta", "2026-01-06 13:00:00"), ("termino", "2026-01-06 17:00:00"),
    ]
    r = clt.fechamento_mensal(batidas, 480, [0, 1, 2, 3, 4], "2026-01")
    assert r["totais"]["dias"] == 2
    assert r["totais"]["trabalhado_min"] == 960
    assert r["totais"]["extra_50_min"] == 0
    assert r["totais"]["deficit_min"] == 0
    assert r["totais"]["banco_min"] == 0


def test_fechamento_mensal_banco_extras_menos_deficit():
    # dia 5: extra 30min; dia 6: deficit 20min -> banco = 30 - 20 = 10
    batidas = [
        ("entrada", "2026-01-05 08:00:00"), ("pausa", "2026-01-05 12:00:00"),
        ("volta", "2026-01-05 13:00:00"), ("termino", "2026-01-05 17:30:00"),
        ("entrada", "2026-01-06 08:00:00"), ("pausa", "2026-01-06 12:00:00"),
        ("volta", "2026-01-06 13:00:00"), ("termino", "2026-01-06 16:40:00"),
    ]
    r = clt.fechamento_mensal(batidas, 480, [0, 1, 2, 3, 4], "2026-01")
    assert r["totais"]["extra_50_min"] == 30
    assert r["totais"]["deficit_min"] == 20
    assert r["totais"]["banco_min"] == 10


# ---------------------------------------------------------------------------
# Interjornada (Art. 66) e teto semanal (Art. 59)
# ---------------------------------------------------------------------------
def test_interjornada_min_entre_jornadas():
    assert clt.interjornada_min("2026-10-12 22:00:00", "2026-10-13 08:00:00") == 10 * 60
    assert clt.interjornada_min("2026-10-12 21:00:00", "2026-10-13 08:00:00") == 11 * 60


def test_interjornada_insuficiente_e_sinalizada():
    batidas = [
        ("entrada", "2026-10-12 08:00:00"), ("pausa", "2026-10-12 12:00:00"),
        ("volta", "2026-10-12 13:00:00"), ("termino", "2026-10-12 22:00:00"),
        ("entrada", "2026-10-13 08:00:00"), ("pausa", "2026-10-13 12:00:00"),
        ("volta", "2026-10-13 13:00:00"), ("termino", "2026-10-13 17:00:00"),
    ]
    r = clt.fechamento_mensal(batidas, 480, [0, 1, 2, 3, 4], "2026-10")
    dia13 = next(d for d in r["dias"] if d["data"] == "2026-10-13")
    assert dia13["interjornada_min"] == 10 * 60
    assert dia13["interjornada_insuficiente"] is True
    assert r["totais"]["interjornadas_insuficientes"] == 1


def test_teto_semanal_excedido_e_sinalizado():
    # 6 dias com 2h extra cada = 720min na semana > teto de 600min (Art. 59).
    batidas = []
    for dia in ("12", "13", "14", "15", "16", "17"):
        batidas += [("entrada", f"2026-10-{dia} 08:00:00"), ("pausa", f"2026-10-{dia} 12:00:00"),
                    ("volta", f"2026-10-{dia} 13:00:00"), ("termino", f"2026-10-{dia} 19:00:00")]
    r = clt.fechamento_mensal(batidas, 480, [0, 1, 2, 3, 4, 5], "2026-10")
    assert r["totais"]["teto_semanal_excedido"] is True   # 6 * 120min = 720min > 600min
