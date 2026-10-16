#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes de segurança: rate limiting, headers e limite de payload."""
import os
import sys

os.environ.setdefault("PONTO_ADMIN_TOKEN", "token-de-teste")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)


def test_headers_seguranca_presentes():
    r = client.get("/api/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"


def test_csp_permite_css_js_inline():
    # o dashboard usa <style> e <script> inline — a CSP não pode bloqueá-los
    r = client.get("/api/health")
    csp = r.headers.get("content-security-policy", "")
    assert "style-src 'self' 'unsafe-inline'" in csp
    assert "script-src 'self' 'unsafe-inline'" in csp


def test_payload_gigante_e_rejeitado_413():
    # 11 MB de dados na foto base64
    body = {"foto_base64": "a" * (11 * 1024 * 1024)}
    r = client.post("/api/reconhecer", json=body)
    assert r.status_code == 413


def test_endpoints_leitura_exigem_autenticacao():
    # PII (CPF/telefone) e geolocalização não podem ser públicos
    for rota in ["/api/colaboradores", "/api/pontos", "/api/metricas", "/api/resumo"]:
        r = client.get(rota)
        assert r.status_code == 401, f"{rota} deveria exigir autenticação"


def test_endpoints_leitura_com_token_acessam():
    token = client.post("/api/login", json={
        "usuario": "admin", "senha": "jteI0p4anqBW9UgG"}).json()["token"]
    for rota in ["/api/colaboradores", "/api/resumo"]:
        r = client.get(rota, headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200, f"{rota} deveria aceitar o token"


def test_login_rate_limit_apos_5_falhas_429():
    # 6 tentativas com senha errada -> as 5 primeiras 401, a 6ª 429
    statuses = []
    for _ in range(6):
        r = client.post("/api/login", json={"usuario": "teste-rate", "senha": "errada"})
        statuses.append(r.status_code)
    assert statuses[:5] == [401] * 5
    assert statuses[5] == 429
