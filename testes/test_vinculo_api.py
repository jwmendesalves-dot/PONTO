import os
import sys
import time

os.environ.setdefault("PONTO_ADMIN_TOKEN", "token-de-teste")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
from clt import apurar_dia  # noqa: E402
from db import conectar  # noqa: E402

client = TestClient(app)
TOKEN = "token-de-teste"


def _criar_colaborador(nome="Maria Teste", cpf="11144477735"):
    con = conectar()
    try:
        con.execute("INSERT OR IGNORE INTO colaboradores (nome, cpf, telefone, criado_em) "
                    "VALUES (?, ?, ?, ?)", (nome, cpf, "11999990000", "2026-10-15 10:00:00"))
        con.commit()
    finally:
        con.close()


def _limpar_vinculos_de_teste():
    # o banco persiste entre rodadas da suíte; limpa sobras de grupo/vínculo
    con = conectar()
    try:
        con.execute("DELETE FROM grupo_membros WHERE colaborador=?", ("Maria Teste",))
        con.execute("DELETE FROM grupo_membros WHERE grupo_id IN "
                    "(SELECT id FROM grupos WHERE nome=?)", ("Turno Teste",))
        con.execute("DELETE FROM grupos WHERE nome=?", ("Turno Teste",))
        con.commit()
    finally:
        con.close()


def test_ajuste_sem_token_e_bloqueado():
    r = client.post("/api/pontos/ajuste", json={"colaborador": "X", "quando": "2026-10-14 12:00:00",
                                                "acao": "inclusao", "tipo_novo": "pausa", "motivo": "a"})
    assert r.status_code == 401


def test_inclusao_exige_motivo():
    _criar_colaborador()
    r = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": "2026-10-14 12:00:00",
                          "acao": "inclusao", "tipo_novo": "pausa", "motivo": "  "})
    assert r.status_code == 400


def test_inclusao_grava_batida_com_fonte_e_auditoria():
    _criar_colaborador()
    r = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": "2026-10-14 12:00:00",
                          "acao": "inclusao", "tipo_novo": "pausa",
                          "motivo": "esquecimento de batida confirmado pelo gestor"})
    assert r.status_code == 200
    body = r.json()
    assert body["ponto_id"] is not None and body["ajuste_id"] is not None
    con = conectar()
    try:
        row = con.execute("SELECT tipo, fonte, motivo, usuario_ajuste, nsr, hash FROM pontos WHERE id=?",
                          (body["ponto_id"],)).fetchone()
    finally:
        con.close()
    assert row[0] == "pausa" and row[1] == "A"
    assert "esquecimento" in (row[2] or "")
    assert row[4] >= 1 and len(row[5] or "") == 64   # NSR + hash da cadeia


def test_reclassificacao_nao_altera_batida_original():
    _criar_colaborador()
    r = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": "2026-10-14 18:00:00",
                          "acao": "inclusao", "tipo_novo": "entrada",
                          "motivo": "batida criada para o teste de auditoria"})
    pid = r.json()["ponto_id"]
    r2 = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                     json={"colaborador": "Maria Teste", "quando": "2026-10-14 18:00:00",
                           "acao": "reclassificacao", "ponto_id": pid, "tipo_novo": "termino",
                           "motivo": "batida avulsa vinculada ao turno da tarde"})
    assert r2.status_code == 200
    con = conectar()
    try:
        row = con.execute("SELECT tipo, nsr, hash FROM pontos WHERE id=?", (pid,)).fetchone()
    finally:
        con.close()
    assert row[0] == "entrada"   # original INTACTO — só a visão efetiva muda
    assert row[1] >= 1


def test_abono_falta_grava_somente_auditoria():
    _criar_colaborador()
    antes = client.get("/api/pontos?usuario=Maria Teste", headers={"X-Admin-Token": TOKEN}).json()["pontos"]
    r = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": "2026-10-13",
                          "acao": "abono_falta", "motivo": "atestado médico — Art. 473 CLT"})
    assert r.status_code == 200 and r.json()["ponto_id"] is None
    depois = client.get("/api/pontos?usuario=Maria Teste", headers={"X-Admin-Token": TOKEN}).json()["pontos"]
    assert len(depois) == len(antes)   # abono não cria nem remove batida


