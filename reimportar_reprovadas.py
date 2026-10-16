#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Reimporta as faciais reprovadas com limiar de pose relaxado (40°) — fotos levemente inclinadas."""
import os
import sys
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from importar_bitrix import buscar_ativos, _nome  # noqa: E402

EMB_DIR = "/opt/ponto/embeddings"
POSE_MAX = 40.0   # mais tolerante que os 30° do reconhecimento (foto de referência)

REPROVADOS = [
    "Gusttavo Andrade", "Wadrian mendes alves de souza", "Michael Walker",
    "Ana Julia da Silva", "Rhyan Ferreira", "Maria Clara Monteiro",
    "João Pedro Batista Rabelo", "Nicolas Slaviero",
]


def main():
    fa = None
    import insightface
    from insightface.app import FaceAnalysis
    fa = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
    fa.prepare(ctx_id=-1)

    usuarios = buscar_ativos()
    by_nome = {_nome(u): u for u in usuarios if _nome(u)}
    ok, ainda_ruim = [], []
    for nome in REPROVADOS:
        u = by_nome.get(nome)
        if not u or not u.get("PERSONAL_PHOTO"):
            ainda_ruim.append((nome, "sem foto"))
            continue
        raw = urllib.request.urlopen(urllib.parse.quote(u["PERSONAL_PHOTO"], safe=":/"), timeout=30).read()
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        faces = fa.get(img)
        if not faces:
            ainda_ruim.append((nome, "sem rosto"))
            continue
        faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
        f = faces[0]
        yaw, pitch, roll = (f.pose if f.pose is not None else (0.0, 0.0, 0.0))
        if abs(yaw) > POSE_MAX or abs(pitch) > POSE_MAX:
            ainda_ruim.append((nome, f"muito de perfil (yaw={yaw:.0f} pitch={pitch:.0f})"))
            continue
        np.save(os.path.join(EMB_DIR, f"{nome}.npy"), f.normed_embedding.astype(np.float32))
        ok.append(nome)
        print(f"  ✓ {nome} (yaw={yaw:.0f} pitch={pitch:.0f})")

    print(f"\n=== salvas: {len(ok)} ===")
    for nome, mot in ainda_ruim:
        print(f"  − {nome}: {mot}")


if __name__ == "__main__":
    main()
