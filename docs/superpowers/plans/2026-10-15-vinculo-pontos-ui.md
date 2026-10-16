# Vínculo de Pontos + Redesign UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar o fluxo de vínculo e tratamento de batidas (pareamento, ajuste auditável, espelho CLT, vínculos de integração) e redesenhar as 4 telas ao padrão comercial, sem quebrar nenhum teste existente.

**Architecture:** Camada de leitura efetiva em `logica.py` (batidas originais + ajustes auditáveis) alimenta novos endpoints em `app.py` (`/api/espelho`, `/api/pontos/ajuste`, `/api/vinculos`). Batidas originais são append-only em `pontos` (hash chain NSR inalterado); ajustes vivem em tabela `ajustes` + colunas `fonte/motivo/usuario_ajuste` em `pontos` só para inclusões. Frontend ganha um mini design system (`static/ui-kit.css`/`ui-kit.js`) e reorganização visual preservando 100% dos IDs DOM, funções JS e rotas.

**Tech Stack:** Python/FastAPI, SQLite/Postgres (via `db.py`), lógica pura testada com pytest, frontend HTML/CSS/JS vanilla (sem framework), fontes locais `static/fonts/` (Inter).

**Spec:** Briefing do usuário (missão Ponto Facial, frentes 1 e 2) — etapas: diagnóstico → backend+testes → HTML um a um.

## Diagnóstico (estado atual)

**Rotas existentes (21):** `POST /api/login`, `GET /api/configuracao`, CRUD grupos (`POST/DELETE /api/grupos`, `POST/DELETE/PUT /api/grupos/{gid}/membros[/{nome}]`), `POST /api/cadastrar`, `POST /api/auto-cadastro`, `DELETE /api/colaborador/{nome}`, `POST /api/reconhecer`, `GET /api/pontos`, `GET /api/metricas`, `GET /api/resumo`, `GET /api/colaboradores`, `GET /api/relatorio/{nome}`, `GET /api/afd`, `GET /api/aej`, `GET /api/health`.

**Modelo (`db.py`):** `colaboradores(nome UNIQUE, cpf, telefone)` · `pontos(colaborador, confianca, quando, tipo, lat, lng, nsr, hash)` · `usuarios` · `grupos(entrada, saida, dias JSON, almoco_min)` · `grupo_membros(grupo_id, colaborador, entrada, saida, almoco_min)` — vínculo de grupo é por STRING de nome, sem FK.

**O que já existe e funciona:** máquina de estados `proximo_tipo` (anti-fraude: tipo decidido no servidor), NSR + hash chain (`fiscal.hash_encadeado`), AFD/AEJ/comprovante (`fiscal.py`), apuração CLT completa (`clt.apurar_dia`, `fechamento_mensal`), métricas/relatório/calendário (`logica.py`), auth JWT + X-Admin-Token, rate limit, CSP.

**Lacunas que este plano fecha:**
1. `clt.py` é código órfão: nenhuma rota o consome — o espelho não mostra extra 50/100, noturno, almoço suprimido, teto.
2. Não existe ajuste de ponto: sem inserção de batida esquecida, sem reclassificação de batida avulsa, sem abono de falta, sem justificativa obrigatória, sem auditoria (quem/quando/por quê).
3. Sem detecção de batidas ímpares/órfãs: `metricas_usuario`/`apurar_dia` só pegam a 1ª ocorrência de cada tipo e ignoram o resto em silêncio.
4. Art. 66 (interjornada 11h) e teto semanal declarados em `RegrasClt` mas nunca calculados.
5. Vínculos de integração invisíveis: `bitrix_id` não existe no banco (importação casa por nome), biometria = existência de `embeddings/<nome>.npy` em disco (fora da API), não há endpoint nem UI para corrigir vínculos quebrados.
6. `GET /api/afd` e `GET /api/aej` não têm botão no dashboard (nenhum `fetch` os chama).

**Frontend atual:** `index.html` (20 IDs, 12 funções JS), `dashboard.html` (64 IDs, 44 funções JS), `cadastro.html` (6 IDs), `cadastro-publico.html` (8 IDs). 3 usos de `alert`/`confirm` nativos (1 em cadastro, 2 em dashboard). CSP fixa em testes: fontes SÓ podem ser locais (`static/fonts/` já traz Inter 400–800).

**Testes:** 10 arquivos em `testes/` — todos devem continuar passando. Asserts relevantes: sequência `proximo_tipo`, chaves de `metricas_usuario`/`relatorio_individual`, tamanhos de linha AFD (302/137/64), estrutura AEJ, auth 401 em rotas protegidas, CSP com `style-src 'self' 'unsafe-inline'`.

## Global Constraints

