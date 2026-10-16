#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Migra os dados do ponto digital do SQLite local para o Supabase (Postgres).

One-shot: copia colaboradores, pontos, usuarios, grupos e grupo_membros.
Os embeddings faciais (arquivos .npy) NÃO migram — continuam em /opt/ponto/embeddings/.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import DB, conectar, criar_schema  # noqa: E402

SQLITE = "/opt/ponto/ponto.db"
URL = os.environ.get("PONTO_DATABASE_URL", "").strip()


def main():
    if not URL:
        raise SystemExit("PONTO_DATABASE_URL não definido.")
    src = sqlite3.connect(SQLITE)
    scur = src.cursor()

    import psycopg2
    pg = psycopg2.connect(URL, connect_timeout=10)
    dst = DB(pg, pg=True)
    criar_schema(dst)

    # colaboradores
    n = 0
    for r in scur.execute("SELECT nome, cpf, telefone, criado_em FROM colaboradores"):
        dst.execute("INSERT INTO colaboradores (nome, cpf, telefone, criado_em) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(nome) DO NOTHING", r)
        n += 1
    print(f"colaboradores: {n}")

    # pontos
    n = 0
    for r in scur.execute("SELECT colaborador, confianca, quando, tipo, lat, lng, nsr FROM pontos"):
        dst.execute("INSERT INTO pontos (colaborador, confianca, quando, tipo, lat, lng, nsr) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(nsr) DO NOTHING", r)
        n += 1
    print(f"pontos: {n}")

    # usuarios
    n = 0
    for r in scur.execute("SELECT usuario, senha_hash, criado_em FROM usuarios"):
        dst.execute("INSERT INTO usuarios (usuario, senha_hash, criado_em) "
                    "VALUES (?, ?, ?) ON CONFLICT(usuario) DO NOTHING", r)
        n += 1
    print(f"usuarios: {n}")

    # grupos + membros
    ng = 0
    nm = 0
    for r in scur.execute("SELECT id, nome, entrada, saida, dias FROM grupos"):
        dst.execute("INSERT INTO grupos (nome, entrada, saida, dias) "
                    "VALUES (?, ?, ?, ?) ON CONFLICT(nome) DO NOTHING", (r[1], r[2], r[3], r[4]))
        ng += 1
        gid = dst.execute("SELECT id FROM grupos WHERE nome=?", (r[1],)).fetchone()[0]
        for m in scur.execute("SELECT colaborador, entrada, saida FROM grupo_membros "
                              "WHERE grupo_id=?", (r[0],)):
            dst.execute("INSERT INTO grupo_membros (grupo_id, colaborador, entrada, saida) "
                        "VALUES (?, ?, ?, ?) ON CONFLICT(grupo_id, colaborador) DO NOTHING",
                        (gid, m[0], m[1], m[2]))
            nm += 1
    print(f"grupos: {ng} | membros: {nm}")

    dst.commit()
    dst.close()
    src.close()
    print("✅ migração concluída")


if __name__ == "__main__":
    main()
