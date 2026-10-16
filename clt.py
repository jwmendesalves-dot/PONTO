# -*- coding: utf-8 -*-
"""Regras CLT e apuração de jornada — módulo PURO (sem rede, testável).

Porte do PontoBio (timeCalculation.ts + cltRulesService.ts) para o ponto, com
os artigos da CLT preservados. Recebe batidas no formato do sistema
(`entrada`/`pausa`/`volta`/`termino`, timestamp 'YYYY-MM-DD HH:MM:SS') e devolve
a apuração do dia: hora extra 50%/100%, adicional noturno, intervalo
intrajornada suprimido, tolerância diária e teto de extras.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

# Art. 73 CLT — hora ficta noturna: 52min30s valem 60min.
FATOR_HORA_NOTURNA = 60 / 52.5

# Feriados nacionais de data fixa (MM-DD). Os móveis (Carnaval, Sexta-Feira
# Santa, Corpus Christi) variam por ano e ficam fora desta lista.
FERIADOS_NACIONAIS = {
    "01-01",  # Confraternização Universal
    "04-21",  # Tiradentes
    "05-01",  # Dia do Trabalho
    "09-07",  # Independência
    "10-12",  # Nossa Senhora Aparecida
    "11-02",  # Finados
    "11-15",  # Proclamação da República
    "11-20",  # Consciência Negra (Lei 14.759/2023)
    "12-25",  # Natal
}

_FMT = "%Y-%m-%d %H:%M:%S"


def _dt(q: str) -> datetime:
    return datetime.strptime(q, _FMT)


@dataclass
class RegrasClt:
    # 1. Tolerâncias (Art. 58 §1º e Súmula 366 TST)
    tolerancia_min: int = 10           # até 10 min/dia não geram desconto nem extra
    tolerancia_entrada_min: int = 5    # variação máxima por marcação de entrada
    tolerancia_saida_min: int = 5      # variação máxima por marcação de saída
    desconta_deficit_integral: bool = True  # excedeu a tolerância -> desconta o total

    # 2. Intervalo intrajornada / almoço (Art. 71 e Art. 611-A)
    almoco_obrigatorio_min: int = 60   # mínimo p/ jornada > 6h
    almoco_min_jornada_curta: int = 15  # mínimo p/ jornada 4h-6h
    indenizar_almoco_suprimido: bool = True  # suprimido é indenizado com 50% (Art. 71 §4º)

    # 3. Limites de hora extra e jornada (Art. 59)
    teto_extra_diaria_min: int = 120   # 2h suplementares/dia
    teto_extra_semanal_min: int = 600  # 10h suplementares/semana
    taxa_extra_50: float = 1.5         # dias úteis (Seg a Sáb)
    taxa_extra_100: float = 2.0        # domingos/feriados (DSR)

    # 4. Descanso interjornada e horário noturno (Art. 66 e Art. 73)
    descanso_interjornada_h: int = 11  # 11h consecutivas entre jornadas
    noturno_inicio: int = 22           # faixa noturna urbana 22h
    noturno_fim: int = 5               # até 5h
    adicional_noturno: float = 0.2     # 20%


CLT_PADRAO = RegrasClt()


def minutos_noturnos(inicio: str, fim: str, regras: RegrasClt = CLT_PADRAO) -> int:
    """Minutos noturnos no intervalo [inicio, fim), com o fator 60/52.5.

    Conta os minutos entre 22h e 5h (Art. 73 CLT) e aplica a hora ficta
    noturna (60 min / 52.5 min = 1.142857). Fiel ao calculateNightMinutes.
    """
    t0, t1 = _dt(inicio), _dt(fim)
    if t1 <= t0:
        return 0
    bruto = 0
    cur = t0
    while cur < t1:
        if cur.hour >= regras.noturno_inicio or cur.hour < regras.noturno_fim:
            bruto += 1
        cur += timedelta(minutes=1)
    return round(bruto * FATOR_HORA_NOTURNA)


def interjornada_min(fim_anterior: str, inicio_atual: str) -> int:
    """Descanso interjornada em minutos (Art. 66: mínimo 11h entre jornadas)."""
    return round((_dt(inicio_atual) - _dt(fim_anterior)).total_seconds() / 60)


def apurar_dia(batidas: list, jornada_esperada_min: int,
               dia_util: bool = True, regras: RegrasClt = CLT_PADRAO) -> dict:
    """Apura um dia de trabalho conforme a CLT.

    batidas: lista de tuplas (tipo, quando), tipo em {entrada, pausa, volta,
             termino}, quando 'YYYY-MM-DD HH:MM:SS'.
    jornada_esperada_min: jornada de referência do dia (0 se folga/DSR).
    dia_util: False = folga/DSR (trabalho vira extra 100%).

    Retorna {status, trabalhou_min, regular_min, extra_50_min, extra_100_min,
             noturno_min, adicional_noturno_min, deficit_min, almoco_min,
             almoco_suprimido_min, teto_excedido, teto_excedido_min}.
    """
    rows = sorted(batidas, key=lambda r: r[1])

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

    e = _dt(entrada).timestamp() if entrada else None
    p = _dt(pausa).timestamp() if pausa else None
    v = _dt(volta).timestamp() if volta else None
    t = _dt(termino).timestamp() if termino else None

    # trabalho e almoço (mesma aritmética do metricas_usuario)
    trab_seg = 0.0
    almoco_seg = 0.0
    if e is not None:
        fim1 = p if p is not None else t
        if fim1 is not None:
            trab_seg += fim1 - e
    if p is not None and v is not None:
        almoco_seg += v - p
    if v is not None and t is not None:
        trab_seg += t - v

    trabalhou_min = round(trab_seg / 60)
    almoco_min = round(almoco_seg / 60)

    # feriado nacional em dia útil conta como DSR (100%), não extra 50%
    data_iso = rows[0][1][:10] if rows else None
    if data_iso and data_iso[5:] in FERIADOS_NACIONAIS:
        dia_util = False

    # adicional noturno (só sobre os períodos efetivamente trabalhados)
    noturno_min = 0
    if entrada:
        fim1 = pausa if pausa else termino
        if fim1:
            noturno_min += minutos_noturnos(entrada, fim1, regras)
    if volta and termino:
        noturno_min += minutos_noturnos(volta, termino, regras)
    adicional_noturno_min = round(noturno_min * regras.adicional_noturno)

    regular_min = 0
    extra_50_min = 0
    extra_100_min = 0
    deficit_min = 0
    almoco_suprimido_min = 0
    teto_excedido = False
    teto_excedido_min = 0
    status = "NORMAL"

    if not dia_util:
        if trabalhou_min > 0:
            extra_100_min = trabalhou_min
            status = "OVERTIME"
            if trabalhou_min > regras.teto_extra_diaria_min:
                teto_excedido = True
                teto_excedido_min = trabalhou_min - regras.teto_extra_diaria_min
        else:
            status = "FOLGA"
    else:
        diff = trabalhou_min - jornada_esperada_min
        if abs(diff) <= regras.tolerancia_min:
            regular_min = trabalhou_min
            status = "NORMAL"
        elif diff > 0:
            regular_min = jornada_esperada_min
            extra_50_min = diff
            status = "OVERTIME"
            if extra_50_min > regras.teto_extra_diaria_min:
                teto_excedido = True
                teto_excedido_min = extra_50_min - regras.teto_extra_diaria_min
        else:
            regular_min = trabalhou_min
            deficit_min = (abs(diff) if regras.desconta_deficit_integral
                           else max(0, abs(diff) - regras.tolerancia_min))
            status = "AUSENTE" if trabalhou_min == 0 else "DEFICIT"

        # intervalo intrajornada suprimido (Art. 71 §1º e §4º)
        minimo_almoco = 0
        if jornada_esperada_min > 360:
            minimo_almoco = regras.almoco_obrigatorio_min
        elif jornada_esperada_min > 240:
            minimo_almoco = regras.almoco_min_jornada_curta
        if trabalhou_min > 0 and minimo_almoco and almoco_min < minimo_almoco:
            almoco_suprimido_min = minimo_almoco - almoco_min
            if regras.indenizar_almoco_suprimido:
                extra_50_min += almoco_suprimido_min

    return {
        "status": status,
        "trabalhou_min": trabalhou_min,
        "regular_min": regular_min,
        "extra_50_min": extra_50_min,
        "extra_100_min": extra_100_min,
        "noturno_min": noturno_min,
        "adicional_noturno_min": adicional_noturno_min,
        "deficit_min": deficit_min,
        "almoco_min": almoco_min,
        "almoco_suprimido_min": almoco_suprimido_min,
        "teto_excedido": teto_excedido,
        "teto_excedido_min": teto_excedido_min,
    }


def fechamento_mensal(batidas: list, jornada_esperada_min: int,
                      dias_semana: list, mes: str,
                      regras: RegrasClt = CLT_PADRAO) -> dict:
    """Consolida o espelho de ponto do mês (apuração CLT dia a dia).

    batidas: lista de (tipo, quando). dias_semana: escala da pessoa
    (weekday Python: 0=segunda ... 6=domingo). mes: 'YYYY-MM'.

    Só os dias com batida entram na lista `dias`; os totais consolidam
    trabalhado/regular/extra 50/extra 100/noturno/adicional noturno/deficit e o
    banco de horas (extra 50 + extra 100 − deficit).
    """
    por_dia: dict[str, list] = {}
    for t, q in batidas:
        if q.startswith(mes):
            por_dia.setdefault(q[:10], []).append((t, q))

    dias = []
    tot = {"dias": 0, "trabalhado_min": 0, "regular_min": 0, "extra_50_min": 0,
           "extra_100_min": 0, "noturno_min": 0, "adicional_noturno_min": 0,
           "deficit_min": 0}

    for ds in sorted(por_dia):
        dia_util = date.fromisoformat(ds).weekday() in dias_semana
        r = apurar_dia(por_dia[ds], jornada_esperada_min if dia_util else 0,
                       dia_util=dia_util, regras=regras)
        r["data"] = ds
        dias.append(r)
        tot["dias"] += 1
        tot["trabalhado_min"] += r["trabalhou_min"]
        tot["regular_min"] += r["regular_min"]
        tot["extra_50_min"] += r["extra_50_min"]
        tot["extra_100_min"] += r["extra_100_min"]
        tot["noturno_min"] += r["noturno_min"]
        tot["adicional_noturno_min"] += r["adicional_noturno_min"]
        tot["deficit_min"] += r["deficit_min"]

    # Art. 66 CLT — descanso interjornada: sinaliza quando < 11h entre o fim de uma
    # jornada (última 'termino') e o início da seguinte (1ª 'entrada').
    for d in dias:
        d["interjornada_min"] = None
        d["interjornada_insuficiente"] = False
    for i in range(1, len(dias)):
        rows_ant = sorted(por_dia[dias[i - 1]["data"]], key=lambda r: r[1])
        rows_atual = sorted(por_dia[dias[i]["data"]], key=lambda r: r[1])
        fim_ant = next((q for t, q in reversed(rows_ant) if t == "termino"), None)
        ini_atual = next((q for t, q in rows_atual if t == "entrada"), None)
        if fim_ant and ini_atual:
            descanso = interjornada_min(fim_ant, ini_atual)
            dias[i]["interjornada_min"] = descanso
            dias[i]["interjornada_insuficiente"] = descanso < regras.descanso_interjornada_h * 60
    tot["interjornadas_insuficientes"] = sum(
        1 for d in dias if d.get("interjornada_insuficiente"))

    # Art. 59 — teto SEMANAL de extras: soma (extra 50 + extra 100) por semana ISO.
    por_semana: dict[tuple, int] = {}
    for d in dias:
        sem = date.fromisoformat(d["data"]).isocalendar()[:2]
        por_semana[sem] = por_semana.get(sem, 0) + d["extra_50_min"] + d["extra_100_min"]
    tot["teto_semanal_excedido"] = any(
        v > regras.teto_extra_semanal_min for v in por_semana.values())

    tot["banco_min"] = tot["extra_50_min"] + tot["extra_100_min"] - tot["deficit_min"]
    return {"mes": mes, "dias": dias, "totais": tot}
