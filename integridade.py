#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verificação de integridade do ponto digital: banco <-> embeddings <-> pontos.

Cruza as três fontes de verdade e aponta inconsistências que causariam
"informação sumir" ou colaborador sem conseguir bater ponto:
  - colaborador sem embedding (não reconhece no totem);
  - embedding órfão (arquivo .npy sem colaborador correspondente no banco);
  - colaborador com embedding mas que nunca bateu ponto.

Uso: `python integridade.py`  (sai 0 se íntegro, 1 se houver inconsistências).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Resolve a URL do banco (mesma lógica do backup.py)
if not os.environ.get("PONTO_DATABASE_URL"):
    _cred = Path("/opt/supabase/credenciais.env")
    if _cred.exists():
        for _linha in _cred.read_text(encoding="utf-8").splitlines():
            if _linha.startswith("POOLER_STRING="):
                os.environ["PONTO_DATABASE_URL"] = _linha.split("=", 1)[1].strip()
                break

from db import conectar  # noqa: E402

BASE = Path(__file__).resolve().parent
EMB_DIR = BASE / "embeddings"


def main() -> int:
    con = conectar()
    colaboradores = {r[0] for r in con.execute(
        "SELECT nome FROM colaboradores").fetchall()}
    com_ponto = {r[0] for r in con.execute(
        "SELECT DISTINCT colaborador FROM pontos").fetchall()}
    con.close()

    embeddings = {f.stem for f in EMB_DIR.glob("*.npy")}

    sem_embedding = sorted(colaboradores - embeddings)
    orfaos = sorted(embeddings - colaboradores)
    nunca_bateu = sorted(embeddings & colaboradores - com_ponto)
    ponto_de_desligado = sorted(com_ponto - colaboradores)

    print("=== INTEGRIDADE DO PONTO DIGITAL ===")
    print(f"colaboradores: {len(colaboradores)}")
    print(f"embeddings (.npy): {len(embeddings)}")
    print(f"colaboradores com ponto: {len(com_ponto)}")
    print()
    print(f"⚠ colaboradores SEM facial ({len(sem_embedding)}): {', '.join(sem_embedding) or '—'}")
    print(f"⚠ embeddings órfãos ({len(orfaos)}): {', '.join(orfaos) or '—'}")
    print(f"ℹ nunca bateu ponto ({len(nunca_bateu)}): {', '.join(nunca_bateu) or '—'}")
    print(f"ℹ ponto de quem saiu da lista ({len(ponto_de_desligado)}): "
          f"{', '.join(ponto_de_desligado) or '—'}")

    inconsistencias = len(sem_embedding) + len(orfaos)
    return 1 if inconsistencias else 0


if __name__ == "__main__":
    sys.exit(main())
