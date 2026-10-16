#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes das funções puras da lógica de ponto (máquina de estados + métricas).

TDD: estes testes foram escritos ANTES da implementação em logica.py.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from logica import (atraso_minutos, avaliar_qualidade_rosto, banco_horas,  # noqa: E402
                    calcular_faltas, calendario_mensal, dias_trabalho,
                    jornada_efetiva_seg, jornada_horario_seg, metricas_usuario,
                    proximo_tipo, relatorio_individual, resumo_colaborador,
                    validar_cpf, validar_nome)

AGORA = "2026-10-07 18:00:00"
JORNADA = 8 * 3600   # jornada padrão de 8h


# ---------- máquina de estados ----------

def test_proximo_tipo_inicio_sem_historico():
    assert proximo_tipo(None) == "entrada"


def test_proximo_tipo_sequencia_completa():
    assert proximo_tipo("entrada") == "pausa"
    assert proximo_tipo("pausa") == "volta"
    assert proximo_tipo("volta") == "termino"
    assert proximo_tipo("termino") == "entrada"   # recomeça o ciclo


def test_proximo_tipo_valor_desconhecido_vira_entrada():
    assert proximo_tipo("xyz") == "entrada"


# ---------- métricas do dia ----------

def test_metricas_sem_batidas():
    m = metricas_usuario("X", [], agora=AGORA)
    assert m["estado"] == "ausente"
    assert m["trabalho_seg"] == 0
    assert m["almoco_seg"] == 0
    assert m["batidas"] == 0


def test_metricas_somente_entrada_esta_presente():
    m = metricas_usuario("X", [("entrada", "2026-10-07 08:00:00")], agora=AGORA)
    assert m["estado"] == "presente"
    # das 08:00 às 18:00 = 10h
    assert m["trabalho_seg"] == 10 * 3600


def test_metricas_entrada_e_pausa_esta_em_pausa():
    m = metricas_usuario("X", [
        ("entrada", "2026-10-07 08:00:00"),
        ("pausa", "2026-10-07 12:00:00"),
    ], agora=AGORA)
    assert m["estado"] == "em pausa"
    # trabalho só do primeiro período: 08:00 -> 12:00 = 4h
    assert m["trabalho_seg"] == 4 * 3600


def test_metricas_dia_completo_encerrado():
    rows = [
        ("entrada", "2026-10-07 08:00:00"),
        ("pausa", "2026-10-07 12:00:00"),
        ("volta", "2026-10-07 13:00:00"),
        ("termino", "2026-10-07 17:00:00"),
    ]
    m = metricas_usuario("X", rows, agora=AGORA)
    assert m["estado"] == "encerrado"
    # (12-8) + (17-13) = 8h
    assert m["trabalho_seg"] == 8 * 3600
    # 13-12 = 1h
    assert m["almoco_seg"] == 1 * 3600
    assert m["entrada"] == "2026-10-07 08:00:00"
    assert m["termino"] == "2026-10-07 17:00:00"


def test_metricas_sem_pausa_encerrado():
    rows = [
        ("entrada", "2026-10-07 08:00:00"),
        ("termino", "2026-10-07 17:00:00"),
    ]
    m = metricas_usuario("X", rows, agora=AGORA)
    assert m["estado"] == "encerrado"
    assert m["trabalho_seg"] == 9 * 3600
    assert m["almoco_seg"] == 0


# ---------- resumo agregado do colaborador ----------

def test_resumo_colaborador_acumula_dias():
    pontos = [
        ("entrada", "2026-10-06 08:00:00"), ("termino", "2026-10-06 17:00:00"),
        ("entrada", "2026-10-07 09:00:00"), ("termino", "2026-10-07 18:00:00"),
    ]
    r = resumo_colaborador("X", pontos, agora=AGORA)
    assert r["dias"] == 2
    assert r["total_seg"] == 9 * 3600 * 2   # 9h em cada dia
    assert r["media_seg"] == 9 * 3600


def test_resumo_colaborador_sem_pontos():
    r = resumo_colaborador("X", [], agora=AGORA)
    assert r["dias"] == 0
    assert r["total_seg"] == 0


# ---------- validação de CPF ----------

def test_cpf_valido_com_mascara():
    assert validar_cpf("123.456.789-09") is True


def test_cpf_valido_sem_mascara():
    assert validar_cpf("12345678909") is True


def test_cpf_digito_errado():
    assert validar_cpf("123.456.789-00") is False


def test_cpf_todos_iguais_invalido():
    assert validar_cpf("111.111.111-11") is False


def test_cpf_curto_invalido():
    assert validar_cpf("123") is False


# ---------- banco de horas ----------

def test_banco_horas_positivo_extra():
    # 1 dia com 10h trabalhadas, jornada 8h -> +2h de banco
    pontos = [("entrada", "2026-10-07 08:00:00"), ("termino", "2026-10-07 18:00:00")]
    assert banco_horas(pontos, jornada_seg=JORNADA, agora=AGORA) == 2 * 3600


