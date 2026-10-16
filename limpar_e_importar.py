#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Limpa o sistema para produção e importa só os colaboradores selecionados.

1. Apaga: grupos, membros, pontos (batidas de teste), colaboradores e embeddings.
2. Busca no Bitrix os 35 nomes selecionados e cadastra nome + telefone.
3. Baixa a foto de perfil (PERSONAL_PHOTO), valida qualidade (det_score + pose) e
   salva o embedding facial — o colaborador já sai pronto para bater ponto.
4. Recria os grupos Estagiários (6h) e Funcionários (8h) e aloca cada um.
"""
import glob
import os
import sys
import unicodedata
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import psycopg2  # noqa: E402

from importar_bitrix import buscar_ativos, _nome  # noqa: E402
from logica import avaliar_qualidade_rosto  # noqa: E402

EMB_DIR = "/opt/ponto/embeddings"

# Resolve a URL do banco: env > POOLER_STRING (credenciais.env) > systemd
def _pg_url():
    if os.environ.get("PONTO_DATABASE_URL"):
        return os.environ["PONTO_DATABASE_URL"]
    cred = "/opt/supabase/credenciais.env"
    if os.path.exists(cred):
        for linha in open(cred, encoding="utf-8"):
            if linha.startswith("POOLER_STRING="):
                return linha.split("=", 1)[1].strip()
    svc = "/etc/systemd/system/ponto-facial.service"
    if os.path.exists(svc):
        for linha in open(svc, encoding="utf-8"):
            if linha.startswith("Environment=PONTO_DATABASE_URL="):
                return linha.split("=", 1)[1].strip()
    raise RuntimeError("não achei a URL do banco")


PG_URL = _pg_url()

# nomes EXATOS no Bitrix (mapeados via verificar_mapeamento.py)
LISTA_8H = [
    "Ruan Fernandes", "Vitória Sousa", "Neide da Silva Negrão", "Guilherme Perez",
    "Camila Duca", "Cristhyane Duca", "Leonardo Rocha", "Josiel S. Silva",
    "Carolina Duca", "Anna Luisa Gomes", "Gusttavo Andrade", "Wadrian mendes alves de souza",
    "Isabella Matos", "Larissa Maia", "Eminem Barbosa", "Samyra Ribeiro",
    "Keren Gabrieli", "Michael Walker", "Ana Julia da Silva", "Jaqueline Carmo",
    "Lucas Ferreira", "Rhyan Ferreira", "Maria Clara Monteiro", "Maria Clara Torres",
]
LISTA_ESTAG = [
    "João Pedro Batista Rabelo", "Sarah Castro", "Nicolas Slaviero",
    "Maria Eduarda Rodrigues Borelli", "Maria Heloisa lopes",
    "GUSTAVO ANASTACIO DE MOURA ARRUDA", "Guilherme Kisser", "Lucas Felipe",
    "Vanessa da Silva Souza Miranda", "Kaua Rodrigues de Andrade", "Amandha Bernardes Rodrigues",
]

_FACE = None


def _face():
    global _FACE
    if _FACE is None:
        import insightface
        from insightface.app import FaceAnalysis
        fa = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        fa.prepare(ctx_id=-1)
        _FACE = fa
    return _FACE


def _norm(s):
    s = unicodedata.normalize("NFD", s.lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _baixar(url):
    try:
        u = urllib.parse.quote(url, safe=":/")
        raw = urllib.request.urlopen(u, timeout=30).read()
        return cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR)
    except Exception:
        return None


def limpar():
    con = psycopg2.connect(PG_URL, connect_timeout=10)
    cur = con.cursor()
    for t in ("grupo_membros", "grupos", "pontos", "colaboradores"):
        cur.execute(f"DELETE FROM {t}")
    con.commit()
    con.close()
    removidos = 0
    for f in glob.glob(os.path.join(EMB_DIR, "*.npy")):
        os.remove(f)
        removidos += 1
    print(f"🧹 limpo: grupos/membros/pontos/colaboradores + {removidos} embeddings removidos")


def mapear(alvos, usuarios):
    by_norm = {_norm(_nome(u)): u for u in usuarios if _nome(u)}
    out = []
    faltando = []
    for a in alvos:
        u = by_norm.get(_norm(a))
        if u:
            out.append(u)
        else:
            faltando.append(a)
    return out, faltando


def importar(usuarios_selecionados):
    os.makedirs(EMB_DIR, exist_ok=True)
    con = psycopg2.connect(PG_URL, connect_timeout=10)
    cur = con.cursor()
    ok = 0
    sem_rosto = 0
    reprovados = []
    for u in usuarios_selecionados:
        nome = _nome(u)
        tel = (u.get("PERSONAL_MOBILE") or u.get("WORK_PHONE") or "").strip()
        cur.execute(
            "INSERT INTO colaboradores (nome, telefone, criado_em) VALUES (%s, %s, NOW()::text) "
            "ON CONFLICT(nome) DO UPDATE SET telefone=EXCLUDED.telefone",
            (nome, tel or None))
        foto = u.get("PERSONAL_PHOTO") or ""
        if not foto:
            reprovados.append((nome, "sem foto no Bitrix"))
            continue
        img = _baixar(foto)
        if img is None:
            reprovados.append((nome, "download da foto falhou"))
            continue
        faces = _face().get(img)
        if not faces:
            sem_rosto += 1
            reprovados.append((nome, "sem rosto detectado na foto"))
            continue
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        f = faces[0]
        yaw, pitch, roll = (f.pose if f.pose is not None else (0.0, 0.0, 0.0))
        qualidade_ok, motivo = avaliar_qualidade_rosto(float(f.det_score), float(yaw), float(pitch), float(roll))
        if not qualidade_ok:
            reprovados.append((nome, "qualidade: " + motivo))
            continue
        emb = f.normed_embedding.astype(np.float32)
        np.save(os.path.join(EMB_DIR, f"{nome}.npy"), emb)
        ok += 1
        print(f"  ✓ {nome}", flush=True)
    con.commit()
    con.close()
    print(f"\n=== FACIAL ===  {ok} válidas | {sem_rosto} sem rosto | {len(reprovados)} reprovadas")
    for nome, mot in reprovados:
        print(f"  − {nome}: {mot}")


def criar_grupos():
    con = psycopg2.connect(PG_URL, connect_timeout=10)
    cur = con.cursor()
    cur.execute("INSERT INTO grupos (nome, entrada, saida, dias) VALUES (%s,%s,%s,%s) RETURNING id",
                ("Estagiários", "08:00", "14:00", "[0, 1, 2, 3, 4]"))
    id_est = cur.fetchone()[0]
    cur.execute("INSERT INTO grupos (nome, entrada, saida, dias) VALUES (%s,%s,%s,%s) RETURNING id",
                ("Funcionários", "08:00", "17:30", "[0, 1, 2, 3, 4]"))
    id_fun = cur.fetchone()[0]
    for nome in LISTA_ESTAG:
        cur.execute("INSERT INTO grupo_membros (grupo_id, colaborador) VALUES (%s,%s) "
                    "ON CONFLICT(grupo_id, colaborador) DO NOTHING", (id_est, nome))
    for nome in LISTA_8H:
        cur.execute("INSERT INTO grupo_membros (grupo_id, colaborador) VALUES (%s,%s) "
                    "ON CONFLICT(grupo_id, colaborador) DO NOTHING", (id_fun, nome))
    con.commit()
    con.close()
    print(f"✅ grupos recriados: Estagiários ({len(LISTA_ESTAG)}) + Funcionários ({len(LISTA_8H)})")


def main():
    limpar()
    usuarios = buscar_ativos()
    sel_8h, falta_8h = mapear(LISTA_8H, usuarios)
    sel_est, falta_est = mapear(LISTA_ESTAG, usuarios)
    faltando = falta_8h + falta_est
    if faltando:
        print("⚠️ não encontrados no Bitrix:", faltando)
    todos = sel_8h + sel_est
    print(f"\n=== IMPORTANDO {len(todos)} colaboradores (com foto) ===")
    importar(todos)
    criar_grupos()
    print("\n🎉 produção pronta.")


if __name__ == "__main__":
    main()
