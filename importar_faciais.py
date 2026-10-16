#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Importa a facial (embedding) dos colaboradores a partir dos avatares do Bitrix.

Fluxo ponto a ponta:
  1. baixa o avatar (PERSONAL_PHOTO) de cada colaborador ativo;
  2. InsightFace detecta o rosto e extrai o embedding (512d);
  3. a IA (agnes) valida se a foto é um rosto frontal utilizável (gate de qualidade);
  4. se ambos OK, salva embeddings/<nome>.npy — o colaborador já pode bater ponto.

A diferença com a integração de IA: sem ela, qualquer imagem (logo, paisagem, foto
de grupo) vira embedding errado. A IA barra o que não é rosto frontal nítido.
"""
import base64
import json
import os
import sys
import time
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from importar_bitrix import _nome, _ramal, buscar_ativos, WEBHOOK  # noqa: E402

EMB_DIR = "/opt/ponto/embeddings"
AGNES_URL = "https://apihub.agnes-ai.com/v1/chat/completions"
AGNES_KEY = os.environ.get("AGNES_KEY", "").strip() or open("/root/.agnes/tokenplan.key").read().strip()

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


def _baixar(url: str) -> np.ndarray | None:
    try:
        u = urllib.parse.quote(url, safe=":/")
        raw = urllib.request.urlopen(u, timeout=30).read()
        arr = np.frombuffer(raw, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception:
        return None


def _ia_valida(img: np.ndarray) -> tuple[bool, str]:
    """Pergunta à agnes se a foto é um rosto frontal utilizável."""
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return False, "erro ao codificar"
    b64 = base64.b64encode(buf.tobytes()).decode()
    payload = {
        "model": "agnes-3.0-flash",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                "Esta imagem é um ROSTO HUMANO FRONTAL, nítido, bem iluminado, sem "
                "óculos escuros/máscara/obstrução, adequado para reconhecimento facial? "
                "Responda APENAS JSON: {\"valido\": true/false, \"motivo\": \"...\"}")},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "stream": False, "max_tokens": 120, "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    try:
        req = urllib.request.Request(
            AGNES_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + AGNES_KEY})
        d = json.loads(urllib.request.urlopen(req, timeout=60).read())
        r = json.loads(d["choices"][0]["message"]["content"])
        return bool(r.get("valido")), str(r.get("motivo", ""))
    except Exception as e:
        return False, f"IA falhou: {type(e).__name__}"


def main():
    usuarios = buscar_ativos()
    pessoas = [u for u in usuarios if not _ramal(u)]
    os.makedirs(EMB_DIR, exist_ok=True)

    total = 0
    ok = 0
    sem_rosto = 0
    ia_reprovou = 0
    resultados = []

    for u in pessoas:
        nome = _nome(u)
        if not nome:
            continue
        foto = u.get("PERSONAL_PHOTO") or ""
        if not foto:
            resultados.append((nome, "sem avatar", ""))
            continue
        total += 1
        img = _baixar(foto)
        if img is None:
            resultados.append((nome, "download falhou", ""))
            continue
        faces = _face().get(img)
        if not faces:
            sem_rosto += 1
            resultados.append((nome, "sem rosto detectado", ""))
            continue
        valido, motivo = _ia_valida(img)
        if not valido:
            ia_reprovou += 1
            resultados.append((nome, "IA reprovou: " + (motivo or "?"), ""))
            continue
        # pega o maior rosto e salva o embedding
        faces.sort(key=lambda f: (f.bbox[2]-f.bbox[0]) * (f.bbox[3]-f.bbox[1]), reverse=True)
        emb = faces[0].normed_embedding.astype(np.float32)
        np.save(os.path.join(EMB_DIR, f"{nome}.npy"), emb)
        ok += 1
        resultados.append((nome, "✓ facial cadastrada", ""))
        print(f"  ✓ {nome}", flush=True)

    print(f"\n=== RESUMO ===")
    print(f"colaboradores processados: {total}")
    print(f"  ✓ facial válida: {ok}")
    print(f"  ✗ sem rosto: {sem_rosto}")
    print(f"  ✗ IA reprovou: {ia_reprovou}")
    for nome, status, _ in resultados:
        if status != "✓ facial cadastrada":
            print(f"  − {nome}: {status}")


if __name__ == "__main__":
    main()
