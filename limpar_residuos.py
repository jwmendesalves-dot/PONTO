#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Remove os resíduos (contas de teste/ramais) da tabela colaboradores.

Mantém apenas: (1) os colaboradores reais do Bitrix (filtro atual) e
(2) quem já tem foto facial (embedding .npy). Remove o resto.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2  # noqa: E402
from importar_bitrix import _nome, _ramal, buscar_ativos, PG_URL  # noqa: E402


def main():
    # lista correta: colaboradores reais (filtro atual) + quem tem foto
    corretos = set()
    for u in buscar_ativos():
        if not _ramal(u):
            n = _nome(u)
            if n:
                corretos.add(n)
    emb_dir = "/opt/ponto/embeddings"
    if os.path.isdir(emb_dir):
        for f in os.listdir(emb_dir):
            if f.endswith(".npy"):
                corretos.add(f[:-4])

    con = psycopg2.connect(PG_URL, connect_timeout=10)
    cur = con.cursor()
    cur.execute("SELECT nome FROM colaboradores")
    todos = [r[0] for r in cur.fetchall()]
    residuos = [n for n in todos if n not in corretos]

    print(f"total: {len(todos)} | manter: {len(corretos)} | resíduos: {len(residuos)}")
    for n in sorted(residuos):
        print(f"  − {n}")

    for n in residuos:
        cur.execute("DELETE FROM colaboradores WHERE nome = %s", (n,))
    con.commit(); con.close()
    print(f"✅ {len(residuos)} resíduos removidos")


if __name__ == "__main__":
    main()