- Todos os testes em `testes/` continuam passando (rodar suíte completa ao fim de cada tarefa).
- REGRA DE OURO: `pontos` é append-only — nenhum ajuste faz `UPDATE` ou `DELETE` em batida original.
- Preservar TODO id DOM (`id="..."`), TODO nome de função JS `function x` e TODA rota de API já chamada pelos HTMLs.
- CSP (`app.py` `_seguranca_middleware`) não muda — testes fixam o header; fontes apenas locais (`static/fonts/`).
- SQL sempre com placeholder `?` (o `db.py` converte para Postgres); `criar_schema` só adiciona colunas/tabelas (nada destrutivo).
- Toda rota nova exige `_autentica(authorization, x_admin_token)` (padrão das rotas vizinhas), exceto leitura de saúde.
- Comentários existentes nos arquivos editados não são removidos nem encurtados.
- Projeto sem git (extract de zip): etapas de "commit" deste plano = rodar `pytest testes/` e confirmar verde antes de avançar.
- Ambiente macOS: rodar os testes com `.venv/bin/python -m pytest testes/ -q` — o `conftest.py` já cuida de `PONTO_ALLOW_SQLITE`, `PONTO_SQLITE_PATH` (precisa casar com `app.DB` = `BASE/ponto.db`), `PONTO_JWT_SECRET` e do bootstrap de schema+admin. NÃO passar `PONTO_SQLITE_PATH` na linha de comando (quebraria `test_hash_nao_e_texto_puro`).
- Nomes de tipos de batida permanecem `entrada`/`pausa`/`volta`/`termino` (testes dependem). Rótulos de UI são outros ("Início Intervalo" etc.) — só texto de exibição.

## Review Focus

1. **Ajuste sobrescrever batida original** — esperado: linha original intacta (mesmo `tipo`, `nsr`, `hash`) após reclassificação. Teste: Task 4 `test_reclassificacao_nao_altera_batida_original`.
2. **Ajuste sem justificativa passar** — esperado: 400 quando `motivo` vazio/ausente, em qualquer `acao`. Teste: Task 4 `test_inclusao_exige_motivo` + `test_abono_exige_motivo`.
3. **Quebra da cadeia NSR/hash em inclusão manual** — esperado: nova batida continua a cadeia (`hash_encadeado(hash_anterior, nsr, cpf, quando)`), NSR = MAX+1. Teste: Task 4 `test_inclusao_continua_cadeia_hash`.
4. **Pareamento errado com batidas extras** — esperado: 1ª ocorrência de cada tipo ocupa o slot; sobras entram em `extras` (órfãs) sem roubar slot; dia ímpar sinalizado. Teste: Task 2 trio de testes de pareamento.
5. **Vazamento de PII em novas rotas** — esperado: `/api/espelho`, `/api/vinculos`, `/api/pontos/ajuste` respondem 401 sem token (CPF/nome são PII). Teste: Task 5/6 `test_*_sem_token_bloqueado`.

---

### Task 1: Schema — tabela `ajustes` + colunas de vínculo (`db.py`)

**Files:**
- Modify: `db.py` (após bloco de migração `grupo_membros`, antes de `con.commit()` em `criar_schema`)
- Test: `testes/test_db.py` (adicionar 1 teste)

**Interfaces:**
- Produz: tabela `ajustes(id, ponto_id, colaborador, acao, tipo_novo, quando, motivo, usuario, criado_em)`; colunas novas `pontos.fonte` (TEXT DEFAULT 'O'), `pontos.motivo` (TEXT), `pontos.usuario_ajuste` (TEXT), `colaboradores.bitrix_id` (TEXT). Tasks 2–6 dependem desses nomes exatos.

- [ ] **Step 1: Escrever o teste que falha**

```python
# testes/test_db.py (acrescentar)
def test_schema_tem_ajustes_e_colunas_de_vinculo():
    from db import conectar, criar_schema
    con = conectar()
    try:
        criar_schema(con)
        cols_pontos = {r[1] for r in con.execute("PRAGMA table_info(pontos)").fetchall()} \
            if not con.pg else {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='pontos'").fetchall()}
        cols_colab = {r[1] for r in con.execute("PRAGMA table_info(colaboradores)").fetchall()} \
            if not con.pg else {r[0] for r in con.execute(
                "SELECT column_name FROM information_schema.columns WHERE table_name='colaboradores'").fetchall()}
        tabs = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'" if not con.pg
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'").fetchall()}
        assert {"fonte", "motivo", "usuario_ajuste"} <= cols_pontos
        assert "bitrix_id" in cols_colab
        assert "ajustes" in tabs
    finally:
        con.close()
```

- [ ] **Step 2: Rodar e confirmar falha**

Run: `.venv/bin/python -m pytest testes/test_db.py::test_schema_tem_ajustes_e_colunas_de_vinculo -v`
Expected: FAIL (coluna `fonte` não existe / tabela `ajustes` ausente)

- [ ] **Step 3: Implementar mínimo em `db.py`**

Dentro de `criar_schema`, logo após a migração de `almoco_min` e antes de `con.commit()`:

```python
    # migração: colunas de tratamento de ponto (ajuste auditável) e vínculo Bitrix.
    # Regra fiscal: batidas originais nunca são alteradas — inclusões entram como
    # novas linhas (fonte='A') com motivo; reclassificação/abono ficam em `ajustes`.
    if con.pg:
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS fonte TEXT NOT NULL DEFAULT 'O'")
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS motivo TEXT")
        con.execute("ALTER TABLE pontos ADD COLUMN IF NOT EXISTS usuario_ajuste TEXT")
        con.execute("ALTER TABLE colaboradores ADD COLUMN IF NOT EXISTS bitrix_id TEXT")
    else:
        for tab, col, typ in (("pontos", "fonte", "TEXT NOT NULL DEFAULT 'O'"),
                              ("pontos", "motivo", "TEXT"),
                              ("pontos", "usuario_ajuste", "TEXT"),
                              ("colaboradores", "bitrix_id", "TEXT")):
            try:
                con.execute(f"ALTER TABLE {tab} ADD COLUMN {col} {typ}")
            except Exception:
                pass   # coluna já existe
    con.execute(f"""CREATE TABLE IF NOT EXISTS ajustes (
        id {pk}, ponto_id INTEGER, colaborador TEXT NOT NULL, acao TEXT NOT NULL,
        tipo_novo TEXT, quando TEXT NOT NULL, motivo TEXT NOT NULL,
        usuario TEXT NOT NULL, criado_em TEXT NOT NULL)""")
```

