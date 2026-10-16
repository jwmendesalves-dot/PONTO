#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do liveness (anti-fraude) — TDD: escritos ANTES da implementação.

A função `decidir_liveness` interpreta a resposta da IA (agnes) e decide se a
batida é de uma pessoa viva ou uma fraude (print de tela, foto de foto, etc.).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from logica import decidir_liveness  # noqa: E402


def test_vivo_sem_fraude():
    r = decidir_liveness({"vivo": True, "fraude": "nenhuma", "motivo": ""})
    assert r["vivo"] is True
    assert r["motivo"] == ""


def test_vivo_campos_ausentes():
    # resposta minimalista de "tá vivo"
    r = decidir_liveness({"vivo": True})
    assert r["vivo"] is True


def test_fraude_print_de_tela():
    r = decidir_liveness({"vivo": False, "fraude": "print_tela",
                          "motivo": "brilho de tela visível"})
    assert r["vivo"] is False
    assert "print_tela" in r["motivo"]


def test_fraude_foto_de_foto():
    r = decidir_liveness({"vivo": False, "fraude": "foto_de_foto",
                          "motivo": "bordas de papel visíveis"})
    assert r["vivo"] is False
    assert "foto_de_foto" in r["motivo"]


def test_fraude_e_decisiva_mesmo_com_vivo_true():
    # a IA marcou vivo=true por engano, mas preencheu fraude — fraude vence
    r = decidir_liveness({"vivo": True, "fraude": "tela_com_foto", "motivo": ""})
    assert r["vivo"] is False


def test_vivo_false_sem_rotulo_de_fraude():
    r = decidir_liveness({"vivo": False, "fraude": "", "motivo": "rosto de lado"})
    assert r["vivo"] is False
    assert r["motivo"] == "rosto de lado"


def test_rotulo_nenhuma_normalizado():
    # variações de "nenhuma" não são fraude
    for rotulo in ("nenhuma", "NENHUMA", "none", "nao", "não", "false", "0"):
        r = decidir_liveness({"vivo": True, "fraude": rotulo, "motivo": ""})
        assert r["vivo"] is True, f"rotulo {rotulo!r} deveria passar"


def test_resposta_vazia_default_vivo():
    # se a IA devolver vazio, o fallback é considerar vivo (não bloqueia)
    r = decidir_liveness({})
    assert r["vivo"] is True
