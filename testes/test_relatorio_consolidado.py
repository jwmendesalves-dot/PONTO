#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes do Relatório Consolidado de Jornada & Ponto (REP-P, Portaria 671/2021)."""
import os
import sys

os.environ.setdefault("PONTO_ADMIN_TOKEN", "token-de-teste")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from db import conectar  # noqa: E402

client = TestClient(app)
TOKEN = "token-de-teste"

NOME = "Consolidado Teste"
MES = "2026-09"          # mês passado, determinístico (30 dias)
GRUPO = "Turno Consolidado"


def _preparar():
    con = conectar()
    try:
        con.execute("DELETE FROM grupo_membros WHERE colaborador=?", (NOME,))
        con.execute("DELETE FROM grupo_membros WHERE grupo_id IN "
                    "(SELECT id FROM grupos WHERE nome=?)", (GRUPO,))
        con.execute("DELETE FROM grupos WHERE nome=?", (GRUPO,))
        con.execute("DELETE FROM pontos WHERE colaborador=?", (NOME,))
        con.execute("DELETE FROM colaboradores WHERE nome=?", (NOME,))
        con.execute("INSERT INTO colaboradores (nome, cpf, telefone, criado_em) "
                    "VALUES (?, ?, ?, ?)", (NOME, "11144477735", "11999990000",
                                            "2026-01-10 10:00:00"))
        con.commit()
    finally:
        con.close()

    g = client.post("/api/grupos", headers={"X-Admin-Token": TOKEN},
                    json={"nome": GRUPO, "entrada": "08:00", "saida": "17:00",
                          "dias": [0, 1, 2, 3, 4], "almoco_min": 60}).json()
    r = client.put(f"/api/colaborador/{NOME}/vinculos", headers={"X-Admin-Token": TOKEN},
                   json={"grupo_id": g["id"]})
    assert r.status_code == 200

    # Dia 1 (terça): 8h->18h = 1h extra a 50%. Dia 2 (quarta): 8h exatas.
    batidas = [
        (f"{MES}-01 08:00:00", "entrada"), (f"{MES}-01 12:00:00", "pausa"),
        (f"{MES}-01 13:00:00", "volta"), (f"{MES}-01 18:00:00", "termino"),
        (f"{MES}-02 08:00:00", "entrada"), (f"{MES}-02 12:00:00", "pausa"),
        (f"{MES}-02 13:00:00", "volta"), (f"{MES}-02 17:00:00", "termino"),
    ]
    con = conectar()
    try:
        for quando, tipo in batidas:
            con.execute("INSERT INTO pontos (colaborador, quando, tipo) VALUES (?, ?, ?)",
                        (NOME, quando, tipo))
        con.commit()
    finally:
        con.close()


def test_relatorio_consolidado():
    _preparar()
    r = client.get(f"/api/relatorio/{NOME}/consolidado?mes={MES}",
                   headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    corpo = r.json()

    assert corpo["nome"] == NOME
    for campo in ("matricula", "quadro", "demonstrativo", "extrato"):
        assert campo in corpo

    assert len(corpo["extrato"]) == 30
    assert corpo["extrato"][0]["dia"] == "01"
    assert corpo["extrato"][0]["he50"].startswith("+")
    assert corpo["extrato"][0]["he50"] == "+01:00"
    assert corpo["quadro"]["extra50"] == "+01:00"
    assert corpo["quadro"]["dias_trabalhados"] == 2
    assert corpo["matricula"].startswith("MAT-2026-")


def test_relatorio_consolidado_sem_token_e_bloqueado():
    r = client.get(f"/api/relatorio/{NOME}/consolidado?mes={MES}")
    assert r.status_code == 401


def test_gerar_pdf_sem_token_bloqueado():
    r = client.post("/api/gerar-pdf", json={"html": "<!doctype html><html><body>ok</body></html>"})
    assert r.status_code == 401


def test_gerar_pdf_html_invalido():
    r = client.post("/api/gerar-pdf",
                    json={"html": "<script>alert(1)</script>"},
                    headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 400
