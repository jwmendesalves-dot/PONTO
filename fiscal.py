#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Arquivos fiscais do ponto eletrônico (Portaria MTP nº 671/2021).

Gera o AFD (Arquivo Fonte de Dados — Anexo I, posições fixas) e o AEJ
(Arquivo Eletrônico de Jornada — Anexo VI, pipe-delimitado), além do
comprovante de marcação com hash SHA-256 e o hash encadeado (hash chain)
que garante a inviolabilidade das marcações.

Tudo aqui é lógica pura (sem FastAPI/banco) — testável via TDD.
"""
from __future__ import annotations

import hashlib
from datetime import datetime

ASSINATURA_P7S = "ASSINATURA_DIGITAL_EM_ARQUIVO_P7S"


def crc16(s: str) -> str:
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). 4 hex chars sem '0x'."""
    crc = 0xFFFF
    for b in s.encode("latin-1", errors="replace"):
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def hash_encadeado(hash_anterior: str, nsr: int, cpf: str, datahora: str) -> str:
    """Hash SHA-256 encadeado da marcação (inviolabilidade)."""
    return sha256(f"{hash_anterior}|{nsr}|{cpf}|{datahora}")


def dh(datahora: str) -> str:
    """'YYYY-MM-DD HH:MM:SS' -> 'YYYY-MM-DDTHH:MM:00±HHMM' (offset real do servidor)."""
    dt = datetime.strptime(datahora, "%Y-%m-%d %H:%M:%S")
    return dt.strftime("%Y-%m-%dT%H:%M:00") + datetime.now().astimezone().strftime("%z")


def _a(s: str, n: int) -> str:
    """Campo alfanumérico: trunca/lpad com espaços à direita até n chars."""
    s = s or ""
    return s[:n].ljust(n)


def _n(s, n: int) -> str:
    """Campo numérico: trunca e alinha à direita com zeros à esquerda."""
    s = str(s or "").replace(".", "").replace("-", "").replace("/", "")
    s = "".join(c for c in s if c.isdigit())
    return s[-n:].rjust(n, "0")


def _cpf(s) -> str:
    """CPF: só dígitos, 11 chars (12 no AFD com dígito verificador do PIS... aqui só CPF)."""
    s = "".join(c for c in str(s or "") if c.isdigit())
    return s[-11:].rjust(11, "0")


# ---------- AFD (Anexo I, posições fixas) ----------

def registro_afd_cabecalho(empregador: dict, data_ini: str, data_fim: str,
                           geracao: str) -> str:
    """Registro tipo '1' (302 chars)."""
    linha = (
        _n("0", 9) +                       # 001-009
        "1" +                              # 010-010 tipo
        _n(empregador.get("tipo_id", "1"), 1) +   # 011-011 1=CNPJ 2=CPF
        _n(empregador.get("id", ""), 14) +        # 012-025 CNPJ/CPF
        _n("", 14) +                       # 026-039 CNO/CAEPF
        _a(empregador.get("razao_social", ""), 150) +  # 040-189
        _n(empregador.get("inpi", ""), 17) +       # 190-206 INPI
        data_ini +                         # 207-216
        data_fim +                         # 217-226
        dh(geracao) +                      # 227-250
        "003" +                            # 251-253 versão
        _n(empregador.get("tipo_id_dev", "1"), 1) +  # 254-254
        _n(empregador.get("id_dev", ""), 14) +      # 255-268
        _a(empregador.get("modelo", ""), 30)        # 269-298
    )
    return linha + crc16(linha)            # 299-302


def registro_afd_marcacao(nsr: int, cpf: str, datahora: str, gravacao: str,
                          coletor: str, online: str, hashcode: str) -> str:
    """Registro tipo '7' — marcação de ponto para REP-P (137 chars)."""
    linha = (
        _n(nsr, 9) +                       # 001-009 NSR
        "7" +                              # 010-010 tipo
        dh(datahora) +                     # 011-034 data-hora marcação
        _n(cpf, 12) +                      # 035-046 CPF
        dh(gravacao) +                     # 047-070 data-hora gravação
        _n(coletor, 2) +                   # 071-072 coletor
        _n(online, 1) +                    # 073-073 0=on-line 1=off-line
        _a(hashcode, 64)                   # 074-137 hash
    )
    return linha


def registro_afd_trailer(qtde: dict) -> str:
    """Registro tipo '9' (64 chars). qtde: {2: n, 3: n, 4: n, 5: n, 6: n, 7: n}."""
    return (
        "999999999" +                       # 001-009 literal
        _n(qtde.get(2, 0), 9) +            # 010-018
        _n(qtde.get(3, 0), 9) +            # 019-027
        _n(qtde.get(4, 0), 9) +            # 028-036
        _n(qtde.get(5, 0), 9) +            # 037-045
        _n(qtde.get(6, 0), 9) +            # 046-054
        _n(qtde.get(7, 0), 9) +            # 055-063
        "9"                                # 064-064
    )