def test_banco_horas_negativo_deficit():
    # 1 dia com 6h, jornada 8h -> -2h de banco
    pontos = [("entrada", "2026-10-07 09:00:00"), ("termino", "2026-10-07 15:00:00")]
    assert banco_horas(pontos, jornada_seg=JORNADA, agora=AGORA) == -2 * 3600


def test_banco_horas_sem_pontos_zero():
    assert banco_horas([], jornada_seg=JORNADA, agora=AGORA) == 0


# ---------- relatório individual ----------

def test_relatorio_individual_totais():
    pontos = [
        ("entrada", "2026-10-06 08:00:00"), ("termino", "2026-10-06 18:00:00"),  # 10h, sem almoço
        ("entrada", "2026-10-07 09:00:00"), ("termino", "2026-10-07 15:00:00"),  # 6h, sem almoço
    ]
    r = relatorio_individual("X", pontos, jornada_seg=JORNADA, agora=AGORA)
    totais = r["totais"]
    assert totais["dias"] == 2
    assert totais["trabalhado_seg"] == 16 * 3600
    # CLT: +2h extra (dia 10h) + 1h almoço suprimido (dia 10h) + 1h almoço
    # suprimido (dia 6h, jornada esperada > 6h) = 4h extra
    assert totais["extra_seg"] == 4 * 3600
    assert totais["deficit_seg"] == 2 * 3600
    assert totais["banco_seg"] == 2 * 3600   # extra 4h - deficit 2h


def test_relatorio_individual_dias_detalhados():
    pontos = [("entrada", "2026-10-07 08:00:00"), ("termino", "2026-10-07 18:00:00")]
    r = relatorio_individual("X", pontos, jornada_seg=JORNADA, agora=AGORA)
    assert len(r["dias"]) == 1
    dia = r["dias"][0]
    assert dia["data"] == "2026-10-07"
    assert dia["trabalhado_seg"] == 10 * 3600
    assert dia["extra_seg"] == 3 * 3600   # +2h extra + 1h almoço suprimido
    assert dia["deficit_seg"] == 0


def test_relatorio_individual_sem_pontos():
    r = relatorio_individual("X", [], jornada_seg=JORNADA, agora=AGORA)
    assert r["totais"]["dias"] == 0
    assert r["totais"]["banco_seg"] == 0


def test_relatorio_dia_inclui_pausa_volta_almoco():
    pontos = [
        ("entrada", "2026-10-07 08:00:00"),
        ("pausa", "2026-10-07 12:00:00"),
        ("volta", "2026-10-07 13:00:00"),
        ("termino", "2026-10-07 17:00:00"),
    ]
    r = relatorio_individual("X", pontos, jornada_seg=JORNADA, agora=AGORA)
    dia = r["dias"][0]
    assert dia["pausa"] == "2026-10-07 12:00:00"
    assert dia["volta"] == "2026-10-07 13:00:00"
    assert dia["almoco_seg"] == 1 * 3600
    assert dia["trabalhado_seg"] == 8 * 3600


def test_relatorio_filtra_por_mes():
    pontos = [
        ("entrada", "2026-09-15 08:00:00"), ("termino", "2026-09-15 17:00:00"),
        ("entrada", "2026-10-07 08:00:00"), ("termino", "2026-10-07 17:00:00"),
    ]
    r = relatorio_individual("X", pontos, jornada_seg=JORNADA, agora=AGORA, mes="2026-10")
    assert len(r["dias"]) == 1
    assert r["dias"][0]["data"] == "2026-10-07"
    assert r["totais"]["dias"] == 1


# ---------- grupos, escala e faltas ----------

def test_dias_trabalho_semana_comercial():
    # 05/10 (seg) a 09/10 (sex) = 5 dias úteis
    dias = dias_trabalho([0, 1, 2, 3, 4], "2026-10-05", "2026-10-09")
    assert dias == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]


def test_dias_trabalho_respeita_fim_de_semana():
    # 05/10 (seg) a 11/10 (dom): só seg-sex entram
    dias = dias_trabalho([0, 1, 2, 3, 4], "2026-10-05", "2026-10-11")
    assert dias == ["2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08", "2026-10-09"]


def test_faltas_quando_nao_bateu_entrada():
    pontos = [("entrada", "2026-10-05 08:00:00"), ("termino", "2026-10-05 17:00:00")]
    faltas = calcular_faltas(pontos, [0, 1, 2, 3, 4], "2026-10-05", "2026-10-07")
    # trabalhou segunda (05); faltou terça (06) e quarta (07)
    assert faltas == ["2026-10-06", "2026-10-07"]


def test_faltas_vazia_quando_trabalhou_todos_os_dias():
    pontos = [
        ("entrada", "2026-10-05 08:00:00"), ("termino", "2026-10-05 17:00:00"),
        ("entrada", "2026-10-06 08:00:00"), ("termino", "2026-10-06 17:00:00"),
    ]
    faltas = calcular_faltas(pontos, [0, 1, 2, 3, 4], "2026-10-05", "2026-10-06")
    assert faltas == []


