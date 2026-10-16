#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Camada de banco do ponto digital: Postgres (Supabase) ou SQLite (dev/teste).

Expõe uma única interface `execute/commit/close` com placeholder `?` (convertido
para `%s` automaticamente no Postgres), para o resto do código não precisar
saber qual backend está em uso.

Escolha do backend via env:
  - PONTO_DATABASE_URL  -> Postgres (Supabase/pooler)
  - (ausente)           -> SQLite local (fallback p/ testes/desenvolvimento)
"""
from __future__ import annotations

import os


class DB:
    """Wrapper com interface comum sobre psycopg2 (Postgres) ou sqlite3."""

    def __init__(self, con, pg: bool):
        self.con = con
        self.pg = pg
        self.cur = con.cursor()

    def execute(self, sql: str, params=()):
        if self.pg:
            sql = sql.replace("?", "%s")
        self.cur.execute(sql, params)
        return self.cur

    def commit(self):
        self.con.commit()

    def close(self):
        try:
            self.cur.close()
        except Exception:
            pass
        self.con.close()


def conectar() -> DB:
    url = os.environ.get("PONTO_DATABASE_URL", "").strip()
    if url:
        import psycopg2
        return DB(psycopg2.connect(url, connect_timeout=10), pg=True)
    # Fail-closed: NÃO cai silenciosamente no SQLite em produção. O fallback
    # SQLite só é permitido de forma explícita (dev/teste) via PONTO_ALLOW_SQLITE=1.
    # Isso evita split-brain: uma batida nunca "some" num banco local esquecido
    # quando o serviço deveria estar apontando para o Supabase/Postgres.
    if os.environ.get("PONTO_ALLOW_SQLITE", "") == "1":
        import sqlite3
        caminho = os.environ.get("PONTO_SQLITE_PATH", "/opt/ponto/ponto.db")
        return DB(sqlite3.connect(caminho), pg=False)
    raise RuntimeError(
        "PONTO_DATABASE_URL não configurado e fallback SQLite desabilitado. "
        "Defina PONTO_DATABASE_URL (produção) ou PONTO_ALLOW_SQLITE=1 (dev/teste).")


def criar_schema(con: DB) -> None:
    """Cria as tabelas se não existirem (sintaxe compatível Postgres/SQLite)."""
    pk = "SERIAL PRIMARY KEY" if con.pg else "INTEGER PRIMARY KEY AUTOINCREMENT"
    con.execute(f"""CREATE TABLE IF NOT EXISTS colaboradores (
        id {pk}, nome TEXT NOT NULL UNIQUE, cpf TEXT, telefone TEXT,
        criado_em TEXT NOT NULL)""")
    con.execute(f"""CREATE TABLE IF NOT EXISTS pontos (
        id {pk}, colaborador TEXT NOT NULL, confianca REAL, quando TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'entrada', lat REAL, lng REAL,
        nsr INTEGER, hash TEXT)""")
    # migração para bancos já existentes (colunas de inviolabilidade do AFD).
    # Postgres: ADD COLUMN IF NOT EXISTS (evita abortar a transação com duplicata).
    # SQLite: try/except (não aborta a transação).
    if con.pg:
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS nsr INTEGER")
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS hash TEXT")
    else:
        for col, typ in (("nsr", "INTEGER"), ("hash", "TEXT")):
            try:
                con.execute(f"ALTER TABLE pontos ADD COLUMN {col} {typ}")
            except Exception:
                pass   # coluna já existe
    # unicidade do NSR (inviolabilidade do AFD). Índice único permite múltiplos
    # NULL — bancos legados com nsr ainda não preenchido continuam funcionando.
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_pontos_nsr ON pontos (nsr)")
    con.execute(f"""CREATE TABLE IF NOT EXISTS usuarios (
        id {pk}, usuario TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL,
        criado_em TEXT NOT NULL)""")
    con.execute(f"""CREATE TABLE IF NOT EXISTS grupos (
        id {pk}, nome TEXT NOT NULL UNIQUE, entrada TEXT NOT NULL, saida TEXT NOT NULL,
        dias TEXT NOT NULL DEFAULT '[0,1,2,3,4]', almoco_min INTEGER NOT NULL DEFAULT 0)""")
    con.execute(f"""CREATE TABLE IF NOT EXISTS grupo_membros (
        id {pk}, grupo_id INTEGER NOT NULL, colaborador TEXT NOT NULL,
        entrada TEXT, saida TEXT, almoco_min INTEGER, UNIQUE(grupo_id, colaborador))""")
    # migração: coluna de intervalo (almoço) para bancos já existentes
    if con.pg:
        con.execute("ALTER TABLE grupos ADD COLUMN IF NOT EXISTS almoco_min INTEGER NOT NULL DEFAULT 0")
        con.execute("ALTER TABLE grupo_membros ADD COLUMN IF NOT EXISTS almoco_min INTEGER")
    else:
        for tab, col, typ in (("grupos", "almoco_min", "INTEGER NOT NULL DEFAULT 0"),
                              ("grupo_membros", "almoco_min", "INTEGER")):
            try:
                con.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {typ}")
            except Exception:
                pass   # coluna já existe
    # migração: colunas de tratamento de ponto (ajuste auditável) e vínculo Bitrix.
    # Regra fiscal: batidas originais nunca são alteradas — inclusões entram como
    # novas linhas (fonte='A') com motivo; reclassificação/abono ficam em `ajustes`.
    if con.pg:
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS fonte TEXT NOT NULL DEFAULT 'O'")
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS motivo TEXT")
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS usuario_ajuste TEXT")
        con.execute("ALTER TABLE colaboradores ADD COLUMN IF NOT EXISTS bitrix_id TEXT")
    else:
        for tab, col, typ in (("pontos", "fonte", "TEXT NOT NULL DEFAULT 'O'"),
                              ("pontos", "motivo", "TEXT"),
                              ("pontos", "usuario_ajuste", "TEXT"),
                              ("colaboradores", "bitrix_id", "TEXT")):
            try:
                con.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {typ}")
            except Exception:
                pass   # coluna já existe
    # migração: dados de registro do empregado (REP-P) — matrícula, cargo e departamento.
    if con.pg:
        con.execute("ALTER TABLE colaboradores ADD COLUMN IF NOT EXISTS matricula TEXT")
        con.execute("ALTER TABLE colaboradores ADD COLUMN IF NOT EXISTS cargo TEXT")
        con.execute("ALTER TABLE colaboradores ADD COLUMN IF NOT EXISTS departamento TEXT")
    else:
        for col in ("matricula", "cargo", "departamento"):
            try:
                con.execute(f"ALTER TABLE colaboradores ADD COLUMN {col} TEXT")
            except Exception:
                pass   # coluna já existe
    con.execute(f"""CREATE TABLE IF NOT EXISTS ajustes (
        id {pk}, ponto_id INTEGER, colaborador TEXT NOT NULL, acao TEXT NOT NULL,
        tipo_novo TEXT, quando TEXT NOT NULL, motivo TEXT NOT NULL,
        usuario TEXT NOT NULL, criado_em TEXT NOT NULL)""")
    con.commit()   # DDL (CREATE/ALTER) exige commit para persistir
