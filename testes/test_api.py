#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes de integração da API (FastAPI TestClient), sem tocar no modelo facial."""
import os
import sys

# Configura o token de admin ANTES de importar o app (ADMIN_TOKEN é lido no import).
os.environ.setdefault("PONTO_ADMIN_TOKEN", "token-de-teste")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)
TOKEN = "token-de-teste"


def test_health():
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_colaboradores_retorna_lista():
    r = client.get("/api/colaboradores", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    assert "colaboradores" in r.json()


def test_cadastrar_sem_token_e_bloqueado():
    r = client.post("/api/cadastrar", json={"nome": "Teste", "foto_base64": "aGk="})
    assert r.status_code == 401


def test_cadastrar_token_errado_e_bloqueado():
    r = client.post("/api/cadastrar",
                    json={"nome": "Teste", "foto_base64": "aGk="},
                    headers={"X-Admin-Token": "errado"})
    assert r.status_code == 401


def test_metricas_retorna_campos_esperados():
    r = client.get("/api/metricas", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    body = r.json()
    assert "usuarios" in body and "presentes" in body and "total" in body


def test_pontos_retorna_lista():
    r = client.get("/api/pontos", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    assert "pontos" in r.json()


def test_resumo_retorna_lista():
    r = client.get("/api/resumo", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    assert "resumo" in r.json()


def test_auto_cadastro_cpf_invalido_e_recusado():
    r = client.post("/api/auto-cadastro",
                    json={"nome": "Teste", "cpf": "123", "foto_base64": "aGk="})
    assert r.status_code == 400


def test_relatorio_sem_token_e_bloqueado():
    r = client.get("/api/relatorio/fulano")
    assert r.status_code == 401

