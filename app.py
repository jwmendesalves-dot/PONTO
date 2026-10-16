#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ponto facial — backend FastAPI + InsightFace (ArcFace) + SQLite.

Registra batidas com tipo (entrada/pausa/volta/termino) e geolocalização,
e expõe métricas reais por usuário + histórico. Serve a PWA (static/).

Endpoints:
  POST /api/cadastrar   {nome, foto_base64}            -> cadastra (autenticado)
  DELETE /api/colaborador/{nome}                       -> exclui (autenticado)
  POST /api/reconhecer  {foto_base64, lat?, lng?, tipo?}-> reconhece + registra
  POST /api/login       {usuario, senha}               -> devolve JWT de sessão (12h)
  GET  /api/pontos      ?usuario=&de=&ate=&limite=     -> histórico
  GET  /api/metricas    ?data=YYYY-MM-DD               -> métricas por usuário
  GET  /api/colaboradores                               -> lista cadastrados
  GET  /api/health
  GET  /                -> PWA

Autenticação: endpoints admin aceitam header `Authorization: Bearer <jwt>`
(obtido em POST /api/login) ou, temporariamente, `X-Admin-Token` igual ao
PONTO_ADMIN_TOKEN do env. Senha guardada com hash bcrypt no SQLite.
"""
from __future__ import annotations

import base64
import calendar
import hashlib
import json
import os
import secrets
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

import cv2
import numpy as np
from fastapi import FastAPI, HTTPException, Header, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from db import DB, conectar, criar_schema  # noqa: F401
from fiscal import (gerar_aej, gerar_afd, gerar_comprovante,  # noqa: F401
                    hash_encadeado, sha256)
from logica import (atraso_minutos, avaliar_qualidade_rosto, aplicar_ajustes,  # noqa: F401
                    banco_horas, calcular_faltas, calendario_mensal,
                    decidir_liveness, dias_trabalho, jornada_efetiva_seg, jornada_horario_seg,
                    metricas_usuario, parear_batidas, proximo_tipo,
                    relatorio_individual, resumo_colaborador, saldo_dia,
                    validar_cpf, validar_nome)
from clt import apurar_dia, interjornada_min
from datetime import date
from auth import (criar_token, garantir_admin, token_valido,  # noqa: F401
                  verificar_senha, TOKEN_TTL_SEG)

BASE = Path(__file__).resolve().parent
DB = BASE / "ponto.db"
STATIC = BASE / "static"
EMB_DIR = BASE / "embeddings"          # um .npy por colaborador
FOTOS_DIR = BASE / "fotos"             # um .jpg por colaborador (exibição no painel)
ADMIN_TOKEN = os.environ.get("PONTO_ADMIN_TOKEN", "").strip()

TIPOS = ("entrada", "pausa", "volta", "termino")
JORNADA_PADRAO = 8 * 3600   # jornada padrão (8h) para quem não tem horário no grupo
NOMES_TIPO = {"entrada": "Entrada", "pausa": "Pausa (almoço)",
              "volta": "Volta", "termino": "Término"}

# ---- Liveness (anti-fraude) via agnes ----
# Desligue com PONTO_LIVENESS=0. Nunca bloqueia o ponto por falha de infra:
# se a IA estiver fora (erro/timeout/sem chave), o fallback é liberar a batida.
LIVENESS_ATIVO = os.environ.get("PONTO_LIVENESS", "1") == "1"
AGNES_URL = os.environ.get("AGNES_URL", "https://apihub.agnes-ai.com/v1/chat/completions")
_AGNES_KEY = os.environ.get("AGNES_KEY", "").strip()

# ---- Aviso de atraso (entrada fora do horário do grupo) ----
# Notifica o Rodrigo (Bitrix) quando alguém bate entrada ATRASADO.
BITRIX_WEBHOOK = os.environ.get("PONTO_BITRIX_WEBHOOK", "").strip()
BITRIX_ADMIN_ID = os.environ.get("PONTO_ADMIN_BITRIX_ID", "1")  # 1 = Rodrigo Correa

_FACE = None
_NSR_LOCK = threading.Lock()


def _agnes_key() -> str:
    global _AGNES_KEY
    if not _AGNES_KEY:
        for p in ("/root/.agnes/tokenplan.key", "/run/secrets/agnes.key"):
            try:
                _AGNES_KEY = Path(p).read_text().strip()
                break
            except Exception:
                continue
    return _AGNES_KEY


def _liveness(img: np.ndarray) -> dict:
    """Valida (via agnes) se a batida é de uma pessoa viva, não fraude (print/foto de foto).

    Retorna {"vivo": bool, "motivo": str}. Só barra quando a IA detecta fraude
    explicitamente — qualquer falha de infra libera (fallback não bloqueante).
    """
    if not LIVENESS_ATIVO:
        return {"vivo": True, "motivo": ""}
    chave = _agnes_key()
    if not chave:
        print("PONTO_LIVENESS: AGNES_KEY ausente — liveness liberado (fail-open)",
              file=sys.stderr, flush=True)
        return {"vivo": True, "motivo": ""}
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 80])
    if not ok:
        return {"vivo": True, "motivo": ""}
    b64 = base64.b64encode(buf.tobytes()).decode()
    payload = {
        "model": "agnes-3.0-flash",
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": (
                "Esta imagem mostra uma PESSOA REAL E VIVA na frente da câmera, ou uma "
                "FRAUDE (foto de foto impressa, print de tela, ou tela/celular exibindo "
                "a foto de outra pessoa)? Responda APENAS JSON: "
                "{\"vivo\": true/false, \"fraude\": \"nenhuma\"/\"print_tela\"/\"foto_de_foto\"/"
                "\"tela_com_foto\", \"motivo\": \"breve\"}")},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}},
        ]}],
        "stream": False, "max_tokens": 120, "temperature": 0.0,
        "response_format": {"type": "json_object"},
    }
    try:
        req = urllib.request.Request(
            AGNES_URL, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + chave})
        d = json.loads(urllib.request.urlopen(req, timeout=5).read())
        return decidir_liveness(json.loads(d["choices"][0]["message"]["content"]))
    except Exception as exc:
        print(f"PONTO_LIVENESS: falha na chamada agnes ({exc}) — liveness liberado (fail-open)",
              file=sys.stderr, flush=True)
        return {"vivo": True, "motivo": ""}


def _verificar_movimento(img1: np.ndarray, img2: np.ndarray) -> bool:
    """Liveness por movimento: True se há diferença entre dois frames.

    Uma foto/print perfeitamente estático gera diferença ~0 entre capturas;
    uma pessoa viva tem micro-movimentos (piscar, respirar, tremor).
    """
    g1 = cv2.resize(cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY), (64, 64))
    g2 = cv2.resize(cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY), (64, 64))
    diff = float(np.mean(np.abs(g1.astype(np.float32) - g2.astype(np.float32))))
    return diff >= 0.5


def _face():
    global _FACE
    if _FACE is None:
        import insightface
        from insightface.app import FaceAnalysis
        app = FaceAnalysis(name="buffalo_l", providers=["CPUExecutionProvider"])
        app.prepare(ctx_id=-1)
        _FACE = app
    return _FACE


def _db() -> DB:
    # criar_schema + garantir_admin rodam UMA vez no startup (lifespan),
    # não a cada requisição (evita ~10 queries DDL por chamada).
    return conectar()


# ---- cache in-memory (TTL) para endpoints de leitura ----
# Reduz a latência nas trocas de aba frequentes. Invalidado em toda mutação.
_CACHE: dict = {}
_CACHE_TTL = 10.0


def _ler_cache(chave: str):
    item = _CACHE.get(chave)
    if item and time.time() - item[0] < _CACHE_TTL:
        return item[1]
    return None


def _gravar_cache(chave: str, valor) -> None:
    _CACHE[chave] = (time.time(), valor)


def _invalidar_cache() -> None:
    _CACHE.clear()


def _horario_entrada(con: DB, nome: str) -> str | None:
    """Horário de entrada esperado (HH:MM) do colaborador, pelo grupo/membro."""
    row = con.execute(
        "SELECT COALESCE(m.entrada, g.entrada) FROM grupo_membros m "
        "JOIN grupos g ON g.id = m.grupo_id WHERE m.colaborador=?", (nome,)).fetchone()
    return row[0] if row else None


def _notificar_atraso(nome: str, atraso_min: int) -> None:
    """Notifica o Rodrigo (Bitrix) quando alguém bate entrada atrasado.

    Best-effort: qualquer falha é silenciosa — a notificação nunca derruba a batida.
    """
    if not BITRIX_WEBHOOK:
        return
    try:
        msg = f"⏰ ATRASO — {nome} bateu entrada {atraso_min} min depois do horário"
        req = urllib.request.Request(
            BITRIX_WEBHOOK + "im.notify.json",
            data=urllib.parse.urlencode({"to": BITRIX_ADMIN_ID, "message": msg,
                                         "type": "SYSTEM"}).encode())
        urllib.request.urlopen(req, timeout=5).read()
    except Exception:
        pass


def _b64_to_img(b64: str) -> np.ndarray:
    try:
        raw = base64.b64decode(b64.split(",", 1)[-1])
    except Exception as e:
        raise HTTPException(400, f"foto_base64 inválida: {e}")
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise HTTPException(400, "não foi possível decodificar a imagem")
    return img


def _embedding(img: np.ndarray) -> np.ndarray:
    """Extrai o embedding do maior rosto, validando a qualidade (confiança + pose)."""
    faces = _face().get(img)
    if not faces:
        raise HTTPException(422, "nenhum rosto detectado — aproxime-se da câmera")
    faces.sort(key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]), reverse=True)
    f = faces[0]
    yaw, pitch, roll = (f.pose if f.pose is not None else (0.0, 0.0, 0.0))
    ok, motivo = avaliar_qualidade_rosto(float(f.det_score), float(yaw), float(pitch), float(roll))
    if not ok:
        raise HTTPException(422, motivo)
    return f.normed_embedding.astype(np.float32)


def _embedding_medio(fotos_b64: list) -> np.ndarray:
    """Média normalizada dos embeddings de várias capturas (robustez).

    Cada captura é validada individualmente; se alguma falhar na qualidade,
    propaga o erro (não cadastra com foto ruim). A média reduz instabilidade
    de um único ângulo/iluminação.
    """
    embs = [_embedding(_b64_to_img(f)) for f in fotos_b64]
    m = np.mean(np.stack(embs), axis=0)
    return m / np.linalg.norm(m)


def _emb_do_payload(foto_base64: str | None, fotos: list | None) -> np.ndarray:
    """Embedding a partir do payload: média de N capturas, ou captura única."""
    if fotos:
        return _embedding_medio(fotos)
    if not foto_base64:
        raise HTTPException(422, "foto_base64 é obrigatória")
    return _embedding(_b64_to_img(foto_base64))


def _salvar_foto(nome: str, foto_base64: str | None, fotos: list | None) -> None:
    """Salva a foto exibível do colaborador em JPEG, com escrita atômica.

    Usa a primeira captura (ou a única) já validada no cadastro. A troca
    temp->final via os.replace garante que nunca fique um arquivo pela metade.
    """
    fonte = (fotos[0] if fotos else None) or foto_base64
    if not fonte:
        return
    img = _b64_to_img(fonte)
    ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
    if not ok:
        return
    FOTOS_DIR.mkdir(exist_ok=True)
    alvo = FOTOS_DIR / f"{nome}.jpg"
    tmp = FOTOS_DIR / f"{nome}.jpg.tmp"
    with open(tmp, "wb") as fh:
        fh.write(buf.tobytes())
    os.replace(tmp, alvo)


def _embeddings_cadastrados() -> dict[str, np.ndarray]:
    out = {}
    if EMB_DIR.is_dir():
        for f in EMB_DIR.glob("*.npy"):
            try:
                out[f.stem] = np.load(f).astype(np.float32)
            except (OSError, ValueError):
                continue
    return out


def _ultimo_tipo(con: DB, colaborador: str) -> str | None:
    hoje = time.strftime("%Y-%m-%d")
    row = con.execute(
        "SELECT tipo FROM pontos WHERE colaborador=? AND substr(quando,1,10)=? "
        "ORDER BY id DESC LIMIT 1", (colaborador, hoje)).fetchone()
    return row[0] if row else None


def _proximo_nsr_hash(con: DB, cpf: str, quando: str) -> tuple:
    """Próximo NSR global e hash encadeado da marcação (inviolabilidade do AFD)."""
    ult = con.execute("SELECT COALESCE(MAX(nsr), 0) FROM pontos").fetchone()
    nsr = int(ult[0] or 0) + 1
    ult_hash = con.execute(
        "SELECT hash FROM pontos WHERE id = (SELECT MAX(id) FROM pontos)").fetchone()
    hash_ant = (ult_hash[0] if ult_hash and ult_hash[0] else "") or "0" * 64
    return nsr, hash_encadeado(hash_ant, nsr, cpf or "0", quando)


class Cadastro(BaseModel):
    nome: str
    foto_base64: str | None = None
    fotos: list[str] | None = None      # múltiplas capturas (média p/ robustez)
    cpf: str | None = None
    telefone: str | None = None


class AutoCadastro(BaseModel):
    nome: str
    cpf: str
    telefone: str | None = None
    foto_base64: str | None = None
    fotos: list[str] | None = None
    grupo_id: int | None = None


class Reconhecimento(BaseModel):
    foto_base64: str
    foto_base64_2: str | None = None      # 2º frame p/ liveness por movimento
    lat: float | None = None
    lng: float | None = None
    tipo: str | None = None


class Login(BaseModel):
    usuario: str
    senha: str


class Grupo(BaseModel):
    nome: str
    entrada: str
    saida: str
    dias: list[int] = [0, 1, 2, 3, 4]
    almoco_min: int = 0


class Membro(BaseModel):
    colaborador: str
    entrada: str | None = None
    saida: str | None = None
    almoco_min: int | None = None


class HorarioMembro(BaseModel):
    entrada: str | None = None
    saida: str | None = None
    almoco_min: int | None = None


def _autentica(authorization: str | None, x_admin_token: str | None) -> None:
    """Exige autenticação: JWT Bearer (padrão novo) ou X-Admin-Token (compat).

    A ordem de aceitação é: (1) header X-Admin-Token igual ao PONTO_ADMIN_TOKEN
    do env (compatibilidade temporária com o frontend antigo); (2) header
    Authorization: Bearer <jwt> assinado e não expirado.
    """
    if x_admin_token and ADMIN_TOKEN and secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        return
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization.split(" ", 1)[1].strip()
        if token and token_valido(token):
            return
    raise HTTPException(401, "não autenticado — informe um token válido")


@asynccontextmanager
async def lifespan(app):
    # inicializa schema + admin UMA vez no startup (não a cada requisição)
    con = conectar()
    try:
        criar_schema(con)
        garantir_admin(con)
    finally:
        con.close()
    yield


app = FastAPI(title="Ponto Digital", lifespan=lifespan)

# rate limiting simples (in-memory, por chave)
_RATE: dict[str, list[float]] = {}
MAX_PAYLOAD = 10_000_000   # 10 MB
PII_ROTAS = (
    "/api/colaboradores", "/api/pontos", "/api/relatorio", "/api/metricas",
    "/api/resumo", "/api/vinculos", "/api/espelho",
)


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limit(chave: str, limite: int, janela_seg: int) -> bool:
    """True se a chave ainda está dentro do limite; False se excedeu."""
    agora = time.time()
    ts = [t for t in _RATE.get(chave, []) if agora - t < janela_seg]
    _RATE[chave] = ts
    if len(ts) >= limite:
        return False
    ts.append(agora)
    return True


@app.middleware("http")
async def _seguranca_middleware(request: Request, call_next):
    # limite de payload
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > MAX_PAYLOAD:
        return JSONResponse({"detail": "payload muito grande"}, status_code=413)
    response = await call_next(request)
    # headers de segurança
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; "
        "img-src 'self' data: blob:; connect-src 'self'; "
        "worker-src 'self' blob:; frame-ancestors 'none'")
    path = request.url.path
    if any(path == r or path.startswith(r + "/") for r in PII_ROTAS):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        response.headers["Cache-Control"] = "no-store"
    return response


@app.post("/api/login")
def login(request: Request, payload: Login):
    """Autentica usuário+senha e devolve um JWT de sessão (12h)."""
    chave = _ip(request) + ":" + payload.usuario.strip()
    if not _rate_limit(chave, 5, 300):
        raise HTTPException(429, "muitas tentativas — tente novamente em 5 minutos")
    con = _db()
    row = con.execute("SELECT usuario, senha_hash FROM usuarios WHERE usuario=?",
                      (payload.usuario.strip(),)).fetchone()
    con.close()
    if row is None or not verificar_senha(payload.senha, row[1]):
        raise HTTPException(401, "usuário ou senha inválidos")
    _RATE.pop(chave, None)   # sucesso limpa o contador de falhas
    return {"ok": True, "usuario": row[0],
            "token": criar_token(row[0]), "expira_em_seg": TOKEN_TTL_SEG}


def _grupos_serializados(con: DB) -> list:
    grupos = []
    for g in con.execute("SELECT id, nome, entrada, saida, dias, almoco_min FROM grupos ORDER BY nome").fetchall():
        membros = [{"colaborador": m[0], "entrada": m[1], "saida": m[2], "almoco_min": m[3]}
                   for m in con.execute(
                       "SELECT colaborador, entrada, saida, almoco_min FROM grupo_membros "
                       "WHERE grupo_id=? ORDER BY colaborador", (g[0],)).fetchall()]
        grupos.append({"id": g[0], "nome": g[1], "entrada": g[2], "saida": g[3],
                       "dias": json.loads(g[4]), "almoco_min": g[5], "membros": membros})
    return grupos


@app.get("/api/configuracao")
def configuracao(authorization: str | None = Header(default=None),
                 x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    val = _ler_cache("configuracao")
    if val is not None:
        return val
    con = _db()
    grupos = _grupos_serializados(con)
    con.close()
    val = {"grupos": grupos, "empresa": _config_empregador()}
    _gravar_cache("configuracao", val)
    return val


@app.get("/api/grupos-publico")
def grupos_publico():
    """Grupos disponíveis para o auto-cadastro público (sem PII)."""
    con = _db()
    grupos = [{"id": g[0], "nome": g[1]}
              for g in con.execute("SELECT id, nome FROM grupos ORDER BY nome").fetchall()]
    con.close()
    return {"grupos": grupos}


@app.post("/api/grupos")
def criar_grupo(payload: Grupo, authorization: str | None = Header(default=None),
                x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    con.execute("INSERT INTO grupos (nome, entrada, saida, dias, almoco_min) VALUES (?, ?, ?, ?, ?)",
                (payload.nome.strip(), payload.entrada, payload.saida,
                 json.dumps(payload.dias), int(payload.almoco_min or 0)))
    con.commit()
    gid = con.execute("SELECT id FROM grupos WHERE nome=?", (payload.nome.strip(),)).fetchone()[0]
    con.close()
    return {"ok": True, "id": gid}


@app.put("/api/grupos/{gid}")
def atualizar_grupo(gid: int, payload: Grupo, authorization: str | None = Header(default=None),
                    x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    con.execute("UPDATE grupos SET nome=?, entrada=?, saida=?, dias=?, almoco_min=? WHERE id=?",
                (payload.nome.strip(), payload.entrada, payload.saida,
                 json.dumps(payload.dias), int(payload.almoco_min or 0), gid))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True}


@app.delete("/api/grupos/{gid}")
def excluir_grupo(gid: int, authorization: str | None = Header(default=None),
                  x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    con.execute("DELETE FROM grupo_membros WHERE grupo_id=?", (gid,))
    con.execute("DELETE FROM grupos WHERE id=?", (gid,))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True}


@app.post("/api/grupos/{gid}/membros")
def adicionar_membro(gid: int, payload: Membro,
                     authorization: str | None = Header(default=None),
                     x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    con.execute("INSERT INTO grupo_membros (grupo_id, colaborador, entrada, saida, almoco_min) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(grupo_id, colaborador) "
                "DO UPDATE SET entrada=excluded.entrada, saida=excluded.saida, almoco_min=excluded.almoco_min",
                (gid, payload.colaborador, payload.entrada, payload.saida, payload.almoco_min))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True}


@app.delete("/api/grupos/{gid}/membros/{nome}")
def remover_membro(gid: int, nome: str, authorization: str | None = Header(default=None),
                   x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    con.execute("DELETE FROM grupo_membros WHERE grupo_id=? AND colaborador=?", (gid, nome))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True}


@app.put("/api/grupos/{gid}/membros/{nome}")
def atualizar_membro(gid: int, nome: str, payload: HorarioMembro,
                     authorization: str | None = Header(default=None),
                     x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    # entrada/saida vazios (ou null) limpam o horário individual -> volta a herdar o grupo
    entrada = (payload.entrada or "").strip() or None
    saida = (payload.saida or "").strip() or None
    # almoco_min null/vazio -> herda o do grupo
    almoco = payload.almoco_min if payload.almoco_min is not None else None
    con.execute("UPDATE grupo_membros SET entrada=?, saida=?, almoco_min=? WHERE grupo_id=? AND colaborador=?",
                (entrada, saida, almoco, gid, nome))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True}


@app.post("/api/cadastrar")
def cadastrar(payload: Cadastro,
              authorization: str | None = Header(default=None),
              x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    nome = validar_nome(payload.nome)   # anti path-traversal + XSS
    emb = _emb_do_payload(payload.foto_base64, payload.fotos)
    EMB_DIR.mkdir(exist_ok=True)
    np.save(EMB_DIR / f"{nome}.npy", emb)
    _salvar_foto(nome, payload.foto_base64, payload.fotos)
    con = _db()
    con.execute("INSERT INTO colaboradores (nome, cpf, telefone, criado_em) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(nome) DO UPDATE SET cpf=excluded.cpf, "
                "telefone=excluded.telefone, criado_em=excluded.criado_em",
                (nome, payload.cpf, payload.telefone, time.strftime("%Y-%m-%d %H:%M:%S")))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True, "nome": nome}


@app.post("/api/auto-cadastro")
def auto_cadastro(payload: AutoCadastro, request: Request):
    """Cadastro público via link: nome + CPF + telefone + foto. Sem token."""
    if not _rate_limit("auto:" + _ip(request), 10, 3600):
        raise HTTPException(429, "muitos cadastros — tente novamente mais tarde")
    nome = validar_nome(payload.nome)   # anti path-traversal + XSS
    cpf = "".join(c for c in payload.cpf if c.isdigit())
    if not validar_cpf(cpf):
        raise HTTPException(400, "CPF inválido")
    con = _db()
    existente = con.execute("SELECT nome FROM colaboradores WHERE cpf=?", (cpf,)).fetchone()
    if existente:
        con.close()
        raise HTTPException(409, "CPF já cadastrado")   # sem revelar o nome vinculado
    if payload.grupo_id is not None:
        if not con.execute("SELECT 1 FROM grupos WHERE id=?", (payload.grupo_id,)).fetchone():
            con.close()
            raise HTTPException(404, "grupo não encontrado")
    emb = _emb_do_payload(payload.foto_base64, payload.fotos)
    EMB_DIR.mkdir(exist_ok=True)
    np.save(EMB_DIR / f"{nome}.npy", emb)
    _salvar_foto(nome, payload.foto_base64, payload.fotos)
    con.execute("INSERT INTO colaboradores (nome, cpf, telefone, criado_em) VALUES (?, ?, ?, ?)",
                (nome, cpf, payload.telefone, time.strftime("%Y-%m-%d %H:%M:%S")))
    if payload.grupo_id is not None:
        con.execute("INSERT INTO grupo_membros (grupo_id, colaborador) VALUES (?, ?) "
                    "ON CONFLICT(grupo_id, colaborador) DO NOTHING",
                    (payload.grupo_id, nome))
    con.commit(); con.close()
    _invalidar_cache()
    return {"ok": True, "nome": nome, "cpf": cpf}


@app.delete("/api/colaborador/{nome}")
def excluir(nome: str,
            authorization: str | None = Header(default=None),
            x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)
    con = _db()
    cur = con.execute("DELETE FROM colaboradores WHERE nome = ?", (nome,))
    con.commit(); con.close()
    _invalidar_cache()
    if cur.rowcount == 0:
        raise HTTPException(404, "colaborador não encontrado")
    arq = EMB_DIR / f"{nome}.npy"
    if arq.exists():
        arq.unlink()
    foto_arq = FOTOS_DIR / f"{nome}.jpg"
    if foto_arq.exists():
        foto_arq.unlink()
    return {"ok": True, "excluido": nome}


@app.post("/api/reconhecer")
def reconhecer(payload: Reconhecimento, request: Request):
    if not _rate_limit("recon:" + _ip(request), 30, 60):
        raise HTTPException(429, "muitas batidas — aguarde um instante")
    img = _b64_to_img(payload.foto_base64)
    emb = _embedding(img)
    # liveness por movimento: 2º frame deve diferir do 1º (pessoa viva, não foto)
    if payload.foto_base64_2:
        img2 = _b64_to_img(payload.foto_base64_2)
        if not _verificar_movimento(img, img2):
            return JSONResponse({"ok": False,
                                 "motivo": "sem movimento detectado — aproxime-se da câmera"},
                                status_code=403)
    cadastrados = _embeddings_cadastrados()
    if not cadastrados:
        raise HTTPException(409, "nenhum colaborador cadastrado ainda")
    melhor, melhor_sim = None, -1.0
    for nome, e in cadastrados.items():
        sim = float(np.dot(emb, e))
        if sim > melhor_sim:
            melhor, melhor_sim = nome, sim
    LIMIAR = 0.40
    if melhor_sim < LIMIAR:
        return JSONResponse({"ok": False, "motivo": "não reconhecido",
                             "confianca": round(melhor_sim, 4)}, status_code=401)
    # anti-fraude: só registra se a IA confirmar que é uma pessoa viva
    liveness = _liveness(img)
    if not liveness["vivo"]:
        return JSONResponse({"ok": False, "nome": melhor,
                             "confianca": round(melhor_sim, 4),
                             "motivo": "presença não validada: " + (liveness["motivo"] or "fraude")},
                            status_code=403)
    con = _db()
    # Anti-fraude de marcação: o tipo é SEMPRE decidido pelo servidor pela
    # máquina de estados (entrada -> pausa -> volta -> termino). O cliente não
    # pode forjar o tipo no payload (ex.: marcar "termino" quando o ciclo exige
    # "entrada"). O seletor no totem é apenas confirmação visual.
    tipo = proximo_tipo(_ultimo_tipo(con, melhor))
    agora = time.strftime("%Y-%m-%d %H:%M:%S")
    # atraso/antecipação em relação ao horário de entrada do grupo (só na entrada)
    atraso_min = None
    if tipo == "entrada":
        entrada_esperada = _horario_entrada(con, melhor)
        if entrada_esperada:
            atraso_min = atraso_minutos(agora, entrada_esperada)
            if atraso_min > 0:
                _notificar_atraso(melhor, atraso_min)
    # CPF para o AFD/AEJ e comprovante
    cpf_row = con.execute("SELECT cpf FROM colaboradores WHERE nome=?", (melhor,)).fetchone()
    cpf = (cpf_row[0] if cpf_row and cpf_row[0] else "").strip()
    # hash encadeado (inviolabilidade das marcações) + NSR sequencial global
    with _NSR_LOCK:
        nsr, hashcode = _proximo_nsr_hash(con, cpf or "0", agora)
        con.execute("INSERT INTO pontos (colaborador, confianca, quando, tipo, lat, lng, nsr, hash) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (melhor, round(melhor_sim, 4), agora, tipo, payload.lat, payload.lng, nsr, hashcode))
        con.commit()
    con.close()
    _invalidar_cache()
    comprovante = gerar_comprovante(melhor, cpf, agora, tipo, nsr, hashcode)
    resp = {"ok": True, "nome": melhor, "tipo": tipo,
            "tipo_nome": NOMES_TIPO[tipo], "confianca": round(melhor_sim, 4),
            "nsr": nsr, "comprovante": comprovante}
    if atraso_min is not None:
        resp["atraso_min"] = atraso_min
    return resp


class AjustePonto(BaseModel):
    colaborador: str
    quando: str                 # 'YYYY-MM-DD HH:MM:SS' (ou 'YYYY-MM-DD' p/ abono_falta)
    acao: str                   # inclusao | reclassificacao | abono_falta
    tipo_novo: str | None = None
    ponto_id: int | None = None
    motivo: str
    usuario: str | None = None


ACOES_VALIDAS = {"inclusao", "reclassificacao", "abono_falta"}


@app.post("/api/pontos/ajuste")
def ajustar_ponto(payload: AjustePonto,
                  authorization: str | None = Header(default=None),
                  x_admin_token: str | None = Header(default=None)):
    """Ajuste/vínculo manual de ponto com justificativa obrigatória e auditoria.

    REGRA FISCAL: nunca altera batida original. Inclusão grava NOVA linha em
    `pontos` (fonte='A', cadeia NSR/hash continua); reclassificação e abono
    gravam apenas em `ajustes` (auditoria: quem, quando, por quê).
    """
    _autentica(authorization, x_admin_token)
    nome = validar_nome(payload.colaborador)
    motivo = (payload.motivo or "").strip()
    if not motivo:
        raise HTTPException(400, "justificativa é obrigatória para qualquer ajuste")
    if payload.acao not in ACOES_VALIDAS:
        raise HTTPException(400, "ação inválida — use inclusao, reclassificacao ou abono_falta")
    con = _db()
    try:
        colab = con.execute("SELECT cpf FROM colaboradores WHERE nome=?", (nome,)).fetchone()
        if not colab:
            raise HTTPException(404, "colaborador não encontrado")
        cpf = (colab[0] or "").strip()
        usuario = (payload.usuario or "").strip() or "rh"
        agora = time.strftime("%Y-%m-%d %H:%M:%S")
        ponto_id = None
        tipo_novo = payload.tipo_novo
        if payload.acao == "inclusao":
            if tipo_novo not in NOMES_TIPO:
                raise HTTPException(400, "tipo_novo inválido para inclusão")
            with _NSR_LOCK:
                nsr, hashcode = _proximo_nsr_hash(con, cpf, payload.quando)
                cur = con.execute(
                    "INSERT INTO pontos (colaborador, confianca, quando, tipo, lat, lng, nsr, hash, "
                    "fonte, motivo, usuario_ajuste) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (nome, None, payload.quando, tipo_novo, None, None, nsr, hashcode,
                     "A", motivo, usuario))
                ponto_id = cur.lastrowid if hasattr(cur, "lastrowid") else con.execute(
                    "SELECT MAX(id) FROM pontos").fetchone()[0]
                cur = con.execute(
                    "INSERT INTO ajustes (ponto_id, colaborador, acao, tipo_novo, quando, motivo, usuario, criado_em) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (ponto_id, nome, payload.acao, tipo_novo, payload.quando, motivo, usuario, agora))
                con.commit()
                ajuste_id = cur.lastrowid if hasattr(cur, "lastrowid") else con.execute(
                    "SELECT MAX(id) FROM ajustes").fetchone()[0]
        else:
            if payload.acao == "reclassificacao":
                if not payload.ponto_id or tipo_novo not in NOMES_TIPO:
                    raise HTTPException(400, "reclassificação exige ponto_id e tipo_novo válidos")
                alvo = con.execute("SELECT id FROM pontos WHERE id=? AND colaborador=?",
                                   (payload.ponto_id, nome)).fetchone()
                if not alvo:
                    raise HTTPException(404, "batida não encontrada para este colaborador")
                ponto_id = payload.ponto_id
            else:  # abono_falta — só auditoria, por data
                if len(payload.quando.strip()) != 10:
                    raise HTTPException(400, "abono de falta usa data 'YYYY-MM-DD'")
                tipo_novo = None
            cur = con.execute(
                "INSERT INTO ajustes (ponto_id, colaborador, acao, tipo_novo, quando, motivo, usuario, criado_em) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (ponto_id, nome, payload.acao, tipo_novo, payload.quando, motivo, usuario, agora))
            con.commit()
            ajuste_id = cur.lastrowid if hasattr(cur, "lastrowid") else con.execute(
                "SELECT MAX(id) FROM ajustes").fetchone()[0]
    finally:
        con.close()
    _invalidar_cache()
    return {"ok": True, "ajuste_id": ajuste_id, "ponto_id": ponto_id}


@app.get("/api/pontos/ajustes")
def listar_ajustes(colaborador: str | None = None, de: str | None = None,
                   ate: str | None = None,
                   authorization: str | None = Header(default=None),
                   x_admin_token: str | None = Header(default=None)):
    """Auditoria dos ajustes de ponto: quem ajustou, quando e por quê."""
    _autentica(authorization, x_admin_token)
    q = "SELECT id, ponto_id, colaborador, acao, tipo_novo, quando, motivo, usuario, criado_em " \
        "FROM ajustes WHERE 1=1"
    args = []
    if colaborador:
        q += " AND colaborador=?"; args.append(colaborador)
    if de:
        q += " AND substr(quando,1,10)>=?"; args.append(de)
    if ate:
        q += " AND substr(quando,1,10)<=?"; args.append(ate)
    q += " ORDER BY id DESC LIMIT 500"
    con = _db()
    rows = con.execute(q, args).fetchall()
    con.close()
    chaves = ("id", "ponto_id", "colaborador", "acao", "tipo_novo", "quando",
              "motivo", "usuario", "criado_em")
    return {"ajustes": [dict(zip(chaves, r)) for r in rows]}


@app.get("/api/espelho")
def espelho(colaborador: str, de: str | None = None, ate: str | None = None,
            authorization: str | None = Header(default=None),
            x_admin_token: str | None = Header(default=None)):
    """Espelho de ponto por dia: batidas originais, visão efetiva pós-ajuste,
    pareamento Entrada/Intervalo/Saída e apuração CLT (extras, noturno, almoço)."""
    _autentica(authorization, x_admin_token)
    nome = validar_nome(colaborador)
    de = de or time.strftime("%Y-%m-01")
    ate = ate or time.strftime("%Y-%m-%d")
    con = _db()
    pts = con.execute(
        "SELECT id, tipo, quando, fonte, nsr, hash FROM pontos WHERE colaborador=? "
        "AND substr(quando,1,10)>=? AND substr(quando,1,10)<=? ORDER BY id",
        (nome, de, ate)).fetchall()
    aj = con.execute(
        "SELECT id, ponto_id, acao, tipo_novo, quando, motivo FROM ajustes "
        "WHERE colaborador=? AND substr(quando,1,10)>=? AND substr(quando,1,10)<=? ORDER BY id",
        (nome, de, ate)).fetchall()
    gm = con.execute(
        "SELECT g.dias, g.entrada, g.saida, g.almoco_min, m.entrada, m.saida, m.almoco_min "
        "FROM grupo_membros m JOIN grupos g ON g.id=m.grupo_id WHERE m.colaborador=?",
        (nome,)).fetchone()
    con.close()

    dias_semana = json.loads(gm[0]) if gm else [0, 1, 2, 3, 4]
    ent = (gm[4] or gm[1]) if gm else None
    saida = (gm[5] or gm[2]) if gm else None
    almoco = (gm[6] if gm and gm[6] is not None else (gm[3] if gm else 0)) or 0
    jornada_min = (jornada_efetiva_seg(ent, saida, almoco) // 60) if ent and saida else 480

    meta = {r[0]: (r[4], r[5]) for r in pts}   # id -> (nsr, hash) da batida original
    efetivas = aplicar_ajustes([(r[0], r[1], r[2], r[3]) for r in pts],
                               [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in aj])
    por_dia: dict[str, list] = {}
    for pid, tipo, quando, fonte, ajustado in efetivas["efetivas"]:
        por_dia.setdefault(quando[:10], []).append((pid, tipo, quando, fonte, ajustado))

    dias = []
    for data in sorted(por_dia):
        rows = por_dia[data]
        pareamento = parear_batidas([(t, q) for _, t, q, _, _ in rows])
        apur = apurar_dia([(t, q) for _, t, q, _, _ in rows], jornada_min,
                          dia_util=date.fromisoformat(data).weekday() in dias_semana)
        flags = []
        if pareamento["impares"]:
            flags.append("batida_impar")
        if pareamento["extras"]:
            flags.append("orfa")
        if apur["almoco_suprimido_min"] > 0:
            flags.append("almoco_suprimido")
        if apur["teto_excedido"]:
            flags.append("teto_excedido")
        atraso = atraso_minutos(pareamento["entrada"], ent) if (pareamento["entrada"] and ent) else None
        dias.append({
            "data": data,
            "batidas_originais": [{"id": pid, "tipo": t, "quando": q, "fonte": f,
                                   "nsr": meta[pid][0], "hash": meta[pid][1]}
                                  for pid, t, q, f, _ in rows],
            "batidas_efetivas": [{"id": pid, "tipo": t, "quando": q, "ajustado": ajst}
                                 for pid, t, q, _, ajst in rows],
            "pareamento": pareamento,
            "apuracao": apur,
            "abono": efetivas["abonos"].get(data),
            "flags": flags,
            "atraso_min": atraso,
        })

    # Art. 66: interjornada entre dias consecutivos (fonte única: clt.interjornada_min)
    for i in range(1, len(dias)):
        fim_ant = dias[i - 1]["pareamento"]["termino"]
        ini_atual = dias[i]["pareamento"]["entrada"]
        if fim_ant and ini_atual:
            descanso = interjornada_min(fim_ant, ini_atual)
            dias[i]["interjornada_min"] = descanso
            if descanso < 11 * 60:
                dias[i]["flags"].append("interjornada_insuficiente")

    # Art. 59: teto SEMANAL de extras (mesma regra de clt.fechamento_mensal)
    por_semana: dict[tuple, int] = {}
    for d in dias:
        sem = date.fromisoformat(d["data"]).isocalendar()[:2]
        por_semana[sem] = por_semana.get(sem, 0) + d["apuracao"]["extra_50_min"] + d["apuracao"]["extra_100_min"]

    tot = {"dias": len(dias),
           "trabalhado_min": sum(d["apuracao"]["trabalhou_min"] for d in dias),
           "regular_min": sum(d["apuracao"]["regular_min"] for d in dias),
           "extra_50_min": sum(d["apuracao"]["extra_50_min"] for d in dias),
           "extra_100_min": sum(d["apuracao"]["extra_100_min"] for d in dias),
           "noturno_min": sum(d["apuracao"]["noturno_min"] for d in dias),
           "deficit_min": sum(d["apuracao"]["deficit_min"] for d in dias)}
    tot["banco_min"] = tot["extra_50_min"] + tot["extra_100_min"] - tot["deficit_min"]
    tot["interjornadas_insuficientes"] = sum(
        1 for d in dias if "interjornada_insuficiente" in d["flags"])
    tot["teto_semanal_excedido"] = any(v > 600 for v in por_semana.values())
    return {"colaborador": nome, "de": de, "ate": ate, "dias": dias, "totais": tot}


# Teto defensivo de VOLUME do resumo: o painel pede o período inteiro de todos os
# colaboradores numa chamada só; acima disto a resposta é cortada e `truncado=true`
# avisa o usuário (nada aqui grava/muta — leitura pura).
TETO_RESUMO_ROWS = 20000


@app.get("/api/espelho/resumo")
def espelho_resumo(de: str | None = None, ate: str | None = None,
                   grupo: str | None = None,
                   authorization: str | None = Header(default=None),
                   x_admin_token: str | None = Header(default=None)):
    """Resumo do espelho de TODOS os colaboradores numa chamada só (mata o N+1
    do painel, que hoje busca /api/espelho uma vez por colaborador).

    Só leitura: 1 query de pontos do período + 1 de ajustes + 1 de colaboradores +
    1 de vínculos grupo/escala. Só dias PASSADOS entram nas contagens: hoje está em
    andamento e nunca conta como ímpar, incompleto, extra ou deficit. Dia de escala
    passado e sem nenhuma batida conta como incompleto e leva a jornada cheia de deficit
    — mas só para quem TEM escala (grupo): sem grupo a rota não inventa falta.
    """
    _autentica(authorization, x_admin_token)
    de = de or time.strftime("%Y-%m-01")
    ate = ate or time.strftime("%Y-%m-%d")
    hoje = time.strftime("%Y-%m-%d")

    con = _db()
    try:
        vinculos = {}
        for r in con.execute(
                "SELECT m.colaborador, g.nome, g.dias, g.entrada, g.saida, g.almoco_min, "
                "m.entrada, m.saida, m.almoco_min FROM grupo_membros m "
                "JOIN grupos g ON g.id=m.grupo_id").fetchall():
            vinculos[r[0]] = r[1:]
        nomes = [r[0] for r in con.execute(
            "SELECT nome FROM colaboradores ORDER BY nome").fetchall()]
        pts = con.execute(
            "SELECT id, colaborador, tipo, quando, fonte FROM pontos "
            "WHERE substr(quando,1,10)>=? AND substr(quando,1,10)<=? "
            "ORDER BY id DESC LIMIT ?",
            (de, ate, TETO_RESUMO_ROWS + 1)).fetchall()
        aj = con.execute(
            "SELECT id, ponto_id, acao, tipo_novo, quando, motivo, colaborador FROM ajustes "
            "WHERE substr(quando,1,10)>=? AND substr(quando,1,10)<=? ORDER BY id",
            (de, ate)).fetchall()
    finally:
        con.close()

    # Corte por VOLUME: guarda as linhas mais recentes (as que o gestor olha primeiro)
    # e devolve a lista em ordem crescente de id, como o resto do processamento espera.
    truncado = len(pts) > TETO_RESUMO_ROWS
    pts = pts[:TETO_RESUMO_ROWS][::-1]
    por_colab_pts: dict[str, list] = {}
    for pid, colab, tipo, quando, fonte in pts:
        por_colab_pts.setdefault(colab, []).append((pid, tipo, quando, fonte))
    por_colab_aj: dict[str, list] = {}
    for aid, ponto_id, acao, tipo_novo, quando, motivo, colab in aj:
        por_colab_aj.setdefault(colab, []).append((aid, ponto_id, acao, tipo_novo, quando, motivo))

    saida = []
    for nome in nomes:
        vinc = vinculos.get(nome)
        if grupo and (not vinc or vinc[0] != grupo):
            continue
        esperados = set()
        if vinc:
            # escala/jornada do grupo (individual > grupo > padrão), igual a /api/espelho
            dias_semana = json.loads(vinc[1])
            ent = vinc[5] or vinc[2]
            sd = vinc[6] or vinc[3]
            almoco = vinc[7] if vinc[7] is not None else vinc[4]
            jornada_min = ((jornada_efetiva_seg(ent, sd, almoco or 0) // 60)
                           if ent and sd else JORNADA_PADRAO // 60)
            # dias de escala do período (fonte única: logica.dias_trabalho) — dia esperado
            # e sem batida conta como incompleto e leva a jornada cheia de deficit.
            try:
                esperados = set(dias_trabalho(dias_semana, de, ate))
            except ValueError:                  # de/ate fora do ISO: período sem dias
                pass
        else:
            # sem grupo não se INFERE escala: nenhum dia esperado (nada de falta/déficit
            # inventados — a aba Vínculos já sinaliza `sem_grupo`). Os dias úteis seg-sex
            # (default de /api/espelho) servem só para classificar extra dos dias COM batida.
            dias_semana, jornada_min = [0, 1, 2, 3, 4], JORNADA_PADRAO // 60

        visao = aplicar_ajustes(por_colab_pts.get(nome, []), por_colab_aj.get(nome, []))
        por_dia: dict[str, list] = {}
        for _pid, tipo, quando, _fonte, _ajst in visao["efetivas"]:
            por_dia.setdefault(quando[:10], []).append((tipo, quando))

        impares = incompletos = interjornadas = 0
        extra_50 = extra_100 = noturno = deficit = 0
        anterior = None                        # último 'termino' do dia anterior com batida
        for data in sorted(set(por_dia) | esperados):
            rows = por_dia.get(data, [])
            pareamento = parear_batidas(rows)
            # só dia PASSADO conta (hoje está em andamento) e abono de falta cancela
            # a falta do dia — nem ímpar/incompleto, nem extra/déficit.
            if data < hoje and data not in visao["abonos"]:
                if rows and pareamento["impares"]:
                    impares += 1
                if pareamento["faltando"]:
                    incompletos += 1
                apur = apurar_dia(rows, jornada_min,
                                  dia_util=date.fromisoformat(data).weekday() in dias_semana)
                extra_50 += apur["extra_50_min"]
                extra_100 += apur["extra_100_min"]
                noturno += apur["noturno_min"]
                deficit += apur["deficit_min"]
            if rows:
                # Art. 66: < 11h entre o ÚLTIMO 'termino' do dia com batida anterior e a
                # 'entrada' deste (mesmo critério de clt.fechamento_mensal)
                if anterior and pareamento["entrada"] and \
                        interjornada_min(anterior, pareamento["entrada"]) < 11 * 60:
                    interjornadas += 1
                anterior = max((q for t, q in rows if t == "termino"), default=None)

        saida.append({"nome": nome, "grupo": vinc[0] if vinc else None,
                      "dias_com_batida": len(por_dia), "dias_impares": impares,
                      "dias_incompletos": incompletos, "extra_50_min": extra_50,
                      "extra_100_min": extra_100, "noturno_min": noturno,
                      "deficit_min": deficit, "interjornadas_insuficientes": interjornadas,
                      "sem_biometria": not (EMB_DIR / f"{nome}.npy").exists()})

    totais = {"colaboradores": len(saida),
              "dias_impares": sum(c["dias_impares"] for c in saida),
              "extra_50_min": sum(c["extra_50_min"] for c in saida),
              "extra_100_min": sum(c["extra_100_min"] for c in saida),
              "noturno_min": sum(c["noturno_min"] for c in saida),
              "deficit_min": sum(c["deficit_min"] for c in saida),
              "sem_biometria": sum(1 for c in saida if c["sem_biometria"])}
    return {"de": de, "ate": ate, "grupo": grupo or "", "colaboradores": saida,
            "totais": totais, "truncado": truncado}


@app.get("/api/pontos")
def pontos(usuario: str | None = None, de: str | None = None,
           ate: str | None = None, limite: int = 200,
           authorization: str | None = Header(default=None),
           x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)   # PII + geolocalização
    q = "SELECT colaborador, tipo, confianca, quando, lat, lng FROM pontos WHERE 1=1"
    args = []
    if usuario:
        q += " AND colaborador=?"; args.append(usuario)
    if de:
        q += " AND substr(quando,1,10)>=?"; args.append(de)
    if ate:
        q += " AND substr(quando,1,10)<=?"; args.append(ate)
    q += " ORDER BY id DESC LIMIT ?"; args.append(max(1, min(limite, 2000)))
    con = _db()
    rows = con.execute(q, args).fetchall()
    con.close()
    return {"pontos": [{"colaborador": r[0], "tipo": r[1], "tipo_nome": NOMES_TIPO.get(r[1], r[1]),
                        "confianca": r[2], "quando": r[3], "lat": r[4], "lng": r[5]} for r in rows]}


@app.get("/api/metricas")
def metricas(data: str | None = None,
             authorization: str | None = Header(default=None),
             x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)   # jornada/horas de cada um
    alvo = data or time.strftime("%Y-%m-%d")
    val = _ler_cache(f"metricas:{alvo}")
    if val is not None:
        return val
    con = _db()
    usuarios = [r[0] for r in con.execute(
        "SELECT nome FROM colaboradores ORDER BY nome").fetchall()]
    # 1 única query p/ todos os pontos do dia (evita N+1 por usuário)
    por_colab: dict[str, list] = {}
    for colab, tipo, quando in con.execute(
            "SELECT colaborador, tipo, quando FROM pontos "
            "WHERE substr(quando,1,10)=? ORDER BY id", (alvo,)).fetchall():
        por_colab.setdefault(colab, []).append((tipo, quando))
    # também inclui quem tem ponto mas não está mais na lista de colaboradores
    for c in por_colab:
        if c not in usuarios:
            usuarios.append(c)
    usuarios.sort()
    res = [metricas_usuario(u, por_colab.get(u, [])) for u in usuarios]
    con.close()
    val = {"data": alvo, "usuarios": res,
           "presentes": sum(1 for r in res if r["estado"] in ("presente", "em pausa")),
           "total": len(res)}
    _gravar_cache(f"metricas:{alvo}", val)
    return val


@app.get("/api/resumo")
def resumo(authorization: str | None = Header(default=None),
           x_admin_token: str | None = Header(default=None)):
    """Agregação multi-dia por colaborador, com banco de horas pela jornada REAL.

    A jornada de cada colaborador vem do grupo/membro (entrada/saída); quem não
    tem horário configurado usa a jornada padrão (8h).
    """
    _autentica(authorization, x_admin_token)   # dados de trabalho de cada um
    val = _ler_cache("resumo")
    if val is not None:
        return val
    con = _db()
    # jornada real por colaborador (membro tem prioridade sobre o grupo; desconta o almoço)
    jornadas = {}
    for nome, ent, saida, almoco, dias in con.execute(
            "SELECT m.colaborador, COALESCE(m.entrada, g.entrada), "
            "COALESCE(m.saida, g.saida), COALESCE(m.almoco_min, g.almoco_min), g.dias "
            "FROM grupo_membros m JOIN grupos g ON g.id = m.grupo_id").fetchall():
        jornadas[nome] = (ent, saida, almoco, dias)
    # 1 única query p/ todos os pontos (evita N+1 por usuário)
    por_colab: dict[str, list] = {}
    for colab, tipo, quando in con.execute(
            "SELECT colaborador, tipo, quando FROM pontos ORDER BY colaborador, id").fetchall():
        por_colab.setdefault(colab, []).append((tipo, quando))
    out = []
    for u in sorted(por_colab):
        res = resumo_colaborador(u, por_colab[u])
        ent, saida, almoco, dias = jornadas.get(u, (None, None, 0, None))
        jorn = jornada_efetiva_seg(ent, saida, almoco) if ent and saida else JORNADA_PADRAO
        dias_semana = json.loads(dias) if dias else None
        por_dia: dict[str, list] = {}
        for t, q in por_colab[u]:
            por_dia.setdefault(q[:10], []).append((t, q))
        extra = deficit = 0
        for data, rows in por_dia.items():
            e, d = saldo_dia(rows, jorn, dias_semana, data)
            extra += e
            deficit += d
        res["jornada_seg"] = jorn
        res["extra_seg"] = extra
        res["deficit_seg"] = deficit
        res["banco_seg"] = extra - deficit
        out.append(res)
    con.close()
    val = {"resumo": out}
    _gravar_cache("resumo", val)
    return val


@app.get("/api/colaboradores")
def colaboradores(authorization: str | None = Header(default=None),
                  x_admin_token: str | None = Header(default=None)):
    _autentica(authorization, x_admin_token)   # CPF + telefone (PII)
    val = _ler_cache("colaboradores")
    if val is not None:
        return val
    con = _db()
    rows = con.execute("SELECT nome, cpf, telefone, criado_em FROM colaboradores ORDER BY nome").fetchall()
    con.close()
    val = {"colaboradores": [{"nome": r[0], "cpf": r[1], "telefone": r[2], "criado_em": r[3],
                              "tem_foto": (FOTOS_DIR / f"{r[0]}.jpg").exists()} for r in rows]}
    _gravar_cache("colaboradores", val)
    return val


@app.get("/api/colaborador/{nome}/foto")
def foto_colaborador(nome: str,
                     authorization: str | None = Header(default=None),
                     x_admin_token: str | None = Header(default=None)):
    """Devolve a foto (JPEG) do colaborador. Exige autenticação (dado PII)."""
    _autentica(authorization, x_admin_token)
    nome = validar_nome(nome)   # anti path-traversal
    arq = FOTOS_DIR / f"{nome}.jpg"
    if not arq.exists():
        raise HTTPException(404, "sem foto")
    return FileResponse(arq, media_type="image/jpeg")


@app.get("/api/vinculos")
def listar_vinculos(authorization: str | None = Header(default=None),
                    x_admin_token: str | None = Header(default=None)):
    """Vínculo de cada colaborador: Bitrix, biometria facial e grupo/escala.
    Serve para a UI corrigir vínculos quebrados sem rodar scripts no terminal."""
    _autentica(authorization, x_admin_token)   # CPF + telefone (PII)
    con = _db()
    grupos_de: dict[str, tuple] = {}
    for nome, gid, gnom in con.execute(
            "SELECT m.colaborador, g.id, g.nome FROM grupo_membros m "
            "JOIN grupos g ON g.id=m.grupo_id").fetchall():
        grupos_de[nome] = (gid, gnom)
    rows = con.execute(
        "SELECT nome, cpf, telefone, bitrix_id FROM colaboradores ORDER BY nome").fetchall()
    con.close()
    out = []
    for nome, cpf, telefone, bitrix_id in rows:
        biometria = "ativa" if (EMB_DIR / f"{nome}.npy").exists() else "pendente"
        tem_foto = (FOTOS_DIR / f"{nome}.jpg").exists()
        gid, gnom = grupos_de.get(nome, (None, None))
        pend = []
        if biometria == "pendente":
            pend.append("sem_biometria")
        if gid is None:
            pend.append("sem_grupo")
        if not (cpf or "").strip():
            pend.append("sem_cpf")
        if not (bitrix_id or "").strip():
            pend.append("sem_bitrix")
        out.append({"nome": nome, "cpf": cpf, "telefone": telefone, "bitrix_id": bitrix_id,
                    "biometria": biometria, "tem_foto": tem_foto,
                    "grupo_id": gid, "grupo": gnom, "pendencias": pend})
    return {"vinculos": out}


class VinculosPayload(BaseModel):
    grupo_id: int | None = None
    bitrix_id: str | None = None


@app.put("/api/colaborador/{nome}/vinculos")
def atualizar_vinculos(nome: str, payload: VinculosPayload,
                       authorization: str | None = Header(default=None),
                       x_admin_token: str | None = Header(default=None)):
    """Corrige vínculos quebrados: grupo/escala e ID Bitrix do colaborador."""
    _autentica(authorization, x_admin_token)
    nome = validar_nome(nome)
    con = _db()
    try:
        if not con.execute("SELECT 1 FROM colaboradores WHERE nome=?", (nome,)).fetchone():
            raise HTTPException(404, "colaborador não encontrado")
        # chave ausente = não mexer; null explícito = remover vínculo de grupo
        if "grupo_id" in payload.model_fields_set:
            if payload.grupo_id is not None:
                if not con.execute("SELECT 1 FROM grupos WHERE id=?", (payload.grupo_id,)).fetchone():
                    raise HTTPException(404, "grupo não encontrado")
                con.execute("INSERT INTO grupo_membros (grupo_id, colaborador) VALUES (?, ?) "
                            "ON CONFLICT(grupo_id, colaborador) DO NOTHING", (payload.grupo_id, nome))
            else:
                con.execute("DELETE FROM grupo_membros WHERE colaborador=?", (nome,))
        if payload.bitrix_id is not None:
            con.execute("UPDATE colaboradores SET bitrix_id=? WHERE nome=?",
                        (payload.bitrix_id.strip(), nome))
        con.commit()
    finally:
        con.close()
    _invalidar_cache()
    return {"ok": True, "nome": nome, "grupo_id": payload.grupo_id,
            "bitrix_id": payload.bitrix_id}


@app.get("/api/relatorio/{nome}")
def relatorio(nome: str, mes: str | None = None,
              authorization: str | None = Header(default=None),
              x_admin_token: str | None = Header(default=None)):
    """Relatório individual completo (extrato do mês): dados + jornada + banco + faltas."""
    _autentica(authorization, x_admin_token)
    con = _db()
    colab = con.execute("SELECT nome, cpf, telefone FROM colaboradores WHERE nome=?",
                        (nome,)).fetchone()
    pts = con.execute("SELECT tipo, quando FROM pontos WHERE colaborador=? ORDER BY id",
                      (nome,)).fetchall()
    # grupo/escala da pessoa (nome, dias, entrada/saida/almoço do grupo e individual)
    gm = con.execute(
        "SELECT g.nome, g.dias, g.entrada, g.saida, g.almoco_min, m.entrada, m.saida, m.almoco_min "
        "FROM grupo_membros m JOIN grupos g ON g.id=m.grupo_id "
        "WHERE m.colaborador=?", (nome,)).fetchone()
    con.close()

    dados = {"nome": nome, "cpf": colab[1] if colab else None,
             "telefone": colab[2] if colab else None,
             "grupo": gm[0] if gm else None}

    # jornada real (individual > grupo > padrão 8h), descontando o intervalo (almoço)
    jornada = JORNADA_PADRAO
    dias_semana = None
    faltas = []
    calendario = []
    if gm:
        dias_semana = json.loads(gm[1])
        ent = gm[5] or gm[2]
        saida = gm[6] or gm[3]
        almoco = gm[7] if gm[7] is not None else gm[4]
        if ent and saida:
            jornada = jornada_efetiva_seg(ent, saida, almoco or 0)
        mes_alvo = mes or time.strftime("%Y-%m")
        ano, mm = int(mes_alvo[:4]), int(mes_alvo[5:7])
        _, ultimo = calendar.monthrange(ano, mm)
        de = f"{mes_alvo}-01"
        ate = f"{mes_alvo}-{ultimo:02d}"
        faltas = calcular_faltas(pts, dias_semana, de, ate)
        calendario = calendario_mensal(nome, pts, dias_semana, mes_alvo,
                                       jornada_seg=jornada)

    dados["faltas"] = faltas
    dados["total_faltas"] = len(faltas)
    dados["calendario"] = calendario
    dados.update(relatorio_individual(nome, pts, mes=mes, jornada_seg=jornada,
                                      dias_semana=dias_semana))
    return dados


MESES_PT = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
            "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
SEM_PT = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]


def _hhmm(minutos, sinal=""):
    if minutos is None or minutos == 0:
        return f"{sinal}00:00" if sinal else "00:00"
    return f"{sinal}{abs(minutos) // 60:02d}:{abs(minutos) % 60:02d}"


def _sinal_hhmm(minutos):
    if not minutos:
        return "00:00"
    if minutos > 0:
        return "+" + _hhmm(minutos)
    return "-" + _hhmm(abs(minutos))


def _hm(quando):
    return quando[11:16] if quando else "--:--"


@app.get("/api/relatorio/{nome}/consolidado")
def relatorio_consolidado(nome: str, mes: str | None = None,
                          authorization: str | None = Header(default=None),
                          x_admin_token: str | None = Header(default=None)):
    """Relatório Consolidado de Jornada & Ponto (REP-P, Portaria 671/2021)."""
    _autentica(authorization, x_admin_token)
    nome = validar_nome(nome)
    mes = mes or time.strftime("%Y-%m")
    try:
        ano, mm = int(mes[:4]), int(mes[5:7])
        _, ultimo = calendar.monthrange(ano, mm)
    except (ValueError, IndexError):
        raise HTTPException(400, "mes inválido — use YYYY-MM")

    con = _db()
    row = con.execute(
        "SELECT id, nome, cpf, telefone, criado_em, matricula, cargo, departamento "
        "FROM colaboradores WHERE nome=?", (nome,)).fetchone()
    pts = con.execute("SELECT tipo, quando FROM pontos WHERE colaborador=? ORDER BY id",
                      (nome,)).fetchall()
    gm = con.execute(
        "SELECT g.nome, g.dias, g.entrada, g.saida, g.almoco_min, m.entrada, m.saida, m.almoco_min "
        "FROM grupo_membros m JOIN grupos g ON g.id=m.grupo_id "
        "WHERE m.colaborador=?", (nome,)).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, "colaborador não encontrado")

    dias_semana, jornada_min, entrada, escala = [0, 1, 2, 3, 4], 480, "08:00", None
    if gm:
        dias_semana = json.loads(gm[1])
        ent, saida = gm[5] or gm[2], gm[6] or gm[3]
        almoco = gm[7] if gm[7] is not None else gm[4]
        escala = gm[0]
        if ent:
            entrada = ent
        if ent and saida:
            jornada_min = jornada_efetiva_seg(ent, saida, almoco or 0) // 60

    cpf, telefone = row[2], row[3]
    matricula = row[5] or f"MAT-{row[4][:4]}-{row[0]:04d}"

    por_dia: dict[str, list] = {}
    for t, q in pts:
        if q.startswith(mes):
            por_dia.setdefault(q[:10], []).append((t, q))

    extrato = []
    trabalhado_min = extra50_min = extra100_min = adicional_noturno_min = 0
    deficit_min = extras_dias = dias_trabalhados = dias_debito = dsr_dias = 0
    for d in calendario_mensal(nome, pts, dias_semana, mes, jornada_seg=jornada_min * 60):
        data = d["data"]
        item = {"dia": data[8:10], "sem": SEM_PT[date.fromisoformat(data).weekday()]}
        if d["status"] == "trabalhado":
            dia_util = date.fromisoformat(data).weekday() in dias_semana
            ap = apurar_dia(por_dia.get(data, []), jornada_min if dia_util else 0,
                            dia_util=dia_util)
            if ap["status"] == "OVERTIME":
                situacao = "Hora Extra" if dia_util else "Hora Extra (DSR)"
            elif ap["status"] == "DEFICIT":
                situacao = "Déficit de Horas"
            elif ap["status"] == "AUSENTE":
                situacao = "Falta"
            else:
                situacao = "Jornada Normal" if ap["status"] == "NORMAL" else ap["status"]
            item.update({
                "entrada": _hm(d.get("entrada")), "intervalo": _hm(d.get("pausa")),
                "retorno": _hm(d.get("volta")), "saida": _hm(d.get("termino")),
                "total": _hhmm(ap["trabalhou_min"]),
                "he50": "+" + _hhmm(ap["extra_50_min"]) if ap["extra_50_min"] > 0 else "-",
                "he100": "+" + _hhmm(ap["extra_100_min"]) if ap["extra_100_min"] > 0 else "-",
                "debito": "-" + _hhmm(ap["deficit_min"]) if ap["deficit_min"] > 0 else "-",
                "noturno": _hhmm(ap["noturno_min"]) if ap["noturno_min"] > 0 else "-",
                "situacao": situacao,
            })
            trabalhado_min += ap["trabalhou_min"]
            extra50_min += ap["extra_50_min"]
            extra100_min += ap["extra_100_min"]
            adicional_noturno_min += ap["adicional_noturno_min"]
            deficit_min += ap["deficit_min"]
            dias_trabalhados += 1
            if ap["extra_50_min"] > 0 or ap["extra_100_min"] > 0:
                extras_dias += 1
            if ap["deficit_min"] > 0:
                dias_debito += 1
        elif d["status"] == "falta":
            item.update({"entrada": "--:--", "intervalo": "--:--", "retorno": "--:--",
                         "saida": "--:--", "total": "00:00", "he50": "-", "he100": "-",
                         "noturno": "-", "debito": "-" + _hhmm(jornada_min),
                         "situacao": "Falta"})
        elif d["status"] == "folga":
            dsr_dias += 1
            item.update({"entrada": "--:--", "intervalo": "--:--", "retorno": "--:--",
                         "saida": "--:--", "total": "00:00", "he50": "-", "he100": "-",
                         "noturno": "-", "debito": "-", "situacao": "DSR / Folga"})
        else:
            item.update({"entrada": "--:--", "intervalo": "--:--", "retorno": "--:--",
                         "saida": "--:--", "total": "--:--", "he50": "-", "he100": "-",
                         "noturno": "-", "debito": "-", "situacao": "Aguardando"})
        extrato.append(item)

    de = f"{mes}-01"
    ate = f"{mes}-{ultimo:02d}"
    # Faltas só se consolidam até HOJE; dias futuros do mês permanecem "aguardando"
    # (coerente com o extrato, que não lança débito em dias ainda não vencidos).
    hoje = time.strftime("%Y-%m-%d")
    faltas = [d for d in calcular_faltas(pts, dias_semana, de, ate) if d <= hoje]
    faltas_integrais = len(faltas)
    deficit_min += faltas_integrais * jornada_min
    dias_debito += faltas_integrais
    banco_min = extra50_min + extra100_min - deficit_min
    dias_uteis = len(dias_trabalho(dias_semana, de, ate))
    assiduidade = round(dias_trabalhados / dias_uteis * 100) if dias_uteis else 0

    seed = f"{nome}|{cpf or ''}|{mes}"
    autenticidade = (f"REP-P-{matricula}-{mes[:4]}{mes[5:7]}-"
                     + hashlib.sha256(seed.encode()).hexdigest()[:6].upper())
    emp = _config_empregador()
    demonst = {
        "faltas": [f"Dia {d[8:10]} ({SEM_PT[date.fromisoformat(d).weekday()]})"
                   for d in faltas],
        "extras_dias": extras_dias,
        "extras_txt": f"+{_hhmm(extra50_min)} a 50% e +{_hhmm(extra100_min)} a 100%.",
        "debito_dias": dias_debito,
        "debito_total": _sinal_hhmm(-deficit_min),
        "dsr_dias": dsr_dias,
    }
    quadro = {
        "trabalhado": _hhmm(trabalhado_min),
        "previstas": _hhmm(dias_uteis * jornada_min),
        "dias_trabalhados": dias_trabalhados,
        "dias_uteis": dias_uteis,
        "assiduidade": assiduidade,
        "extra50": "+" + _hhmm(extra50_min),
        "extra100": "+" + _hhmm(extra100_min),
        "adicional_noturno": _hhmm(adicional_noturno_min),
        "deficit": _sinal_hhmm(-deficit_min),
        "faltas_integrais": faltas_integrais,
        "dias_debito": dias_debito,
        "creditos": "+" + _hhmm(extra50_min + extra100_min),
        "debitos": _sinal_hhmm(-deficit_min),
        "banco": _sinal_hhmm(banco_min),
        "situacao": ("Saldo Devedor / A Compensar" if banco_min < 0
                     else "Saldo Credor / A Receber" if banco_min > 0 else "Equilibrado"),
    }
    return {
        "nome": nome, "cpf": cpf, "telefone": telefone,
        "matricula": matricula, "cargo": row[6], "departamento": row[7],
        "competencia": f"{MESES_PT[mm - 1]} de {ano}",
        "escala": escala,
        "carga_diaria": f"{jornada_min // 60}h/dia ({entrada})",
        "emissao": time.strftime("%d/%m/%Y às %H:%M"),
        "autenticidade": autenticidade,
        "empresa": {"razao_social": emp["razao_social"], "id": emp["id"],
                    "modelo": emp["modelo"]},
        "quadro": quadro,
        "demonstrativo": demonst,
        "extrato": extrato,
    }


class PdfPayload(BaseModel):
    html: str


def _chrome_bin() -> str | None:
    cand = os.environ.get("PONTO_CHROME_BIN", "").strip()
    if cand and Path(cand).exists():
        return cand
    for p in ("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Chromium.app/Contents/MacOS/Chromium",
              "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if Path(p).exists():
            return p
    return None


@app.post("/api/gerar-pdf")
def gerar_pdf(payload: PdfPayload,
              authorization: str | None = Header(default=None),
              x_admin_token: str | None = Header(default=None)):
    """Gera PDF A4 do relatório consolidado (via Chrome/Chromium headless)."""
    _autentica(authorization, x_admin_token)
    html = (payload.html or "").strip()
    # HTML vem do próprio dashboard; rejeita script embutido por segurança.
    if len(html) < 40 or "<!doctype" not in html.lower() or "<script" in html.lower():
        raise HTTPException(400, "html inválido")
    chrome = _chrome_bin()
    if not chrome:
        raise HTTPException(501, "gerador de PDF indisponível (Chrome/Chromium não encontrado)")
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "relatorio.html"
        out = Path(td) / "relatorio.pdf"
        src.write_text(html, encoding="utf-8")
        try:
            subprocess.run([chrome, "--headless", "--disable-gpu", "--no-sandbox",
                            "--no-first-run", "--no-pdf-header-footer",
                            f"--user-data-dir={td}/profile",
                            f"--print-to-pdf={out}", str(src)],
                           capture_output=True, timeout=30, check=False)
        except subprocess.TimeoutExpired:
            raise HTTPException(504, "tempo esgotado ao gerar PDF")
        if not out.exists() or out.stat().st_size < 100:
            raise HTTPException(500, "falha ao gerar PDF")
        pdf_bytes = out.read_bytes()
    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition":
                             'attachment; filename="relatorio-consolidado.pdf"'})


def _config_empregador() -> dict:
    """Identificação do empregador/desenvolvedor (env) para AFD/AEJ."""
    return {
        "tipo_id": os.environ.get("PONTO_EMPRESA_TIPO_ID", "1"),      # 1=CNPJ 2=CPF
        "id": os.environ.get("PONTO_EMPRESA_CNPJ", ""),
        "razao_social": os.environ.get("PONTO_EMPRESA_RAZAO", ""),
        "inpi": os.environ.get("PONTO_EMPRESA_INPI", ""),
        "tipo_id_dev": os.environ.get("PONTO_DEV_TIPO_ID", "1"),
        "id_dev": os.environ.get("PONTO_DEV_CNPJ", ""),
        "modelo": "Ponto Digital",
    }


@app.get("/api/afd")
def afd(de: str | None = None, ate: str | None = None,
        authorization: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None)):
    """AFD (Arquivo Fonte de Dados) — Anexo I da Portaria MTP 671/2021."""
    _autentica(authorization, x_admin_token)
    con = _db()
    q = "SELECT colaborador, cpf, quando, tipo, nsr, hash, confianca FROM pontos " \
        "LEFT JOIN colaboradores ON colaboradores.nome = pontos.colaborador WHERE 1=1"
    args = []
    if de:
        q += " AND substr(pontos.quando,1,10)>=?"; args.append(de)
    if ate:
        q += " AND substr(pontos.quando,1,10)<=?"; args.append(ate)
    q += " ORDER BY pontos.nsr"
    rows = con.execute(q, args).fetchall()
    con.close()

    marcacoes = [{"nsr": r[4] or 0, "cpf": r[1] or "", "quando": r[2],
                  "hash": r[5] or "", "gravacao": r[2]} for r in rows]
    data_ini = de or (rows[0][2][:10] if rows else time.strftime("%Y-%m-%d"))
    data_fim = ate or (rows[-1][2][:10] if rows else time.strftime("%Y-%m-%d"))
    emp = _config_empregador()
    conteudo = gerar_afd(emp, marcacoes, data_ini, data_fim,
                         time.strftime("%Y-%m-%d %H:%M:%S"))
    return {"afd": conteudo, "total_marcacoes": len(marcacoes)}


@app.get("/api/aej")
def aej(de: str | None = None, ate: str | None = None,
        authorization: str | None = Header(default=None),
        x_admin_token: str | None = Header(default=None)):
    """AEJ (Arquivo Eletrônico de Jornada) — Anexo VI da Portaria MTP 671/2021."""
    _autentica(authorization, x_admin_token)
    con = _db()
    vinculos_rows = con.execute(
        "SELECT nome, cpf FROM colaboradores ORDER BY nome").fetchall()
    vinculos = [{"cpf": r[1] or "", "nome": r[0]} for r in vinculos_rows if r[1]]
    q = "SELECT colaborador, cpf, quando, tipo FROM pontos " \
        "LEFT JOIN colaboradores ON colaboradores.nome = pontos.colaborador WHERE 1=1"
    args = []
    if de:
        q += " AND substr(pontos.quando,1,10)>=?"; args.append(de)
    if ate:
        q += " AND substr(pontos.quando,1,10)<=?"; args.append(ate)
    q += " ORDER BY pontos.quando"
    rows = con.execute(q, args).fetchall()
    con.close()

    marcacoes = [{"cpf": r[1] or "", "quando": r[2], "tipo": r[3],
                  "fonte": "O"} for r in rows if r[1]]
    emp = _config_empregador()
    dev = {"nome_prog": "Ponto Digital", "versao": "1.0.0",
           "tipo_id": emp["tipo_id_dev"], "id": emp["id_dev"],
           "razao": emp["razao_social"], "email": os.environ.get("PONTO_DEV_EMAIL", "")}
    data_ini = de or (rows[0][2][:10] if rows else time.strftime("%Y-%m-%d"))
    data_fim = ate or (rows[-1][2][:10] if rows else time.strftime("%Y-%m-%d"))
    conteudo = gerar_aej(emp, dev, vinculos, marcacoes, data_ini, data_fim,
                         time.strftime("%Y-%m-%d %H:%M:%S"))
    return {"aej": conteudo, "total_marcacoes": len(marcacoes)}


@app.get("/api/health")
def health():
    try:
        con = _db()
        try:
            con.execute("SELECT 1")
        finally:
            con.close()
        db = "ok"
    except Exception:
        db = "erro"
    return {"ok": True, "db": db}


app.mount("/", StaticFiles(directory=str(STATIC), html=True), name="static")
