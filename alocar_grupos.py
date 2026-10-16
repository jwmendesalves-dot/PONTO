#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Aloca colaboradores nos grupos Estagiários (6h) e Funcionários (8h).

Idempotente: pode rodar de novo sem duplicar (ON CONFLICT DO UPDATE).
Fonte dos horários (confirmados pelo usuário):
  - Estagiários: 6h diárias, entrada/saída 08:00-14:00 (turnos variam, jornada = 6h).
  - Funcionários: 08:00-17:30 (8h de trabalho + 1h30 almoço).
"""
import json
import os
import urllib.request

BASE = os.environ.get("PONTO_BASE_URL", "http://localhost:8898")


def _tok():
    if os.environ.get("PONTO_JWT_SECRET"):
        import auth
        return auth.criar_token(auth.ADMIN_USUARIO)
    senha = os.environ.get("PONTO_ADMIN_SENHA")
    if not senha:
        raise RuntimeError("defina PONTO_ADMIN_SENHA ou PONTO_JWT_SECRET no ambiente")
    r = urllib.request.Request(BASE + "/api/login",
                               data=json.dumps({"usuario": "admin", "senha": senha}).encode(),
                               headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())["token"]


def call(method, path, tok, body=None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method,
                               headers={"Content-Type": "application/json",
                                        "Authorization": "Bearer " + tok})
    try:
        return json.loads(urllib.request.urlopen(r, timeout=30).read())
    except urllib.error.HTTPError as e:
        return {"erro": e.code, "msg": e.read().decode()[:200]}


ESTAGIARIOS = [
    "João Pedro Batista Rabelo",
    "Sarah Castro",
    "Nicolas Slaviero",
    "Maria Eduarda Rodrigues Borelli",
    "Maria Heloisa lopes",
    "GUSTAVO ANASTACIO DE MOURA ARRUDA",
    "Guilherme Kisser",
    "Lucas Felipe",
    "Vanessa da Silva Souza Miranda",
    "Kaua Rodrigues de Andrade",
    "Amandha Bernardes Rodrigues",
]

FUNCIONARIOS = [
    "Ruan Fernandes",
    "Vitória Sousa",
    "Neide da Silva Negrão",
    "Guilherme Perez",
    "Camila Duca",
    "Cristhyane Duca",
    "Leonardo Rocha",
    "Josiel S. Silva",
    "Carolina Duca",
    "Anna Luisa Gomes",
    "Gusttavo Andrade",
    "Wadrian mendes alves de souza",
    "Isabella Matos",
    "Larissa Maia",
    "Eminem Barbosa",
    "Samyra Ribeiro",
    "Keren Gabrieli",
    "Michael Walker",
    "Ana Julia da Silva",
    "Jaqueline Carmo",
    "Lucas Ferreira",
    "Rhyan Ferreira",
    "Maria Clara Monteiro",
    "Maria Clara Torres",
]


def main():
    tok = _tok()
    cfg = call("GET", "/api/configuracao", tok)

    # 1) remove o grupo antigo "Recepção" (só tinha o wadrian)
    for g in cfg.get("grupos", []):
        if g["nome"].strip().lower() in ("recepção", "recepcao"):
            call("DELETE", f"/api/grupos/{g['id']}", tok)
            print(f"removido grupo antigo: {g['nome']}")

    # 2) cria os 2 grupos
    g_est = call("POST", "/api/grupos", tok,
                 {"nome": "Estagiários", "entrada": "08:00", "saida": "14:00", "dias": [0, 1, 2, 3, 4]})
    g_fun = call("POST", "/api/grupos", tok,
                 {"nome": "Funcionários", "entrada": "08:00", "saida": "17:30", "dias": [0, 1, 2, 3, 4]})
    print("grupos criados:", g_est, g_fun)

    id_est = g_est.get("id")
    id_fun = g_fun.get("id")

    # 3) aloca membros
    for nome in ESTAGIARIOS:
        call("POST", f"/api/grupos/{id_est}/membros", tok, {"colaborador": nome})
    for nome in FUNCIONARIOS:
        call("POST", f"/api/grupos/{id_fun}/membros", tok, {"colaborador": nome})
    print(f"alocados: {len(ESTAGIARIOS)} estagiários + {len(FUNCIONARIOS)} funcionários")

    # 4) verifica
    cfg2 = call("GET", "/api/configuracao", tok)
    for g in cfg2["grupos"]:
        print(f"  {g['nome']}: {g['entrada']}-{g['saida']} | {len(g['membros'])} membros")


if __name__ == "__main__":
    main()