def gerar_afd(empregador: dict, marcacoes: list[dict], data_ini: str,
              data_fim: str, geracao: str) -> str:
    """Gera o AFD completo (linhas terminadas em CR LF).

    marcacoes: lista (ordenada por NSR) de {cpf, quando, hash, gravacao?, coletor?}.
    """
    linhas = [registro_afd_cabecalho(empregador, data_ini, data_fim, geracao)]
    for m in marcacoes:
        linhas.append(registro_afd_marcacao(
            nsr=m["nsr"], cpf=m["cpf"], datahora=m["quando"],
            gravacao=m.get("gravacao", m["quando"]),
            coletor=m.get("coletor", "01"),
            online=m.get("online", "0"),
            hashcode=m.get("hash", "")))
    qtde = {7: len(marcacoes)}
    linhas.append(registro_afd_trailer(qtde))
    linhas.append(ASSINATURA_P7S.ljust(100))
    return "\r\n".join(linhas) + "\r\n"


# ---------- AEJ (Anexo VI, pipe-delimitado) ----------

_TP_MARC = {"entrada": "E", "volta": "E", "pausa": "S", "termino": "S"}


def _linha_aej(campos: list) -> str:
    return "|".join(str(c) for c in campos)


def gerar_aej(empregador: dict, dev: dict, vinculos: list[dict],
              marcacoes: list[dict], data_ini: str, data_fim: str,
              geracao: str) -> str:
    """Gera o AEJ (Anexo VI). vinculos: {cpf, nome, horario?}. marcacoes: {cpf, quando, tipo, fonte}."""
    linhas = []

    # 01 - Cabeçalho
    linhas.append(_linha_aej([
        "01", empregador.get("tipo_id", "1"), empregador.get("id", ""),
        "", "", empregador.get("razao_social", ""),
        data_ini, data_fim, dh(geracao), "001"]))

    # 02 - REPs utilizados (REP-P -> tpRep=3, nrRep=INPI)
    linhas.append(_linha_aej(["02", "1", "3", empregador.get("inpi", "")]))

    # 03 - Vínculos + 06 - matrícula eSocial (opcional)
    id_vinculo = {v["cpf"]: i + 1 for i, v in enumerate(vinculos)}
    for v in vinculos:
        linhas.append(_linha_aej(["03", id_vinculo[v["cpf"]], v["cpf"], v["nome"]]))

    # 04 - Horário contratual (se informado)
    for v in vinculos:
        h = v.get("horario") or {}
        if h:
            linhas.append(_linha_aej([
                "04", h.get("cod", "PADRAO"), h.get("dur_min", "480"),
                h.get("e1", "0800"), h.get("s1", "1200"),
                h.get("e2", "1300"), h.get("s2", "1800")]))

    # 05 - Marcações
    for m in marcacoes:
        vid = id_vinculo.get(m["cpf"], 0)
        tp = _TP_MARC.get(m.get("tipo", "entrada"), "E")
        linhas.append(_linha_aej([
            "05", vid, dh(m["quando"]), "1", tp, "1",
            m.get("fonte", "O"), "", m.get("motivo", "")]))

    # 07 - Ausências/banco de horas (vazio por ora)
    # 08 - PTRP
    linhas.append(_linha_aej([
        "08", dev.get("nome_prog", "Ponto Digital"), dev.get("versao", "1.0.0"),
        dev.get("tipo_id", "1"), dev.get("id", ""), dev.get("razao", ""),
        dev.get("email", "")]))

    # 99 - Trailer
    q = {}
    for l in linhas:
        q[l.split("|")[0]] = q.get(l.split("|")[0], 0) + 1
    linhas.append(_linha_aej([
        "99", q.get("01", 0), q.get("02", 0), q.get("03", 0), q.get("04", 0),
        q.get("05", 0), q.get("06", 0), q.get("07", 0), q.get("08", 0)]))
    linhas.append(ASSINATURA_P7S.ljust(100))

    return "\r\n".join(linhas) + "\r\n"


# ---------- Comprovante de marcação ----------

def gerar_comprovante(colaborador: str, cpf: str, quando: str, tipo: str,
                      nsr: int, hashcode: str) -> dict:
    """Comprovante de registro de ponto (dados + hash SHA-256)."""
    return {
        "colaborador": colaborador,
        "cpf": cpf,
        "quando": quando,
        "tipo": tipo,
        "nsr": nsr,
        "hash_sha256": hashcode,
    }