- [ ] **Step 4: Rodar e confirmar passagem**

Run: mesmo comando do Step 2 → Expected: PASS. Depois `.venv/bin/python -m pytest testes/ -q` → todo verde (nada destrutivo).

### Task 2: Pareamento e visão efetiva (`logica.py`)

**Files:**
- Modify: `logica.py` (novas funções no fim do arquivo)
- Test: `testes/test_vinculo.py` (novo)

**Interfaces:**
- Produz:
  - `parear_batidas(rows: list) -> dict` com `{"entrada", "pausa", "volta", "termino", "extras": list, "faltando": list, "impares": bool, "registradas": int}`. `rows`: lista de `(tipo, quando)` de UM dia, qualquer ordem.
  - `aplicar_ajustes(pontos: list, ajustes: list) -> dict` com `{"efetivas": list, "abonos": dict}`. `pontos`: `(id, tipo, quando, fonte)`; `ajustes`: `(id, ponto_id, acao, tipo_novo, quando, motivo)`. `efetivas`: tuplas `(id, tipo_efetivo, quando, fonte, ajustado)`. `abonos`: `{data_iso: {"motivo", "usuario"?, "criado_em"?}}`.
- Consome: nada (funções puras). Tasks 4–5 consomem estas assinaturas.

- [ ] **Step 1: Testes que falham**

```python
# testes/test_vinculo.py (novo)
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
```

- [ ] **Step 2: Rodar → FAIL** (`ImportError: cannot import name 'parear_batidas'`)

Run: `.venv/bin/python -m pytest testes/test_vinculo.py -v`

- [ ] **Step 3: Implementar em `logica.py`**

```python
def parear_batidas(rows: list) -> dict:
    """Pareia as batidas de UM dia na sequência 1ª Entrada -> Início Intervalo ->
    Fim Intervalo -> Saída (mesma convenção de `metricas_usuario`: a 1ª ocorrência
    de cada tipo ocupa o slot). Sobras são órfãs/duplicadas — nunca descartadas.

    rows: lista de (tipo, quando), qualquer ordem. tipo em
          {entrada, pausa, volta, termino}.
    Retorna {entrada, pausa, volta, termino, extras, faltando, impares, registradas}.
    `impares` = quantidade ímpar de batidas (ciclo incompleto — esquecimento).
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
            "impares": len(rows) % 2 == 1, "registradas": len(rows)}


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
```

- [ ] **Step 4: Rodar → PASS** (mesmo comando do Step 2) e suíte completa verde.

### Task 3: Interjornada (Art. 66) e teto semanal (`clt.py`)

**Files:**
- Modify: `clt.py` (nova função pura `interjornada_min` + trecho final de `fechamento_mensal`)
- Test: `testes/test_clt.py` (acrescentar 3 testes)

**Interfaces:**
- Produz:
  - `interjornada_min(fim_anterior: str, inicio_atual: str) -> int` — minutos entre as duas marcações (`'YYYY-MM-DD HH:MM:SS'`). Fonte única da aritmética do Art. 66: usada aqui e pelo espelho (Task 5).
  - Chaves ADICIONAIS em cada item de `dias` de `fechamento_mensal` — `interjornada_min` (int|None) e `interjornada_insuficiente` (bool) — e em `totais` — `interjornadas_insuficientes` (int) e `teto_semanal_excedido` (bool). Chaves existentes e seus valores não mudam.

- [ ] **Step 1: Testes que falham**

```python
# testes/test_clt.py (acrescentar)
def test_interjornada_insuficiente_e_sinalizada():
    batidas = [
        ("entrada", "2026-10-12 08:00:00"), ("pausa", "2026-10-12 12:00:00"),
        ("volta", "2026-10-12 13:00:00"), ("termino", "2026-10-12 22:00:00"),
        ("entrada", "2026-10-13 08:00:00"), ("pausa", "2026-10-13 12:00:00"),
        ("volta", "2026-10-13 13:00:00"), ("termino", "2026-10-13 17:00:00"),
    ]
    r = fechamento_mensal(batidas, 480, [0, 1, 2, 3, 4], "2026-10")
    dia13 = next(d for d in r["dias"] if d["data"] == "2026-10-13")
    assert dia13["interjornada_min"] == 10 * 60
    assert dia13["interjornada_insuficiente"] is True
    assert r["totais"]["interjornadas_insuficientes"] == 1


def test_teto_semanal_excedido_e_sinalizado():
    # 6 dias com 2h extra cada = 720min na semana > teto de 600min (Art. 59).
    batidas = []
    for dia in ("12", "13", "14", "15", "16", "17"):
        batidas += [("entrada", f"2026-10-{dia} 08:00:00"), ("pausa", f"2026-10-{dia} 12:00:00"),
                    ("volta", f"2026-10-{dia} 13:00:00"), ("termino", f"2026-10-{dia} 19:00:00")]
    r = fechamento_mensal(batidas, 480, [0, 1, 2, 3, 4, 5], "2026-10")
    assert r["totais"]["teto_semanal_excedido"] is True   # 6 * 120min = 720min > 600min
```

