#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lógica pura do ponto digital — sem dependências de FastAPI ou do modelo facial.

Funções extraídas para serem testáveis de forma determinística (TDD):
  - proximo_tipo: máquina de estados entrada -> pausa -> volta -> termino -> entrada
  - metricas_usuario: jornada de um colaborador num dia (estado + horas)
  - resumo_colaborador: agregação multi-dia (total, dias, média)
"""
from __future__ import annotations

import re
import time
from datetime import date, timedelta

from clt import apurar_dia

TIPO_SEQUENCIA = {"entrada": "pausa", "pausa": "volta", "volta": "termino"}

# nome de colaborador: letras (com acento), espaço, apóstrofo, hífen, ponto, dígito.
# Proíbe '/', '\', '..', null bytes e caracteres de controle (anti path-traversal e XSS).
_NOME_RE = re.compile(r"^[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9 .'’-]*$")


def validar_nome(nome: str) -> str:
    """Valida o nome de colaborador. Levanta ValueError se inválido.

    Regras: 2..80 chars; só letras (acentuadas), espaços, apóstrofo, hífen,
    ponto e dígitos. Bloqueia caminho (/, \\, ..), null byte e controle.
    """
    nome = (nome or "").strip()
    if not (2 <= len(nome) <= 80):
        raise ValueError("nome deve ter entre 2 e 80 caracteres")
    if not _NOME_RE.match(nome):
        raise ValueError("nome contém caracteres inválidos")
    return nome


def proximo_tipo(ultimo_tipo: str | None) -> str:
    """Dado o último tipo registrado hoje, retorna o próximo (ou 'entrada')."""
    if not ultimo_tipo or ultimo_tipo == "termino":
        return "entrada"
    return TIPO_SEQUENCIA.get(ultimo_tipo, "entrada")


def _seg(q: str) -> float:
    return time.mktime(time.strptime(q, "%Y-%m-%d %H:%M:%S"))


def metricas_usuario(nome: str, rows: list, agora: str | None = None) -> dict:
    """Calcula a jornada de um colaborador num dia.

    rows: lista de tuplas (tipo, quando) em qualquer ordem.
    agora: timestamp de referência injetável para testes (default: hora real).
    """
    agora = agora or time.strftime("%Y-%m-%d %H:%M:%S")

    entrada = pausa = volta = termino = None
    for t, q in rows:
        if t == "entrada" and entrada is None:
            entrada = q
        elif t == "pausa" and pausa is None:
            pausa = q
        elif t == "volta" and volta is None:
            volta = q
        elif t == "termino" and termino is None:
            termino = q

    e = _seg(entrada) if entrada else None
    p = _seg(pausa) if pausa else None
    v = _seg(volta) if volta else None
    t = _seg(termino) if termino else None
    n = _seg(agora)

    trab = 0.0
    almoco = 0.0
    # primeiro período de trabalho: entrada -> pausa | termino | agora
    if e:
        fim1 = p if p is not None else (t if t is not None else n)
        trab += fim1 - e
    # almoço: pausa -> volta
    if p is not None and v is not None:
        almoco += v - p
    # segundo período: volta -> termino | agora
    if v is not None:
        fim2 = t if t is not None else n
        trab += fim2 - v

    if termino:
        estado = "encerrado"
    elif pausa and not volta:
        estado = "em pausa"
    elif entrada:
        estado = "presente"
    else:
        estado = "ausente"

    return {"nome": nome, "estado": estado,
            "entrada": entrada, "pausa": pausa, "volta": volta, "termino": termino,
            "trabalho_seg": round(trab), "almoco_seg": round(almoco), "batidas": len(rows)}


def resumo_colaborador(nome: str, pontos: list, agora: str | None = None) -> dict:
    """Agrega todos os pontos de um colaborador (vários dias).

    pontos: lista de tuplas (tipo, quando).
    Retorna: dias trabalhados, total de segundos e média diária.
    """
    agora = agora or time.strftime("%Y-%m-%d %H:%M:%S")

    por_dia: dict[str, list] = {}
    for t, q in pontos:
        por_dia.setdefault(q[:10], []).append((t, q))

    total = 0
    for dia, rows in por_dia.items():
        total += metricas_usuario(nome, rows, agora=agora)["trabalho_seg"]

    dias = len(por_dia)
    media = round(total / dias) if dias else 0
    return {"nome": nome, "dias": dias, "total_seg": total, "media_seg": media}


def validar_cpf(cpf: str) -> bool:
    """Valida um CPF (aceita com ou sem máscara). Verifica os 2 dígitos verificadores."""
    digitos = [int(c) for c in cpf if c.isdigit()]
    if len(digitos) != 11:
        return False
    if len(set(digitos)) == 1:          # 111.111.111-11 etc.
        return False
    d1 = (sum(d * (10 - i) for i, d in enumerate(digitos[:9])) * 10) % 11 % 10
    if d1 != digitos[9]:
        return False
    d2 = (sum(d * (11 - i) for i, d in enumerate(digitos[:10])) * 10) % 11 % 10
    return d2 == digitos[10]


DET_MIN = 0.5        # confiança mínima da detecção facial
POSE_MAX = 30.0      # desvio máximo de yaw/pitch (graus) para considerar frontal


def avaliar_qualidade_rosto(det_score: float, yaw: float = 0.0,
                            pitch: float = 0.0, roll: float = 0.0) -> tuple:
    """Avalia se uma detecção facial tem qualidade para reconhecimento.

    Retorna (ok, motivo). ok=False => motivo é uma mensagem para o usuário.
    """
    if det_score < DET_MIN:
        return False, "rosto pouco nítido — aproxime-se e olhe para a câmera"
    if abs(yaw) > POSE_MAX or abs(pitch) > POSE_MAX:
        return False, "olhe de frente para a câmera (rosto de lado ou inclinado)"
    return True, ""


def jornada_horario_seg(entrada: str, saida: str) -> int:
    """Jornada em segundos a partir de horários 'HH:MM'.

    Ex.: '08:00' -> '17:00' = 9h (32400s). Trata virada de meia-noite
    (saida <= entrada => soma 24h).
    """
    def _h(q: str) -> int:
        h, m = q.strip().split(":")
        return int(h) * 3600 + int(m) * 60
    e, s = _h(entrada), _h(saida)
    if s <= e:
        s += 24 * 3600
    return s - e


def jornada_efetiva_seg(entrada: str, saida: str, almoco_min: int = 0) -> int:
    """Jornada de trabalho EFETIVA: tempo no local menos o intervalo (almoço).

    Ex.: '08:00' -> '17:30' com 90min de almoço = 8h de trabalho (28800s).
    `almoco_min` é o intervalo ESPERADO (configurado no grupo), não o batido.
    """
    return max(0, jornada_horario_seg(entrada, saida) - int(almoco_min or 0) * 60)


def atraso_minutos(quando: str, entrada_esperada: str) -> int:
    """Diferença em minutos entre a batida (`quando`, 'YYYY-MM-DD HH:MM:SS') e o
    horário de entrada esperado ('HH:MM').

    Positivo = atrasado; negativo = antecipado; 0 = pontual.
    """
    eh, em = map(int, entrada_esperada.split(":"))
    esperado = eh * 3600 + em * 60
    atual = int(quando[11:13]) * 3600 + int(quando[14:16]) * 60
    return round((atual - esperado) / 60)


def banco_horas(pontos: list, jornada_seg: int = 8 * 3600, agora: str | None = None) -> int:
    """Saldo de banco de horas: total trabalhado - (jornada * dias). Pode ser negativo."""
    r = resumo_colaborador("", pontos, agora=agora)
    return r["total_seg"] - jornada_seg * r["dias"]


def saldo_dia(rows: list, jornada_seg: int, dias_semana: list | None, data: str) -> tuple:
    """(extra_seg, deficit_seg) de um dia pela CLT (fonte única: clt.apurar_dia).

    Dia em aberto (sem 'termino') ainda não tem saldo definitivo — devolve (0, 0).
    `dias_semana` None trata o dia como útil (escala desconhecida).
    """
    if not any(t == "termino" for t, _ in rows):
        return 0, 0
    dia_util = dias_semana is None or date.fromisoformat(data).weekday() in dias_semana
    ap = apurar_dia(rows, (jornada_seg // 60) if dia_util else 0, dia_util=dia_util)
    return ((ap["extra_50_min"] + ap["extra_100_min"]) * 60, ap["deficit_min"] * 60)


def relatorio_individual(nome: str, pontos: list, jornada_seg: int = 8 * 3600,
                         agora: str | None = None, mes: str | None = None,
                         dias_semana: list | None = None) -> dict:
    """Relatório detalhado (extrato) de um colaborador: dia a dia + totais.

    pontos: lista de tuplas (tipo, quando).
    mes: filtro opcional no formato 'YYYY-MM' (extrato do mês inteiro).
    Retorna: {nome, dias:[{data, entrada, pausa, volta, termino, almoco_seg,
              trabalhado_seg, extra_seg, deficit_seg}],
              totais:{dias, trabalhado_seg, extra_seg, deficit_seg, banco_seg}}
    """
    agora = agora or time.strftime("%Y-%m-%d %H:%M:%S")
    por_dia: dict[str, list] = {}
    for t, q in pontos:
        if mes and not q.startswith(mes):
            continue
        por_dia.setdefault(q[:10], []).append((t, q))

    dias = []
    total_trab = 0
    total_extra = 0
    total_deficit = 0
    for data in sorted(por_dia):
        m = metricas_usuario(nome, por_dia[data], agora=agora)
        trab = m["trabalho_seg"]
        extra, deficit = saldo_dia(por_dia[data], jornada_seg, dias_semana, data)
        total_trab += trab
        total_extra += extra
        total_deficit += deficit
        dias.append({"data": data, "entrada": m["entrada"], "pausa": m["pausa"],
                     "volta": m["volta"], "termino": m["termino"],
                     "almoco_seg": m["almoco_seg"], "trabalhado_seg": trab,
                     "extra_seg": extra, "deficit_seg": deficit})

    banco = total_extra - total_deficit
    return {"nome": nome, "dias": dias,
            "totais": {"dias": len(dias), "trabalhado_seg": total_trab,
                       "extra_seg": total_extra, "deficit_seg": total_deficit,
                       "banco_seg": banco}}


def dias_trabalho(dias_semana: list, de: str, ate: str) -> list[str]:
    """Datas (YYYY-MM-DD) entre `de` e `ate` (inclusive) que caem em `dias_semana`.

    dias_semana: lista de inteiros no padrão Python weekday(): 0=segunda ... 6=domingo.
    """
    d0 = date.fromisoformat(de)
    d1 = date.fromisoformat(ate)
    out = []
    d = d0
    while d <= d1:
        if d.weekday() in dias_semana:
            out.append(d.isoformat())
        d += timedelta(days=1)
    return out


def calcular_faltas(pontos: list, dias_semana: list, de: str, ate: str) -> list[str]:
    """Dias em que a pessoa deveria trabalhar (escala) mas NÃO bateu entrada.

    pontos: lista de tuplas (tipo, quando).
    """
    dias_com_entrada = {q[:10] for t, q in pontos if t == "entrada"}
    esperados = dias_trabalho(dias_semana, de, ate)
    return [d for d in esperados if d not in dias_com_entrada]


def calendario_mensal(nome: str, pontos: list, dias_semana: list, mes: str,
                      jornada_seg: int = 8 * 3600, agora: str | None = None) -> list:
    """Calendário completo do mês: todos os dias (1..último) com status.

    Cada dia retorna {"data", "status"} onde status é:
      - "trabalhado": bateu ponto (inclui horários e horas);
      - "falta":     dia útil (escala) já passado sem batida;
      - "aguardando": dia útil (escala) futuro, ainda sem registro;
      - "folga":     dia fora da escala (fim de semana etc.).
    """
    agora = agora or time.strftime("%Y-%m-%d %H:%M:%S")
    ano, mm = int(mes[:4]), int(mes[5:7])
    ultimo = (date(ano + 1, 1, 1) if mm == 12 else date(ano, mm + 1, 1)) - timedelta(days=1)

    por_dia: dict[str, list] = {}
    for t, q in pontos:
        if mes and not q.startswith(mes):
            continue
        por_dia.setdefault(q[:10], []).append((t, q))

    esperados = set(dias_trabalho(dias_semana, f"{mes}-01", ultimo.isoformat()))
    hoje = agora[:10]

    out = []
    d = date(ano, mm, 1)
    while d <= ultimo:
        ds = d.isoformat()
        if ds in por_dia:
            m = metricas_usuario(nome, por_dia[ds], agora=agora)
            trab = m["trabalho_seg"]
            extra, deficit = saldo_dia(por_dia[ds], jornada_seg, dias_semana, ds)
            out.append({"data": ds, "status": "trabalhado",
                        "entrada": m["entrada"], "pausa": m["pausa"],
                        "volta": m["volta"], "termino": m["termino"],
                        "almoco_seg": m["almoco_seg"], "trabalhado_seg": trab,
                        "extra_seg": extra, "deficit_seg": deficit})
        elif ds in esperados:
            out.append({"data": ds, "status": "aguardando" if ds > hoje else "falta"})
        else:
            out.append({"data": ds, "status": "folga"})
        d += timedelta(days=1)
    return out


_FRAUDE_NAO_FRAUDE = {"", "nenhuma", "none", "nao", "não", "false", "0", "null"}


def decidir_liveness(resp: dict) -> dict:
    """Interpreta a resposta da IA de liveness e decide vivo vs. fraude.

    resp: {"vivo": bool, "fraude": str|None, "motivo": str|None}
    retorna: {"vivo": bool, "motivo": str}  (motivo vazio = ok)

    Regras:
      - se `fraude` vier preenchido com algo diferente de "nenhuma"/etc., é fraude
        (decisivo, mesmo que `vivo` esteja True por engano);
      - senão, segue o campo `vivo` (False => não validado);
      - resposta vazia => vivo (fallback não bloqueante).
    """
    fraude = (resp.get("fraude") or "").strip().lower()
    vivo = bool(resp.get("vivo", True))
    motivo = (resp.get("motivo") or "").strip()

    if fraude not in _FRAUDE_NAO_FRAUDE:
        return {"vivo": False,
                "motivo": (f"fraude ({fraude}): {motivo}" if motivo else f"fraude ({fraude})")}
    if not vivo:
        return {"vivo": False, "motivo": motivo or "não validado pela IA"}
    return {"vivo": True, "motivo": ""}


def parear_batidas(rows: list) -> dict:
    """Pareia as batidas de UM dia na sequência 1ª Entrada -> Início Intervalo ->
    Fim Intervalo -> Saída (mesma convenção de `metricas_usuario`: a 1ª ocorrência
    de cada tipo ocupa o slot). Sobras são órfãs/duplicadas — nunca descartadas.

    rows: lista de (tipo, quando), qualquer ordem. tipo em
          {entrada, pausa, volta, termino}.
    Retorna {entrada, pausa, volta, termino, extras, faltando, impares, registradas}.
    `impares` = True quando o dia não fecha em pares (ciclo incompleto ou órfã).
    """
    slots = {"entrada": None, "pausa": None, "volta": None, "termino": None}
    extras = []
    for t, q in sorted(rows, key=lambda r: r[1]):
        if t in slots and slots[t] is None:
            slots[t] = q
        else:
            extras.append((t, q))
    faltando = [k for k, v in slots.items() if v is None]
    return {**slots, "extras": extras, "faltando": faltando,
            "impares": bool(faltando or extras), "registradas": len(rows)}


def aplicar_ajustes(pontos: list, ajustes: list) -> dict:
    """Monta a visão EFETIVA das batidas de um período aplicando os ajustes do RH.

    Regra fiscal: a lista `pontos` (linhas originais) nunca é alterada.
      - reclassificacao (ponto_id + tipo_novo): sobrepõe o tipo na visão efetiva;
      - inclusao (linha já em pontos com fonte='A'): entra marcada como ajustada;
      - abono_falta (por data): sai em `abonos` — o dia deixa de contar como falta.

    pontos: (id, tipo, quando, fonte). ajustes: (id, ponto_id, acao, tipo_novo, quando, motivo).
    Retorna {"efetivas": [(id, tipo, quando, fonte, ajustado)], "abonos": {data: {...}}}.
    """
    sobrescritas = {}
    abonos = {}
    for aid, ponto_id, acao, tipo_novo, quando, motivo in ajustes:
        if acao == "reclassificacao" and ponto_id:
            sobrescritas[ponto_id] = tipo_novo
        elif acao == "abono_falta":
            abonos[quando[:10]] = {"motivo": motivo, "ajuste_id": aid}
    efetivas = []
    for pid, tipo, quando, fonte in pontos:
        ajustado = pid in sobrescritas or fonte == "A"
        efetivas.append((pid, sobrescritas.get(pid, tipo), quando, fonte, ajustado))
    return {"efetivas": efetivas, "abonos": abonos}
