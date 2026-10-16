#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Backup do ponto digital: banco (Postgres/SQLite) + embeddings faciais.

Gera um snapshot JSON de todas as tabelas + cópia dos embeddings .npy e das fotos para
/opt/ponto/backups/<timestamp>/. Uso: `python backup.py` (cron diário).

O backup dos embeddings é crítico: são os vetores biométricos (irrecuperáveis
se o disco morrer — não dá para reextrair sem a foto original).
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Resolve a URL do banco: env PONTO_DATABASE_URL > POOLER_STRING do credenciais.env
if not os.environ.get("PONTO_DATABASE_URL"):
    _cred = Path("/opt/supabase/credenciais.env")
    if _cred.exists():
        for _linha in _cred.read_text(encoding="utf-8").splitlines():
            if _linha.startswith("POOLER_STRING="):
                os.environ["PONTO_DATABASE_URL"] = _linha.split("=", 1)[1].strip()
                break

from db import conectar  # noqa: E402

BASE = Path(__file__).resolve().parent
EMB_DIR = Path(os.environ.get("PONTO_EMB_DIR", BASE / "embeddings"))
FOTOS_DIR = Path(os.environ.get("PONTO_FOTOS_DIR", BASE / "fotos"))
BACKUP_DIR = Path(os.environ.get("PONTO_BACKUP_DIR", "/opt/ponto/backups"))

TABELAS = ["colaboradores", "pontos", "usuarios", "grupos", "grupo_membros", "ajustes"]


def _dump_tabela(con, nome: str) -> list[dict]:
    try:
        cur = con.execute(f"SELECT * FROM {nome}")
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]
    except Exception as e:
        return [{"__erro__": f"{type(e).__name__}: {e}"}]


def main() -> int:
    ts = time.strftime("%Y%m%d-%H%M%S")
    destino = BACKUP_DIR / ts
    destino.mkdir(parents=True, exist_ok=True)

    con = conectar()
    banco = {"criado_em": time.strftime("%Y-%m-%d %H:%M:%S"),
             "backend": "postgres" if con.pg else "sqlite",
             "tabelas": {t: _dump_tabela(con, t) for t in TABELAS}}
    con.close()

    (destino / "banco.json").write_text(
        json.dumps(banco, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    # embeddings (biometria) + fotos de perfil
    n_emb = 0
    if EMB_DIR.is_dir():
        for f in EMB_DIR.glob("*.npy"):
            shutil.copy2(f, destino / f.name)
            n_emb += 1

    n_fotos = 0
    if FOTOS_DIR.is_dir():
        for f in FOTOS_DIR.glob("*.jpg"):
            shutil.copy2(f, destino / f.name)
            n_fotos += 1

    # limpa backups antigos (mantém os 14 mais recentes)
    backups = sorted(BACKUP_DIR.glob("20*"))
    for velho in backups[:-14]:
        shutil.rmtree(velho, ignore_errors=True)

    print(f"backup OK: {destino.name} — {len(banco['tabelas'])} tabelas, "
          f"{n_emb} embeddings, {n_fotos} fotos, backend={banco['backend']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
