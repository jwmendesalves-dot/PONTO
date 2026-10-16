#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes da camada de banco — fail-closed (evita split-brain SQLite/Postgres).

TDD: escritos ANTES da implementação do fail-closed em db.py.

Regra de ouro: em produção (sem PONTO_ALLOW_SQLITE), se PONTO_DATABASE_URL não
estiver definido, conectar() DEVE falhar (não cair silenciosamente no SQLite).
Isso garante que uma batida de ponto nunca "suma" num banco local esquecido.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

import db as dbmod  # noqa: E402


def test_sem_url_sem_flag_falha_fechado(monkeypatch):
    monkeypatch.delenv("PONTO_DATABASE_URL", raising=False)
    monkeypatch.delenv("PONTO_ALLOW_SQLITE", raising=False)
    with pytest.raises(RuntimeError):
        dbmod.conectar()


def test_sem_url_com_flag_usa_sqlite(monkeypatch):
    monkeypatch.delenv("PONTO_DATABASE_URL", raising=False)
    monkeypatch.setenv("PONTO_ALLOW_SQLITE", "1")
    con = dbmod.conectar()
    try:
        assert con.pg is False
    finally:
        con.close()


def test_com_url_usa_postgres(monkeypatch):
    monkeypatch.delenv("PONTO_ALLOW_SQLITE", raising=False)
    monkeypatch.setenv("PONTO_DATABASE_URL", "postgresql://u:p@h:5432/db")

    class FakeCur:
        def execute(self, *a, **k):
            return self

        def close(self):
            pass

    class FakeConn:
        def cursor(self):
            return FakeCur()

        def commit(self):
            pass

        def close(self):
            pass

    import psycopg2
    monkeypatch.setattr(psycopg2, "connect", lambda *a, **k: FakeConn())
    con = dbmod.conectar()
    try:
        assert con.pg is True
    finally:
        con.close()


def test_schema_tem_ajustes_e_colunas_de_vinculo():
    from db import conectar, criar_schema
    con = conectar()
    try:
        criar_schema(con)
        cols_pontos = {r[1] for r in con.execute("PRAGMA table_info(pontos)").fetchall()} \
            if not con.pg else {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='pontos'").fetchall()}
        cols_colab = {r[1] for r in con.execute("PRAGMA table_info(colaboradores)").fetchall()} \
            if not con.pg else {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='colaboradores'").fetchall()}
        tabs = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'" if not con.pg
            else "SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()}
        assert {"fonte", "motivo", "usuario_ajuste"} <= cols_pontos
        assert "bitrix_id" in cols_colab
        assert "ajustes" in tabs
    finally:
        con.close()