- [ ] **Step 2: Rodar → FAIL** (`KeyError: 'interjornada_min'`)

Run: `.venv/bin/python -m pytest testes/test_clt.py -v`

- [ ] **Step 3: Implementar em `clt.py`**

Função pura nova (perto de `minutos_noturnos`):

```python
def interjornada_min(fim_anterior: str, inicio_atual: str) -> int:
    """Descanso interjornada em minutos (Art. 66: mínimo 11h entre jornadas)."""
    return round((_dt(inicio_atual) - _dt(fim_anterior)).total_seconds() / 60)
```

Dentro de `fechamento_mensal`, após montar a lista `dias` (mantendo o loop atual intacto), acrescentar:

```python
    # Art. 66 CLT — descanso interjornada: sinaliza quando < 11h entre o fim de uma
    # jornada (última 'termino') e o início da seguinte (1ª 'entrada').
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
```

(Locais de `fim_ant`/`ini_atual` são as batidas `termino`/`entrada` do próprio `por_dia` que a função já monta. `date` já está importado em `clt.py`.)

- [ ] **Step 4: Rodar → PASS** — `testes/test_clt.py` todo verde (inclusive os antigos de `fechamento_mensal_totaliza`), depois suíte completa.

### Task 4: Endpoint de ajuste auditável (`app.py`)

**Files:**
- Modify: `app.py` (novas rotas após `POST /api/reconhecer`; extrair helper `_proximo_nsr_hash` do bloco de hash do `reconhecer` e reaproveitar)
- Test: `testes/test_vinculo_api.py` (novo)

**Interfaces:**
- Consome: schema da Task 1; `logica.validar_nome` (nome do colaborador).
- Produz:
  - `POST /api/pontos/ajuste` — body `{colaborador, quando, acao, tipo_novo?, ponto_id?, motivo, usuario?}` com `acao ∈ {inclusao, reclassificacao, abono_falta}` → `{ok, ajuste_id, ponto_id}`. Motivo obrigatório (400 se vazio). 404 se colaborador não existe; 404 se `reclassificacao` sem `ponto_id` válido.
  - `GET /api/pontos/ajustes?colaborador=&de=&ate=` → `{"ajustes": [{id, ponto_id, colaborador, acao, tipo_novo, quando, motivo, usuario, criado_em}]}` (mais recente primeiro).
  - `func _proximo_nsr_hash(con, cpf, quando) -> tuple[int, str]` — NSR = MAX+1 e hash encadeado (extraído do `reconhecer` para não duplicar a cadeia).

- [ ] **Step 1: Testes que falham**

```python
# testes/test_vinculo_api.py (novo)
import os
import sys

os.environ.setdefault("PONTO_ADMIN_TOKEN", "token-de-teste")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app import app  # noqa: E402
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
```

- [ ] **Step 2: Rodar → FAIL** (404 em `/api/pontos/ajuste`)

Run: `.venv/bin/python -m pytest testes/test_vinculo_api.py -v`

- [ ] **Step 3: Implementar em `app.py`**

(a) Extrair do `reconhecer` o bloco NSR+hash para helper (mantendo o comportamento idêntico):

```python
def _proximo_nsr_hash(con: DB, cpf: str, quando: str) -> tuple:
    """Próximo NSR global e hash encadeado da marcação (inviolabilidade do AFD)."""
    ult = con.execute("SELECT COALESCE(MAX(nsr), 0) FROM pontos").fetchone()
    nsr = int(ult[0] or 0) + 1
    ult_hash = con.execute(
        "SELECT hash FROM pontos WHERE id = (SELECT MAX(id) FROM pontos)").fetchone()
    hash_ant = (ult_hash[0] if ult_hash and ult_hash[0] else "") or "0" * 64
    return nsr, hash_encadeado(hash_ant, nsr, cpf or "0", quando)
```

No `reconhecer`, substituir o bloco equivalente por `nsr, hashcode = _proximo_nsr_hash(con, cpf or "0", agora)` (semântica idêntica: NSR = MAX+1 sobre a cadeia do último id).

(b) Novos modelos e rotas (após `reconhecer`):

```python
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
            nsr, hashcode = _proximo_nsr_hash(con, cpf, payload.quando)
            cur = con.execute(
                "INSERT INTO pontos (colaborador, confianca, quando, tipo, lat, lng, nsr, hash, "
                "fonte, motivo, usuario_ajuste) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (nome, None, payload.quando, tipo_novo, None, None, nsr, hashcode,
                 "A", motivo, usuario))
            ponto_id = cur.lastrowid if hasattr(cur, "lastrowid") else con.execute(
                "SELECT MAX(id) FROM pontos").fetchone()[0]
        elif payload.acao == "reclassificacao":
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
```

Observação Postgres: `cur.lastrowid` não existe no psycopg2 — por isso o fallback `SELECT MAX(id)`. No SQLite `lastrowid` funciona. Manter ambos.