def test_faltas_ignora_dia_fora_da_escala():
    # grupo trabalha só segunda (0); sábado/domingo não são falta
    pontos = [("entrada", "2026-10-05 08:00:00"), ("termino", "2026-10-05 17:00:00")]
    faltas = calcular_faltas(pontos, [0], "2026-10-05", "2026-10-11")
    assert faltas == []


# ---------- validação de nome (anti path-traversal / XSS) ----------

def test_validar_nome_aceita_nome_normal():
    assert validar_nome("Rodrigo Brandão Correa") == "Rodrigo Brandão Correa"
    assert validar_nome("Anna Luisa Gomes") == "Anna Luisa Gomes"
    assert validar_nome("  João D'Ávila  ") == "João D'Ávila"   # faz strip


def test_validar_nome_rejeita_path_traversal():
    import pytest
    for malicioso in ["../embeddings/Vitima", "a/b", "a\\b", "..",
                      "nome\x00", "no\nme", "<script>"]:
        with pytest.raises(ValueError):
            validar_nome(malicioso)


def test_validar_nome_rejeita_tamanho_invalido():
    import pytest
    with pytest.raises(ValueError):
        validar_nome("a")          # curto demais
    with pytest.raises(ValueError):
        validar_nome("x" * 81)     # longo demais


# ---------- jornada real (horário contratual) ----------

def test_jornada_horario_seg_normal():
    assert jornada_horario_seg("08:00", "17:00") == 9 * 3600
    assert jornada_horario_seg("08:00", "17:30") == 9 * 3600 + 1800


def test_jornada_horario_seg_virada_meia_noite():
    assert jornada_horario_seg("22:00", "06:00") == 8 * 3600


def test_jornada_efetiva_desconta_almoco():
    assert jornada_efetiva_seg("08:00", "17:30", 90) == 8 * 3600          # 9h30 - 1h30 = 8h
    assert jornada_efetiva_seg("08:00", "14:00", 15) == 6 * 3600 - 15 * 60  # 6h - 15min
    assert jornada_efetiva_seg("08:00", "17:30") == 9 * 3600 + 30 * 60     # sem almoço = 9h30
    assert jornada_efetiva_seg("08:00", "14:00", 0) == 6 * 3600            # almoço 0 = 6h


def test_atraso_minutos():
    assert atraso_minutos("2026-10-08 08:12:00", "08:00") == 12   # atrasado
    assert atraso_minutos("2026-10-08 07:45:00", "08:00") == -15  # antecipado
    assert atraso_minutos("2026-10-08 08:00:00", "08:00") == 0    # pontual
    assert atraso_minutos("2026-10-08 12:05:00", "12:00") == 5    # estagiário da tarde


# ---------- calendário mensal (todos os dias) ----------

def test_calendario_mensal_todos_os_dias():
    # fevereiro/2024 (bissexto, 29 dias). 01/02/2024 é quinta-feira.
    pontos = [("entrada", "2024-02-01 08:00:00"), ("termino", "2024-02-01 17:00:00")]
    cal = calendario_mensal("Teste", pontos, [0, 1, 2, 3, 4], "2024-02",
                            agora="2024-02-29 12:00:00")
    assert len(cal) == 29
    s = {d["data"]: d["status"] for d in cal}
    assert s["2024-02-01"] == "trabalhado"
    assert s["2024-02-02"] == "falta"      # sexta, escala, sem batida
    assert s["2024-02-03"] == "folga"      # sábado
    assert s["2024-02-04"] == "folga"      # domingo
    assert s["2024-02-05"] == "falta"      # segunda, escala, sem batida


def test_calendario_mensal_dia_futuro_aguardando():
    pontos = [("entrada", "2024-02-01 08:00:00"), ("termino", "2024-02-01 17:00:00")]
    cal = calendario_mensal("Teste", pontos, [0, 1, 2, 3, 4], "2024-02",
                            agora="2024-02-10 12:00:00")
    s = {d["data"]: d["status"] for d in cal}
    assert s["2024-02-11"] == "folga"       # domingo
    assert s["2024-02-12"] == "aguardando"  # segunda, futuro
    assert s["2024-02-01"] == "trabalhado"
    assert s["2024-02-02"] == "falta"


# ---------- qualidade facial (det_score + pose) ----------

def test_qualidade_rosto_boa():
    ok, motivo = avaliar_qualidade_rosto(0.8, 5.0, 5.0, 5.0)
    assert ok is True
    assert motivo == ""


def test_qualidade_rosto_confianca_baixa():
    ok, motivo = avaliar_qualidade_rosto(0.3)
    assert ok is False
    assert "nítido" in motivo


def test_qualidade_rosto_nao_frontal():
    assert avaliar_qualidade_rosto(0.8, yaw=45)[0] is False
    assert avaliar_qualidade_rosto(0.8, pitch=-40)[0] is False
    assert avaliar_qualidade_rosto(0.8, roll=60)[0] is True   # roll não é critério



