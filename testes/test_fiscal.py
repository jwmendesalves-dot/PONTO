#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Testes dos arquivos fiscais (AFD/AEJ/comprovante) — TDD."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fiscal import (crc16, dh, gerar_aej, gerar_afd, gerar_comprovante,  # noqa: E402
                    hash_encadeado, registro_afd_cabecalho,
                    registro_afd_marcacao, registro_afd_trailer)


def test_crc16_valor_conhecido():
    # CRC-16/CCITT-FALSE da string "123456789" = 0x29B1
    assert crc16("123456789") == "29B1"


def test_crc16_4_hex_chars():
    assert len(crc16("qualquer coisa")) == 4


def test_hash_encadeado_deterministico_e_encadeado():
    h0 = "0" * 64
    h1 = hash_encadeado(h0, 1, "11144477735", "2026-10-07 08:00:00")
    h2 = hash_encadeado(h1, 2, "11144477735", "2026-10-07 17:00:00")
    assert len(h1) == 64 and len(h2) == 64
    assert h1 != h2
    # mesma entrada -> mesmo hash (determinístico)
    assert hash_encadeado(h0, 1, "11144477735", "2026-10-07 08:00:00") == h1


def test_dh_formato():
    from datetime import datetime
    offset = datetime.now().astimezone().strftime("%z")
    assert dh("2026-10-07 08:00:00") == "2026-10-07T08:00:00" + offset


def test_registro_afd_cabecalho_tamanho_302():
    emp = {"tipo_id": "1", "id": "12345678000199", "razao_social": "Teste LTDA",
           "inpi": "123456", "tipo_id_dev": "1", "id_dev": "99999999999",
           "modelo": "Ponto Digital"}
    r = registro_afd_cabecalho(emp, "2026-10-01", "2026-10-31", "2026-10-31 10:00:00")
    assert len(r) == 302
    assert r[9] == "1"          # tipo
    assert r[250:253] == "003"  # versão


def test_registro_afd_marcacao_tamanho_137():
    r = registro_afd_marcacao(1, "11144477735", "2026-10-07 08:00:00",
                              "2026-10-07 08:00:01", "01", "0", "a" * 64)
    assert len(r) == 137
    assert r[9] == "7"
    assert r[0:9] == "000000001"  # NSR


def test_registro_afd_trailer_tamanho_64():
    r = registro_afd_trailer({7: 3})
    assert len(r) == 64
    assert r[0:9] == "999999999"
    assert r[63] == "9"


def test_gerar_afd_com_linhas_corretas():
    emp = {"tipo_id": "1", "id": "12345678000199", "razao_social": "Teste LTDA",
           "inpi": "123456", "tipo_id_dev": "1", "id_dev": "99999999999",
           "modelo": "Ponto Digital"}
    marcacoes = [
        {"nsr": 1, "cpf": "11144477735", "quando": "2026-10-07 08:00:00",
         "hash": "a" * 64},
        {"nsr": 2, "cpf": "11144477735", "quando": "2026-10-07 17:00:00",
         "hash": "b" * 64},
    ]
    afd = gerar_afd(emp, marcacoes, "2026-10-01", "2026-10-31", "2026-10-31 10:00:00")
    linhas = afd.splitlines()
    # cabeçalho + 2 marcações + trailer + assinatura
    assert len(linhas) == 5
    assert len(linhas[0]) == 302   # cabeçalho
    assert len(linhas[1]) == 137   # marcação
    assert len(linhas[3]) == 64    # trailer
    assert len(linhas[4]) == 100   # assinatura
    assert "ASSINATURA_DIGITAL_EM_ARQUIVO_P7S" in linhas[4]


def test_gerar_aej_estrutura():
    emp = {"tipo_id": "1", "id": "12345678000199", "razao_social": "Teste LTDA",
           "inpi": "123456"}
    dev = {"nome_prog": "Ponto Digital", "versao": "1.0.0", "tipo_id": "1",
           "id": "99999999999", "razao": "Dev", "email": "dev@x.com"}
    vinculos = [{"cpf": "11144477735", "nome": "Fulano"}]
    marcacoes = [{"cpf": "11144477735", "quando": "2026-10-07 08:00:00",
                  "tipo": "entrada", "fonte": "O"}]
    aej = gerar_aej(emp, dev, vinculos, marcacoes, "2026-10-01", "2026-10-31",
                    "2026-10-31 10:00:00")
    linhas = aej.splitlines()
    assert linhas[0].startswith("01|")
    # trailer é a penúltima linha (a última é a assinatura)
    assert any(l.startswith("99|") for l in linhas)
    # marcação tipo entrada -> E
    marc = next(l for l in linhas if l.startswith("05|"))
    assert "|E|" in marc


def test_gerar_comprovante_com_hash():
    c = gerar_comprovante("Fulano", "11144477735", "2026-10-07 08:00:00",
                          "entrada", 1, "a" * 64)
    assert c["nsr"] == 1
    assert len(c["hash_sha256"]) == 64
    assert c["colaborador"] == "Fulano"
