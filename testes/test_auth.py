#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes de autenticação real (bcrypt + JWT).

TDD: escritos ANTES da implementação em auth.py / app.py.
"""
import os
import sys

# Configura o token de admin ANTES de importar o app (ADMIN_TOKEN é lido no import).
os.environ.setdefault("PONTO_ADMIN_TOKEN", "token-de-teste")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402

client = TestClient(app)

ADMIN_USUARIO = "admin"
ADMIN_SENHA = "jteI0p4anqBW9UgG"
X_ADMIN_TOKEN = "token-de-teste"


def _login(usuario=ADMIN_USUARIO, senha=ADMIN_SENHA):
    return client.post("/api/login", json={"usuario": usuario, "senha": senha})


# ---------- login ----------

def test_login_correto_retorna_token():
    r = _login()
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["usuario"] == ADMIN_USUARIO
    assert body["token"] and isinstance(body["token"], str)


def test_login_senha_errada_retorna_401():
    r = _login(senha="senha-errada")
    assert r.status_code == 401


def test_login_usuario_inexistente_retorna_401():
    r = _login(usuario="nao-existe")
    assert r.status_code == 401


def test_login_campos_faltando_retorna_422():
    r = client.post("/api/login", json={"usuario": "admin"})
    assert r.status_code == 422


# ---------- proteção dos endpoints admin ----------

def test_endpoint_admin_sem_token_retorna_401():
    r = client.post("/api/cadastrar", json={"nome": "X", "foto_base64": "aGk="})
    assert r.status_code == 401


def test_endpoint_admin_token_jwt_valido_acessa():
    token = _login().json()["token"]
    r = client.get("/api/relatorio/fulano",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200


def test_endpoint_admin_token_invalido_retorna_401():
    r = client.get("/api/relatorio/fulano",
                   headers={"Authorization": "Bearer token-invalido"})
    assert r.status_code == 401


def test_endpoint_admin_token_expirado_retorna_401():
    # cria um token JWT já expirado
    import time
    import jwt as pyjwt
    from auth import JWT_SECRET
    agora = int(time.time())
    token = pyjwt.encode(
        {"sub": ADMIN_USUARIO, "iat": agora, "exp": agora - 1},
        JWT_SECRET, algorithm="HS256")
    r = client.get("/api/relatorio/fulano",
                   headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# ---------- hash bcrypt (nunca texto puro) ----------

def test_hash_nao_e_texto_puro():
    import sqlite3
    from app import _db, DB
    con = _db()
    con.close()   # garantir_admin já commitou o admin se ele não existia
    # nova conexão independente prova que o hash está PERSISTIDO (não só em memória)
    con2 = sqlite3.connect(DB)
    row = con2.execute(
        "SELECT senha_hash FROM usuarios WHERE usuario=?", (ADMIN_USUARIO,)).fetchone()
    con2.close()
    assert row is not None
    assert row[0] != ADMIN_SENHA          # não guarda a senha em claro
    assert row[0].startswith("$2")        # prefixo de hash bcrypt ($2a/$2b/$2y)


def test_hash_bcrypt_valida_senha_correta():
    import bcrypt
    from app import _db
    con = _db()
    h = con.execute(
        "SELECT senha_hash FROM usuarios WHERE usuario=?", (ADMIN_USUARIO,)).fetchone()[0]
    con.close()
    assert bcrypt.checkpw(ADMIN_SENHA.encode(), h.encode()) is True
    assert bcrypt.checkpw(b"senha-errada", h.encode()) is False


# ---------- compatibilidade temporária (X-Admin-Token) ----------

def test_x_admin_token_ainda_funciona():
    r = client.get("/api/relatorio/fulano",
                   headers={"X-Admin-Token": X_ADMIN_TOKEN})
    assert r.status_code == 200


def test_x_admin_token_errado_retorna_401():
    r = client.get("/api/relatorio/fulano",
                   headers={"X-Admin-Token": "errado"})
    assert r.status_code == 401


# ---------- segredo JWT independente (não derivado de senha/token admin) ----------

def test_jwt_secret_nao_e_fallback_fixo():
    import hashlib
    from auth import JWT_SECRET
    assert JWT_SECRET != hashlib.sha256(b"ponto-facial-secret-padrao").hexdigest()


def test_jwt_secret_nao_deriva_da_senha_admin():
    import hashlib
    from auth import ADMIN_SENHA, JWT_SECRET
    assert JWT_SECRET != hashlib.sha256(ADMIN_SENHA.encode("utf-8")).hexdigest()


def test_jwt_secret_nao_deriva_do_admin_token():
    import hashlib
    from auth import JWT_SECRET
    assert JWT_SECRET != hashlib.sha256(os.environ["PONTO_ADMIN_TOKEN"].encode()).hexdigest()