- [ ] **Step 4: Rodar → PASS** na Task e suíte completa verde.

### Task 5: Espelho de ponto com pareamento + CLT (`app.py`)

**Files:**
- Modify: `app.py` (nova rota após `/api/pontos/ajustes`)
- Test: `testes/test_vinculo_api.py` (acrescentar)

**Interfaces:**
- Consome: `logica.parear_batidas`, `logica.aplicar_ajustes` (Task 2), `clt.apurar_dia` e `clt.interjornada_min` (Task 3), lookup de jornada já usado em `/api/relatorio` (grupo_membros JOIN grupos → `jornada_efetiva_seg`). Imports novos em `app.py`: acrescentar `parear_batidas, aplicar_ajustes` ao import de `logica`, criar `from clt import apurar_dia, interjornada_min` e `from datetime import date`.
- Produz: `GET /api/espelho?colaborador=&de=&ate=` →
  `{"colaborador", "de", "ate", "dias": [{"data", "batidas_originais": [{"id","tipo","quando","fonte","nsr","hash"}], "batidas_efetivas": [{"id","tipo","quando","ajustado"}], "pareamento": {entrada, pausa, volta, termino, extras, faltando, impares, registradas}, "apuracao": {...clt.apurar_dia...}, "abono": dict|null, "flags": [...], "atraso_min": int|null, "interjornada_min"?}], "totais": {"dias", "trabalhado_min", "regular_min", "extra_50_min", "extra_100_min", "noturno_min", "deficit_min", "banco_min", "interjornadas_insuficientes", "teto_semanal_excedido"}}`.
  Flags por dia: `"batida_impar"` (impares), `"orfa"` (extras não vazio), `"almoco_suprimido"` (almoco_suprimido_min > 0), `"interjornada_insuficiente"`, `"teto_excedido"` (teto_excedido do dia).

- [ ] **Step 1: Testes que falham**

```python
# testes/test_vinculo_api.py (acrescentar)
def test_espelho_sem_token_e_bloqueado():
    r = client.get("/api/espelho?colaborador=Maria Teste")
    assert r.status_code == 401


def test_espelho_pareia_e_sinaliza_batida_impar():
    _criar_colaborador()
    for quando, tipo in [("2026-10-14 08:02:00", "entrada"), ("2026-10-14 12:01:00", "pausa"),
                         ("2026-10-14 13:00:00", "volta")]:
        client.post("/api/pontos/ajuste", headers={"X-Admin-Token": TOKEN},
                    json={"colaborador": "Maria Teste", "quando": quando,
                          "acao": "inclusao", "tipo_novo": tipo,
                          "motivo": "carga de teste do espelho"})
    r = client.get("/api/espelho?colaborador=Maria Teste&de=2026-10-14&ate=2026-10-14",
                   headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    dia = r.json()["dias"][0]
    assert dia["pareamento"]["entrada"] == "2026-10-14 08:02:00"
    assert dia["pareamento"]["impares"] is True
    assert dia["pareamento"]["faltando"] == ["termino"]
    assert "batida_impar" in dia["flags"]
    assert dia["apuracao"]["status"] in ("DEFICIT", "AUSENTE", "NORMAL", "OVERTIME")
```

- [ ] **Step 2: Rodar → FAIL** (404 em `/api/espelho`)

- [ ] **Step 3: Implementar em `app.py`**

```python
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
```

- [ ] **Step 4: Rodar → PASS** + suíte completa.

### Task 6: Vínculos de integração (Bitrix/biometria/grupo) (`app.py`)

**Files:**
- Modify: `app.py` (rotas novas perto de `/api/colaboradores`)
- Test: `testes/test_vinculo_api.py` (acrescentar)

**Interfaces:**
- Produz:
  - `GET /api/vinculos` → `{"vinculos": [{"nome", "cpf", "telefone", "bitrix_id", "biometria": "ativa"|"pendente", "grupo_id", "grupo", "pendencias": [...]}]}`. `biometria` = "ativa" se `EMB_DIR / f"{nome}.npy"` existe. `pendencias` ⊆ `{"sem_biometria", "sem_grupo", "sem_cpf", "sem_bitrix"}`.
  - `PUT /api/colaborador/{nome}/vinculos` — body `{grupo_id?: int|null, bitrix_id?: str|null}` → `{"ok": true, "nome", "grupo_id", "bitrix_id"}`. `grupo_id` válido = grupo existente (404 caso contrário); `null` remove o vínculo (DELETE em `grupo_membros`).

- [ ] **Step 1: Testes que falham**

```python
# testes/test_vinculo_api.py (acrescentar)
def test_vinculos_sem_token_e_bloqueado():
    assert client.get("/api/vinculos").status_code == 401


def test_vinculos_lista_pendencias_de_biometria_e_grupo():
    _criar_colaborador()
    r = client.get("/api/vinculos", headers={"X-Admin-Token": TOKEN})
    assert r.status_code == 200
    linha = next(v for v in r.json()["vinculos"] if v["nome"] == "Maria Teste")
    assert linha["biometria"] == "pendente"      # sem .npy em embeddings/
    assert "sem_grupo" in linha["pendencias"]
    assert "sem_biometria" in linha["pendencias"]


def test_vincular_grupo_e_bitrix_corrige_pendencias():
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
```

