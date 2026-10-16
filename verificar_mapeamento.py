#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Verifica o mapeamento dos 35 nomes fornecidos contra os usuários do Bitrix (dry-run)."""
import sys, unicodedata
sys.path.insert(0, '/opt/ponto')
from importar_bitrix import buscar_ativos, _nome

def norm(s):
    s = unicodedata.normalize('NFD', s.lower().strip())
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.strip()

LISTA = [
    # 8h
    "Ruan Fernandes", "Vitória Sousa", "Neide da Silva Negrão", "Guilherme Perez", "Camila Duca",
    "Cristhyane Duca", "Leonardo Rocha", "Josiel S. Silva", "Carolina Duca", "Anna Luisa Gomes",
    "Gusttavo Andrade", "Wadrian mendes alves de souza", "Isabella Matos", "Larissa Maia", "Eminem Barbosa",
    "Samyra Ribeiro", "Keren Gabrieli", "Michael Walker", "Ana Julia da Silva", "Jaqueline Carmo",
    "Lucas Ferreira", "Rhyan Ferreira", "Maria Clara Monteiro", "Maria Clara Torres",
    # estagiários
    "João Pedro Batista Rabelo", "Sarah Castro", "Nicolas Slaviero", "Maria Eduarda Rodrigues Borelli",
    "Maria Heloisa lopes", "GUSTAVO ANASTACIO DE MOURA ARRUDA", "Guilherme Kisser", "Lucas Felipe",
    "Vanessa da Silva Souza Miranda", "Kaua Rodrigues de Andrade", "Amandha Bernardes Rodrigues",
]

usuarios = buscar_ativos()
bitrix = [(u, _nome(u), norm(_nome(u))) for u in usuarios if _nome(u)]

encontrados = []
nao_encontrados = []

for alvo in LISTA:
    a = norm(alvo)
    # comparação exata normalizada (case/trim), sem substring
    hits = [n for u, n, nn in bitrix if nn == a]
    if not hits:
        nao_encontrados.append(alvo)
    elif len(hits) == 1:
        encontrados.append((alvo, hits[0]))
    else:
        encontrados.append((alvo, hits))

print(f"=== {len(encontrados)} encontrados / {len(nao_encontrados)} não encontrados ===\n")
print("NÃO ENCONTRADOS:")
for n in nao_encontrados:
    print(f"  ✗ {n}")
print("\nENCONTRADOS (alvo -> bitrix):")
for alvo, hit in encontrados:
    marca = "  ✓" if not isinstance(hit, list) else "  ⚠ (ambíguo)"
    print(f"{marca} {alvo} -> {hit if not isinstance(hit, list) else hit}")
