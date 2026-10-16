#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Importa os colaboradores ativos do Bitrix24 para o ponto (Supabase).

Filtra os usuários `employee` ativos, excluindo ramais de telefonia (Cisco/IP phone)
e contas genéricas (Recepção/Atendimento/DPVAT/etc.). Cadastra nome + telefone.
O CPF não vem do Bitrix (fica NULL) e a foto facial é tirada depois pelo colaborador.
"""
import json
import os
import re
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import psycopg2  # noqa: E402

WEBHOOK = os.environ.get("PONTO_BITRIX_WEBHOOK", "").strip()
PG_URL = os.environ.get("PONTO_DATABASE_URL", "").strip()

# palavras que identificam ramal/conta genérica (excluir)
PALAVRAS_RAMAL = [
    "recepção", "recepcao", "atendimento", "ramal", "dpvat",
    "previdenciário", "previdenciario", "previ", "casa rod", "selma",
    "casa", "financeiro", "consulta", "arquivo",
]
CARGOS_RAMAL = [
    "cisco", "ipphone", "ip phone", "ip phone", "grandstream", "ramal",
    "ip phone", "roo", "consulta", "quality call", "assistindo",
]


def _ramal(u: dict) -> bool:
    nome = f"{u.get('NAME', '')} {u.get('LAST_NAME', '')}".lower()
    cargo = (u.get("WORK_POSITION") or "").lower()
    if any(p in cargo for p in CARGOS_RAMAL):
        return True
    if any(p in nome for p in PALAVRAS_RAMAL):
        return True
    # sobrenome só numérico (ex.: "1051", "1101 xx")
    ln = (u.get("LAST_NAME") or "").strip()
    if ln and re.fullmatch(r"\d+(\s*xx)?", ln, re.IGNORECASE):
        return True
    return False


def _nome(u: dict) -> str:
    partes = [u.get("NAME", "").strip(), u.get("LAST_NAME", "").strip()]
    return " ".join(p for p in partes if p).strip()


def buscar_ativos() -> list:
    """Pega TODOS os usuários (paginação) e filtra ACTIVE=true no Python."""
    todos = []
    start = 0
    while True:
        qs = urllib.parse.urlencode({"start": start})
        d = json.loads(urllib.request.urlopen(
            f"{WEBHOOK}user.get.json?{qs}", timeout=30).read())
        batch = d.get("result", [])
        todos.extend(batch)
        if len(batch) < 50:
            break
        start += 50
    ativos = [u for u in todos if u.get("ACTIVE") is True and u.get("USER_TYPE") == "employee"]
    return ativos


def main():
    if not WEBHOOK:
        raise SystemExit("PONTO_BITRIX_WEBHOOK não definido.")
    if not PG_URL:
        raise SystemExit("PONTO_DATABASE_URL não definido.")
    usuarios = buscar_ativos()
    pessoas = [u for u in usuarios if not _ramal(u)]
    # dedup por nome
    vistos = set()
    unicos = []
    for u in pessoas:
        n = _nome(u)
        if n and n not in vistos:
            vistos.add(n)
            unicos.append(u)

    print(f"ativos: {len(usuarios)} | pessoas (sem ramal): {len(unicos)}")
    print("---- lista ----")
    for u in sorted(unicos, key=_nome):
        print(f"  • {_nome(u)}  | {u.get('WORK_POSITION') or '—'} | {u.get('PERSONAL_MOBILE') or u.get('WORK_PHONE') or '—'}")

    con = psycopg2.connect(PG_URL, connect_timeout=10)
    cur = con.cursor()
    n_inseridos = 0
    for u in unicos:
        nome = _nome(u)
        tel = (u.get("PERSONAL_MOBILE") or u.get("WORK_PHONE") or "").strip()
        cur.execute(
            "INSERT INTO colaboradores (nome, telefone, criado_em) VALUES (%s, %s, NOW()::text) "
            "ON CONFLICT(nome) DO UPDATE SET telefone=EXCLUDED.telefone",
            (nome, tel or None),
        )
        n_inseridos += 1
    con.commit(); con.close()
    print(f"✅ {n_inseridos} colaboradores cadastrados no Supabase")


if __name__ == "__main__":
    main()
