#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Autenticação real do ponto: senha com hash bcrypt + sessão JWT.

Sem dependência de FastAPI ou do modelo facial — funções puras, testáveis.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import bcrypt
import jwt

# Segredo usado para assinar os tokens. Prioridade: env PONTO_JWT_SECRET >
# arquivo persistente /opt/ponto/jwt-secret.txt (gerado na 1ª execução) >
# geração aleatória. NUNCA deriva da senha admin nem usa fallback fixo
# (segredo conhecido permitiria forjar tokens). Trocar o segredo invalida
# todos os tokens emitidos anteriormente.
def _carregar_jwt_secret() -> str:
    v = os.environ.get("PONTO_JWT_SECRET", "").strip()
    if v:
        return v
    arq = Path("/opt/ponto/jwt-secret.txt")
    try:
        v = arq.read_text(encoding="utf-8").strip()
        if v:
            return v
    except OSError:
        pass
    import secrets
    v = secrets.token_hex(32)
    arq.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(arq, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        try:
            existente = arq.read_text(encoding="utf-8").strip()
        except OSError:
            existente = ""
        return existente or v
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(v)
    return v


JWT_SECRET = _carregar_jwt_secret()

TOKEN_TTL_SEG = 12 * 3600   # 12 horas

ADMIN_USUARIO = "admin"
# Senha do admin só na PRIMEIRA criação do usuário (depois o login usa o hash
# bcrypt no banco). Obrigatória via env — sem ela o admin não é criado (fail-closed).
ADMIN_SENHA = os.environ.get("PONTO_ADMIN_SENHA", "").strip()


def hash_senha(senha: str) -> str:
    """Gera um hash bcrypt (com salt aleatório) da senha."""
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha: str, senha_hash: str) -> bool:
    """Compara a senha em claro com o hash bcrypt armazenado."""
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), senha_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def criar_token(usuario: str, ttl_seg: int = TOKEN_TTL_SEG) -> str:
    """Emite um JWT HS256 assinado, com expiração (default 12h)."""
    agora = int(time.time())
    payload = {"sub": usuario, "iat": agora, "exp": agora + ttl_seg}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def token_valido(token: str) -> bool:
    """Valida assinatura + expiração de um JWT (True se íntegro e não expirado)."""
    try:
        jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return True
    except jwt.PyJWTError:
        return False


def garantir_admin(con) -> None:
    """Cria o usuário admin padrão na primeira execução.

    A tabela `usuarios` é criada pelo schema em db.py — aqui só garantimos que
    o admin existe, com hash bcrypt gerado em runtime (nunca em texto puro).
    """
    if con.execute("SELECT 1 FROM usuarios WHERE usuario=?",
                   (ADMIN_USUARIO,)).fetchone() is None:
        if not ADMIN_SENHA:
            raise RuntimeError(
                "PONTO_ADMIN_SENHA não definido — recusando criar admin com senha padrão.")
        con.execute("INSERT INTO usuarios (usuario, senha_hash, criado_em) "
                    "VALUES (?, ?, ?)",
                    (ADMIN_USUARIO, hash_senha(ADMIN_SENHA),
                     time.strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()   # persiste o admin imediatamente (o chamador pode não commitar)