- [ ] **Step 2: Rodar → FAIL** (404)

- [ ] **Step 3: Implementar em `app.py`**

```python
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
                    "biometria": biometria, "grupo_id": gid, "grupo": gnom, "pendencias": pend})
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
```

- [ ] **Step 4: Rodar → PASS** na Task e `pytest testes/ -q` completo verde. **Gate da Etapa 2.**

### Task 7: UI Kit compartilhado (`static/ui-kit.css`, `static/ui-kit.js`)

**Files:**
- Create: `static/ui-kit.css`, `static/ui-kit.js`
- Modify: nenhum HTML ainda (Task 8–10 linkam)

**Interfaces:**
- Produz (globals em `window`): `toast(msg: string, tipo?: "ok"|"erro"|"aviso") -> void`, `confirmarAcao({titulo, texto, confirmar, cancelar}) -> Promise<boolean>`, e CSS vars + classes base. Tasks 8–10 consomem estes nomes exatos.
- Regras: CSP não muda — fontes via `@font-face` local (`/fonts/latin-{400,500,600,700,800}-normal.woff2`, família `Inter`). Sem CDN.

- [ ] **Step 1: Escrever `ui-kit.css` com tokens exatos**

Tokens (`:root`): `--font: "Inter", ui-sans-serif, system-ui, sans-serif`; cores Slate/Zinc + Indigo — `--bg:#F8FAFC; --surface:#FFFFFF; --border:#E2E8F0; --text:#0F172A; --muted:#64748B; --primary:#4F46E5; --primary-hover:#4338CA; --ok:#059669; --aviso:#D97706; --perigo:#E11D48; --ok-bg:#ECFDF5; --aviso-bg:#FFFBEB; --perigo-bg:#FFF1F2`; `--radius:10px; --shadow:0 1px 3px rgba(15,23,42,.08), 0 1px 2px rgba(15,23,42,.04); --shadow-lg:0 16px 40px rgba(15,23,42,.16)`. Classes: `.toast` (fixo topo-direito, slide-in, variantes `.toast.ok|.aviso|.erro`), `.modal-overlay` + `.modal` (centro, `--shadow-lg`), `.btn`, `.btn-primary`, `.btn-ghost`, `.btn-perigo`, `.badge`, `.badge.ok|.aviso|.perigo`, `.drawer` (painel lateral direito 420px, `transform: translateX(100%)` → `.drawer.aberto`), `.stepper` + `.stepper .passo.ativo`, `.kpi-card`, `.tabela-espelho`. Dark mode do kiosk: classe `.tema-totem` redefinindo `--bg:#0B1220; --surface:#111C2E; --border:#1E293B; --text:#F1F5F9; --muted:#94A3B8; --primary:#818CF8`. `@font-face` para os 5 woff2 (pesos 400/500/600/700/800, `font-display: swap`, `src: url("/fonts/latin-XXX-normal.woff2")`). `font-variant-numeric: tabular-nums` em relógio/horas. Foco visível: `:focus-visible { outline: 2px solid var(--primary); outline-offset: 2px }` (a11y). Breakpoints: `@media (max-width: 900px)` colapsa sidebar/KPIs em coluna única.

- [ ] **Step 2: Escrever `ui-kit.js` (vanilla, ~60 linhas)**

```javascript
// ui-kit.js — toasts e confirmações do Ponto Digital (substitui alert/confirm nativos).
function toast(msg, tipo = "ok") {
  let caixa = document.getElementById("ui-toasts");
  if (!caixa) {
    caixa = document.createElement("div");
    caixa.id = "ui-toasts";
    document.body.appendChild(caixa);
  }
  const el = document.createElement("div");
  el.className = "toast " + tipo;
  el.textContent = msg;
  caixa.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

function confirmarAcao({ titulo = "Confirmar", texto = "", confirmar = "Confirmar", cancelar = "Cancelar" } = {}) {
  return new Promise((resolve) => {
    const overlay = document.createElement("div");
    overlay.className = "modal-overlay";
    overlay.innerHTML =
      '<div class="modal" role="dialog" aria-modal="true" aria-label="' + titulo.replace(/"/g, "&quot;") + '">' +
      '<h3></h3><p></p><div class="modal-acoes"></div></div>';
    overlay.querySelector("h3").textContent = titulo;
    overlay.querySelector("p").textContent = texto;
    const acoes = overlay.querySelector(".modal-acoes");
    const btnNao = document.createElement("button");
    btnNao.className = "btn btn-ghost";
    btnNao.textContent = cancelar;
    const btnSim = document.createElement("button");
    btnSim.className = "btn btn-primary";
    btnSim.textContent = confirmar;
    const fechar = (v) => { overlay.remove(); resolve(v); };
    btnNao.addEventListener("click", () => fechar(false));
    btnSim.addEventListener("click", () => fechar(true));
    acoes.append(btnNao, btnSim);
    document.body.appendChild(overlay);
    btnSim.focus();
  });
}
```

- [ ] **Step 3: Verificação** — sem HTML linkado ainda; abrir via `python -m http.server` só nas Tasks 8–10. Gate de revisão: CSS/JS sem dependência externa (nenhuma URL `http`), IDs novos só `ui-toasts` (criado em runtime).