def test_abono_exige_motivo():
    _criar_colaborador()
    r = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": "2026-10-13",
                          "acao": "abono_falta", "motivo": ""})
    assert r.status_code == 400


def test_espelho_sem_token_e_bloqueado():
    r = client.get("/api/espelho?colaborador=Maria Teste")
    assert r.status_code == 401


def test_espelho_pareia_e_sinaliza_batida_impar():
    # Data própria do teste: em 2026-10-14 o teste de reclassificação já deixa um
    # 'termino' efetivo para Maria Teste e o slot não ficaria faltando.
    _criar_colaborador()
    for quando, tipo in [("2026-10-16 08:02:00", "entrada"), ("2026-10-16 12:01:00", "pausa"),
                         ("2026-10-16 13:00:00", "volta")]:
        client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": quando,
                          "acao": "inclusao", "tipo_novo": tipo,
                          "motivo": "carga de teste do espelho"})
    r = client.get("/api/espelho?colaborador=Maria Teste&de=2026-10-16&ate=2026-10-16",
                   headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    dia = r.json()["dias"][0]
    assert dia["pareamento"]["entrada"] == "2026-10-16 08:02:00"
    assert dia["pareamento"]["impares"] is True
    assert dia["pareamento"]["faltando"] == ["termino"]
    assert "batida_impar" in dia["flags"]
    assert dia["apuracao"]["status"] in ("DEFICIT", "AUSENTE", "NORMAL", "OVERTIME")


def test_vinculos_sem_token_e_bloqueado():
    assert client.get("/api/vinculos").status_code == 401


def test_vinculos_lista_pendencias_de_biometria_e_grupo():
    _limpar_vinculos_de_teste()
    _criar_colaborador()
    r = client.get("/api/vinculos", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    linha = next(v for v in r.json()["vinculos"] if v["nome"] == "Maria Teste")
    assert linha["biometria"] == "pendente"      # sem .npy em embeddings/
    assert "sem_grupo" in linha["pendencias"]
    assert "sem_biometria" in linha["pendencias"]


def test_vincular_grupo_e_bitrix_corrige_pendencias():
    _limpar_vinculos_de_teste()
    _criar_colaborador()
    g = client.post("/api/grupos", headers={"X-Admin-Token": TOKEN},
                    json={"nome": "Turno Teste", "entrada": "08:00", "saida": "17:00",
                          "dias": [0, 1, 2, 3, 4], "almoco_min": 60}).json()
    r = client.put("/api/colaborador/Maria Teste/vinculos", headers={"X-Admin-Token": TOKEN},
                   json={"grupo_id": g["id"], "bitrix_id": "4321"})
    assert r.status_code == 200
    linha = next(v for v in client.get("/api/vinculos", headers={"X-Admin-Token": TOKEN}).json()["vinculos"]
                 if v["nome"] == "Maria Teste")
    assert linha["grupo"] == "Turno Teste" and linha["bitrix_id"] == "4321"
    assert "sem_grupo" not in linha["pendencias"] and "sem_bitrix" not in linha["pendencias"]


def test_editar_grupo_atualiza_horario_dias_e_almoco():
    _limpar_vinculos_de_teste()
    g = client.post("/api/grupos", headers={"X-Admin-Token": TOKEN},
                    json={"nome": "Turno Teste", "entrada": "08:00", "saida": "17:00",
                          "dias": [0, 1, 2, 3, 4], "almoco_min": 60}).json()
    r = client.put(f"/api/grupos/{g['id']}", headers={"X-Admin-Token": TOKEN},
                   json={"nome": "Turno Teste", "entrada": "08:30", "saida": "18:00",
                         "dias": [0, 1, 2, 3, 4, 5], "almoco_min": 45})
    assert r.status_code == 200
    cfg = client.get("/api/configuracao", headers={"X-Admin-Token": TOKEN}).json()
    grupo = next(x for x in cfg["grupos"] if x["id"] == g["id"])
    assert grupo["entrada"] == "08:30" and grupo["saida"] == "18:00"
    assert grupo["almoco_min"] == 45 and grupo["dias"] == [0, 1, 2, 3, 4, 5]


# ---------- resumo do espelho (agregação: 1 chamada em vez de N) ----------

def _inserir_batidas(nome, batidas):
    """Inclui as batidas de teste via API, UMA vez por banco.

    O ponto.db persiste entre rodadas: reincluir duplicaria as batidas do mesmo
    dia e `parear_batidas` passaria a ver órfãs (dia completo viraria ímpar).
    """
    dia = batidas[0][0][:10]
    con = conectar()
    try:
        ja = con.execute("SELECT COUNT(*) FROM pontos WHERE colaborador=? "
                         "AND substr(quando,1,10)=?", (nome, dia)).fetchone()[0]
    finally:
        con.close()
    if ja:
        return
    for quando, tipo in batidas:
        r = client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                        json={"colaborador": nome, "quando": quando, "acao": "inclusao",
                              "tipo_novo": tipo, "motivo": "fixture do resumo do espelho"})
        assert r.status_code == 200


def _resumo(colaborador, dia):
    r = client.get(f"/api/espelho/resumo?de={dia}&ate={dia}",
                   headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    return next(c for c in r.json()["colaboradores"] if c["nome"] == colaborador)


def _ligar_a_grupo(nome, grupo_nome, dias):
    """Garante grupo/escala para o colaborador de teste (idempotente: sem grupo a rota
    não infere escala nenhuma, então o teste de falta precisa de vínculo de verdade)."""
    con = conectar()
    try:
        row = con.execute("SELECT id FROM grupos WHERE nome=?", (grupo_nome,)).fetchone()
    finally:
        con.close()
    gid = row[0] if row else client.post(
        "/api/grupos", headers={"X-Admin-Token": TOKEN},
        json={"nome": grupo_nome, "entrada": "08:00", "saida": "17:00",
              "dias": dias, "almoco_min": 60}).json()["id"]
    r = client.put(f"/api/colaborador/{nome}/vinculos", headers={"X-Admin-Token": TOKEN},
                   json={"grupo_id": gid})
    assert r.status_code == 200


def _assert_totais_somam(corpo):
    """Totais são exatamente a soma dos itens de `colaboradores`.

    Nada de número literal aqui: o banco traz colaboradores e `.npy` de produção/importação,
    então qualquer literal de `totais` depende do estado de disco do projeto. Os valores
    esperados ficam nos itens dos colaboradores de TESTE (os que os testes criam).
    """
    tot = corpo["totais"]
    assert tot["colaboradores"] == len(corpo["colaboradores"])
    for campo in ("dias_impares", "extra_50_min", "extra_100_min", "noturno_min",
                  "deficit_min", "sem_biometria"):
        assert tot[campo] == sum(c[campo] for c in corpo["colaboradores"])


def test_espelho_resumo_sem_token_e_bloqueado():
    r = client.get("/api/espelho/resumo?de=2026-09-01&ate=2026-09-30")
    assert r.status_code == 401


def test_espelho_resumo_dia_completo_nao_e_impar():
    nome, dia = "Resumo Completo Teste", "2026-09-15"
    _criar_colaborador(nome)
    batidas = [(f"{dia} 08:00:00", "entrada"), (f"{dia} 12:00:00", "pausa"),
               (f"{dia} 13:00:00", "volta"), (f"{dia} 17:00:00", "termino")]
    _inserir_batidas(nome, batidas)
    colab = _resumo(nome, dia)
    esperado = apurar_dia([(t, q) for q, t in batidas], 480, dia_util=True)
    assert colab["dias_com_batida"] == 1
    assert colab["dias_impares"] == 0
    assert colab["dias_incompletos"] == 0
    assert colab["extra_50_min"] == esperado["extra_50_min"]
    assert colab["extra_100_min"] == esperado["extra_100_min"]
    assert colab["noturno_min"] == esperado["noturno_min"]
    assert colab["deficit_min"] == esperado["deficit_min"]


def test_espelho_resumo_dia_impar_passado_conta():
    nome, dia = "Resumo Impar Teste", "2026-09-16"
    _criar_colaborador(nome)
    _inserir_batidas(nome, [(f"{dia} 08:00:00", "entrada"),
                            (f"{dia} 12:00:00", "pausa"),
                            (f"{dia} 13:00:00", "volta")])
    colab = _resumo(nome, dia)
    assert colab["dias_impares"] == 1
    assert colab["dias_incompletos"] == 1


def test_espelho_resumo_hoje_incompleto_nao_conta():
    nome = "Resumo Hoje Teste"
    dia = time.strftime("%Y-%m-%d")
    _criar_colaborador(nome)
    _inserir_batidas(nome, [(f"{dia} 08:00:00", "entrada"), (f"{dia} 12:00:00", "pausa"),
                            (f"{dia} 13:00:00", "volta")])
    r = client.get(f"/api/espelho/resumo?de={dia}&ate={dia}",
                   headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    corpo = r.json()
    colab = next(c for c in corpo["colaboradores"] if c["nome"] == nome)
    assert colab["dias_com_batida"] == 1
    assert colab["dias_impares"] == 0      # hoje NUNCA conta como ímpar
    assert colab["dias_incompletos"] == 0
    # dia em andamento não gera extra nem déficit (nem no colaborador, nem nos totais —
    # o período da consulta aqui é só hoje, então nada pode ser acumulado)
    assert colab["deficit_min"] == 0
    assert colab["extra_50_min"] == 0
    assert corpo["totais"]["deficit_min"] == 0
    assert corpo["totais"]["extra_50_min"] == 0


def test_espelho_resumo_dia_de_escala_sem_batida_conta_falta_e_deficit():
    # segunda-feira passada, DENTRO da escala do grupo (seg-sex) e sem nenhuma batida:
    # conta como dia incompleto e leva a jornada do grupo (08:00-17:00 menos 60 = 480 min)
    nome, dia = "Resumo Falta Teste", "2026-09-14"
    _criar_colaborador(nome)
    _ligar_a_grupo(nome, "Escala Falta Teste", [0, 1, 2, 3, 4])
    colab = _resumo(nome, dia)
    assert colab["dias_com_batida"] == 0
    assert colab["dias_impares"] == 0      # sem batida nenhuma não é "batida ímpar"
    assert colab["dias_incompletos"] == 1
    assert colab["deficit_min"] == 480


def test_espelho_resumo_sem_grupo_nao_inventa_falta_nem_deficit():
    # sem grupo não se infere escala: nenhum dia passado vira falta/déficit — nem em
    # semana cheia, nem no fim de semana (o defeito contava todo o período)
    nome = "Resumo Sem Grupo Teste"
    _criar_colaborador(nome)
    for de, ate in (("2026-10-05", "2026-10-11"), ("2026-09-12", "2026-09-13")):
        r = client.get(f"/api/espelho/resumo?de={de}&ate={ate}",
                       headers={"X-Admin-Token": TOKEN})
        assert r.status_code == 200
        corpo = r.json()
        assert next(c for c in corpo["colaboradores"] if c["nome"] == nome) == {
            "nome": nome, "grupo": None, "dias_com_batida": 0, "dias_impares": 0,
            "dias_incompletos": 0, "extra_50_min": 0, "extra_100_min": 0,
            "noturno_min": 0, "deficit_min": 0, "interjornadas_insuficientes": 0,
            "sem_biometria": True}
        _assert_totais_somam(corpo)


def test_espelho_resumo_totais_e_sem_biometria():
    # sábado (fora da escala seg-sex) = trabalho vira extra 100%
    nome, dia = "Resumo Totais Teste", "2026-09-19"
    _criar_colaborador(nome)
    _ligar_a_grupo(nome, "Escala Totais Teste", [0, 1, 2, 3, 4])
    _inserir_batidas(nome, [(f"{dia} 08:00:00", "entrada"), (f"{dia} 12:00:00", "pausa"),
                            (f"{dia} 13:00:00", "volta"), (f"{dia} 17:30:00", "termino")])
    r = client.get(f"/api/espelho/resumo?de={dia}&ate={dia}",
                   headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    corpo = r.json()
    assert corpo["de"] == dia and corpo["ate"] == dia
    assert corpo["grupo"] == "" and corpo["truncado"] is False
    # Sábado fora da escala: 08:00-12:00 + 13:00-17:30 = 510 min, todos como extra 100%
    assert next(c for c in corpo["colaboradores"] if c["nome"] == nome) == {
        "nome": nome, "grupo": "Escala Totais Teste", "dias_com_batida": 1,
        "dias_impares": 0, "dias_incompletos": 0, "extra_50_min": 0,
        "extra_100_min": 510, "noturno_min": 0, "deficit_min": 0,
        "interjornadas_insuficientes": 0, "sem_biometria": True}
    # totais: só o invariante (os literais vivem no item do colaborador de teste acima)
    _assert_totais_somam(corpo)
