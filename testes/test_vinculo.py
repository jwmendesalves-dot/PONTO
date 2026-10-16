from logica import aplicar_ajustes, parear_batidas


def test_parear_dia_completo_sem_orfas():
    rows = [("entrada", "2026-10-14 08:00:00"), ("pausa", "2026-10-14 12:00:00"),
            ("volta", "2026-10-14 13:00:00"), ("termino", "2026-10-14 17:00:00")]
    r = parear_batidas(rows)
    assert r["entrada"] == "2026-10-14 08:00:00"
    assert r["pausa"] == "2026-10-14 12:00:00"
    assert r["volta"] == "2026-10-14 13:00:00"
    assert r["termino"] == "2026-10-14 17:00:00"
    assert r["extras"] == [] and r["faltando"] == []
    assert r["impares"] is False and r["registradas"] == 4


def test_parear_batida_impar_sinaliza_esquecimento():
    rows = [("entrada", "2026-10-14 08:00:00"), ("pausa", "2026-10-14 12:00:00"),
            ("volta", "2026-10-14 13:00:00")]
    r = parear_batidas(rows)
    assert r["impares"] is True
    assert r["faltando"] == ["termino"]
    assert r["entrada"] == "2026-10-14 08:00:00"


def test_parear_duplicada_nao_rouba_slot_e_vira_extra():
    rows = [("entrada", "2026-10-14 08:00:00"), ("entrada", "2026-10-14 08:05:00")]
    r = parear_batidas(rows)
    assert r["entrada"] == "2026-10-14 08:00:00"          # 1ª ocorrência ocupa o slot
    assert r["extras"] == [("entrada", "2026-10-14 08:05:00")]   # órfã preservada
    assert r["impares"] is True


def test_aplicar_reclassificacao_sobrepoe_visao_efetiva():
    pontos = [(1, "entrada", "2026-10-14 12:30:00", "O")]
    ajustes = [(10, 1, "reclassificacao", "pausa", "2026-10-14 12:30:00",
                "batida de almoço lançada errada")]
    r = aplicar_ajustes(pontos, ajustes)
    assert r["efetivas"] == [(1, "pausa", "2026-10-14 12:30:00", "O", True)]
    assert pontos[0][1] == "entrada"   # tupla original preservada


def test_aplicar_abono_de_falta_fica_por_data():
    ajustes = [(11, None, "abono_falta", None, "2026-10-13", "atestado médico anexado ao RH")]
    r = aplicar_ajustes([], ajustes)
    assert r["abonos"]["2026-10-13"]["motivo"] == "atestado médico anexado ao RH"


def test_aplicar_inclusao_aparece_como_ajustada():
    pontos = [(7, "termino", "2026-10-14 17:00:00", "A")]
    r = aplicar_ajustes(pontos, [(12, None, "inclusao", "termino", "2026-10-14 17:00:00", "esquecimento")])
    assert r["efetivas"] == [(7, "termino", "2026-10-14 17:00:00", "A", True)]