### Task 8: `index.html` — totem/kiosk de batida facial

**Files:**
- Modify: `static/index.html`
- Consome: `ui-kit.css`/`ui-kit.js` (Task 7). NÃO remove nada da superfície existente.

**Preservação obrigatória (verificação mecânica):**
```bash
cd static && grep -o 'id="[^"]*"' index.html | sort > /tmp/ids-index-antes.txt
grep -o 'function [a-zA-Z0-9_]*' index.html | sort > /tmp/fn-index-antes.txt
# após o redesign: diff (adicionar linhas é permitido; remover NÃO)
grep -o 'id="[^"]*"' index.html | sort | diff /tmp/ids-index-antes.txt -
grep -o 'function [a-zA-Z0-9_]*' index.html | sort | diff /tmp/fn-index-antes.txt -
```
Superfície atual: 20 IDs, 12 funções (`avaliar`, `baterPonto`, `capturarLocal`, `escolherFoto`, `initCam`, `initFace`, `loop`, `mostrarAviso`, `mostrarResultado`, `renderTipo`, `tick`, +1). Todas continuam.

**Mudanças (uma por uma, dentro dos `<style>`/`<script>` existentes + link do ui-kit):**
1. `<link rel="stylesheet" href="/ui-kit.css">` + `<script src="/ui-kit.js">` (ajustar path relativo como os demais assets). `<body>` ganha classe `tema-totem`. Tipografia Inter via ui-kit.
2. Relógio digital grande (função `tick` existente): formato `HH:MM:SS` com `tabular-nums`, data por extenso abaixo. Ampliar o elemento do relógio (mesmo id).
3. Moldura oval de scanner sobre o `<video>`: container com `border-radius: 50%`/elipse, borda animada (pulse `--primary`), sombreamento externo (`box-shadow: 0 0 0 9999px rgba(2,6,23,.55)`), canto do status de liveness ao lado (badge verde "Liveness OK" / âmbar "Validando…" / rose "Não validado").
4. Indicador online/servidor: poll `fetch('/api/health')` a cada 30s → badge `online`/`offline` no topo (novo elemento, id novo permitido).
5. Card de confirmação de batida (`mostrarResultado`): nome, avatar/iniciais, tipo vinculado ("Entrada registrada às 08:02", rótulos novos: Entrada / Início Intervalo / Fim Intervalo / Saída — via `renderTipo`), NSR + botão "Ver comprovante" que expande o JSON/hash do comprovante já devolvido por `/api/reconhecer`.
6. Substituir qualquer `alert`/`erro` inline por `toast(msg, 'erro'|'ok')` dentro de `mostrarAviso`/`mostrarResultado` (semântica igual).

**Critérios:** tela cheia sem scroll horizontal; relógio atualiza 1s; video com overlay oval; cada uma das 12 funções ainda existe e é chamada pelos mesmos handlers; diff de IDs só com adições.

### Task 9: `cadastro.html` + `cadastro-publico.html` — onboarding biométrico

**Files:**
- Modify: `static/cadastro.html`, `static/cadastro-publico.html`
- Consome: `ui-kit.css`/`ui-kit.js`.

**Preservação:** mesmos comandos de diff para os dois arquivos (6 e 8 IDs; funções JS existentes). O `alert`/`confirm` atual de `cadastro.html` (1 uso) vira `confirmarAcao(...).then(ok => { if (ok) ... })` mantendo o fluxo.

**Mudanças (iguais nos 2; `cadastro-publico.html` mantém `POST /api/auto-cadastro` e o `cadastro.html` mantém `POST /api/cadastrar`):**
1. Layout em card central + Stepper visual (`<div class="stepper">` novo) com 4 passos: `1 Dados` → `2 Foto` → `3 Grupo` → `4 Termo`. Os campos atuais ficam em `<section>`s mostradas/ocultas por classe `.passo.ativo` — ids e handlers dos inputs intactos; os botões existentes viram "Avançar"/"Voltar" chamando a mesma lógica de submit no último passo.
2. Passo Foto: preview da captura com feedback de qualidade reutilizando a lógica de `avaliar_qualidade_rosto` (mesma regra: `DET_MIN 0.5`, `POSE_MAX 30°`) já embutida no cliente do kiosk — copiar a função para cá com o mesmo nome (`avaliarQualidade` já não existe aqui; acrescentar `avaliar` como no index se necessário — nome livre novo permitido), mostrando badge verde/âmbar sobre o preview.
3. Passo Grupo: `fetch('/api/configuracao')` (rota existente) → select de grupos (`select` novo, id novo permitido) que envia `grupo_id` no submit; no `cadastro-publico.html` sem token o envio continua `/api/auto-cadastro` — o vínculo de grupo é feito depois pelo gestor em `/api/colaborador/{nome}/vinculos` (mostrar aviso no passo).
4. Passo Termo: checkbox de aceite do termo LGPD (`compliance/aviso-privacidade.md`) com resumo em 3 linhas (finalidade: registro de ponto via biometria; base: execução de contrato/obrigação legal; direitos: acesso/eliminação via RH) + link para o texto completo. Submit bloqueado sem aceite (mensagem via `toast`).
5. Rebrand (cores/tipografia do ui-kit, `.btn-primary`, `.badge` de qualidade).

**Critérios:** cada arquivo mantém sua rota de submit; diff de IDs só com adições; todos os `alert/confirm` nativos eliminados; stepper navega sem perder valores digitados (campos permanecem no DOM).

### Task 10: `dashboard.html` — painel gestor, espelho e vínculos

**Files:**
- Modify: `static/dashboard.html`
- Consome: `ui-kit.css`/`ui-kit.js`; rotas novas Tasks 4–6 (`/api/espelho`, `/api/pontos/ajuste`, `/api/vinculos`, `/api/pontos/ajustes`).

**Preservação:** snapshot de 64 IDs e 44 funções (`abrirExtrato` … `trocarAba`) — diff só com adições. Os 2 `alert`/`confirm` nativos viram `confirmarAcao`/`toast`. Todas as rotas atuais continuam sendo chamadas.

**Mudanças (em ordem):**
1. Shell: Sidebar colapsável (novo `<aside>` + botão toggle, id novo) com a navegação por abas existente (`trocarAba` mantido); Header com filtros globais (Período `de/ate`, Grupo/Departamento, Status do Ponto) — selects novos alimentados por `/api/configuracao` e `/api/vinculos`, que re-disparam `carregarGeral`/`carregarHistorico` com query params já suportados (`/api/pontos?de=&ate=`).
2. KPIs no topo (`.kpi-card`, função `kpiCard` existente reutilizada): **Presentes Hoje** (`/api/metricas` → `presentes`), **Batidas Ímpares Pendentes** (somatório de dias com flag `batida_impar` via `/api/espelho` de cada colaborador do filtro), **Horas Extras Acumuladas** (`/api/resumo` → `banco_seg` positivo, ou `totais.extra_50_min+extra_100_min` do espelho), **Sem Biometria** (`/api/vinculos` → contagem `pendencias` contém `sem_biometria`).
3. Tabela de Espelho e Vínculo (aba nova ou seção de `carregarHistorico`): por colaborador/dia — linha com slots pareados `[Entrada 08:02 → Início Intervalo 12:01 → Fim Intervalo 13:00 → Saída 17:10]` (rótulos de display; dados de `/api/espelho`), badges `.badge.ok` (regular), `.badge.aviso` (tolerância/almoço suprimido/pendente), `.badge.perigo` (batida ímpar/órfã/falta), extras 50/100 e noturno em colunas. Botão por linha **"Ajustar / Vincular Ponto"** → `.drawer` lateral (id novo) com form: ação (inclusão/reclassificação/abono), tipo (select), data-hora, **justificativa obrigatória**, submit `POST /api/pontos/ajuste` + feedback `toast` + refresh.
4. Painel Vínculos (aba nova, `carregarColaboradores` estendida): tabela de `/api/vinculos` — colunas Nome, Bitrix ID, Biometria (badge ativa/pendente), Grupo, Pendências; ações inline: corrigir grupo (select → `PUT /api/colaborador/{nome}/vinculos`), editar Bitrix id (input → mesmo PUT), link "Capturar biometria" abrindo `cadastro.html`. Correções sem terminal.
5. Botões de exportação fiscal: **AFD** e **AEJ** (rotas `/api/afd`, `/api/aej` já existem e hoje não têm UI) — baixam o conteúdo retornado como arquivo `.txt`/`.aej` (criar Blob a partir do JSON). Drawer de ajuste mostra histórico `/api/pontos/ajustes?colaborador=` (auditoria: quem/quando/motivo).
6. Rebrand completo: Inter, paleta Slate/Indigo, badges semânticos, tabelas com zebra `#F8FAFC`, hover `--primary-bg`, números com `tabular-nums`, responsivo (`@media 900px` → sidebar vira overlay). Substituir TODO `alert`/`confirm` nativo.

**Critérios:** os 15 `fetch` atuais continuam; as 44 funções continuam e são chamadas; diff de IDs só adições; espelho mostra pareamento e órfãs; ajuste exige justificativa e aparece na auditoria; KPIs calculam dos endpoints novos sem virar de função `kpi`/`kpiCard` existentes.

---

## Ordem de execução e gates

1. **Etapa 2 (backend):** Tasks 1→6. Gate: `pytest testes/` completo verde (incluindo os novos `test_vinculo.py`/`test_vinculo_api.py`).
2. **Etapa 3 (frontend):** Task 7 → 8 → 9 → 10 (index primeiro, cadastros, dashboard por último, como pedido).
3. Após cada HTML: rodar os comandos de diff de IDs/funções e abrir a página localmente para verificação visual.

## Riscos e limitações assumidos

- **Virada de plantão:** o agrupamento de dia continua calendar-day (`q[:10]`) — testes atuais fixam esse comportamento. Plantão 22h–06h aparece em dois dias no espelho; o adicional noturno (Art. 73) já é calculado corretamente. Melhorar exigiria um conceito de "dia de trabalho" e quebraria testes — ficou de fora por decisão.
- **Credenciais em `importar_bitrix.py`:** o arquivo traz URL do Postgres e webhook do Bitrix hardcoded — ROTACIONAR as credenciais e mover para `PONTO_DATABASE_URL`/env antes de qualquer deploy deste código. Fora do escopo de código deste plano, mas urgente.
- `lastrowid` no Postgres: usar o fallback `SELECT MAX(id)` implementado (concorrência baixa — fluxo de RH).
