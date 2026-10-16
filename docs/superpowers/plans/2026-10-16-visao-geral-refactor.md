# Refatoração Visão Geral — Plano de Execução

**Goal:** corrigir os 8 defeitos encontrados na análise da Visão Geral (dashboard.html), movendo o cálculo pesado para o backend e consertando layout/lógica da UI.

**Stack:** FastAPI + SQLite/Postgres (`db.py`), lógica pura em `logica.py`/`clt.py`, frontend vanilla (`static/dashboard.html` + `static/ui-kit.css`).

**Base:** análise desta sessão (8 achados ranqueados). Projeto SEM git — BASE de cada task é uma cópia dos arquivos em `.superpowers/sdd/base/`, e o "diff" de review é `diff -u`.

## Global Constraints

- `pontos` é append-only: NUNCA `UPDATE`/`DELETE` em linhas de pontos.
- Suíte `testes/` verde ao fim de cada task: `.venv/bin/python -m pytest testes/ -q` (hoje 125 passed).
- Tema CLARO (Slate/Indigo do `ui-kit`). Nada de dark mode, nada de Tailwind/React/CDN.
- Preservar ids DOM e nomes de funções JS; remoções só as justificadas explicitamente neste plano, com referências JS limpas.
- Não remover/encurtar comentários existentes. Edições em pedaços pequenos (histórico de agentes mortos em reescritas grandes).
- Sem git: não commitar.

## Review Focus

1. **Hoje nunca é marcado como ímpar/falta** — dia corrente sem saída não pode contar em `dias_impares` nem pintar card vermelho.
2. **Inspetor do dia visível ao clicar na barra** — clicar num dia mostra os colaboradores e horários daquele dia.
3. **Sem N+1** — KPIs de período fazem UMA chamada de agregação, não uma por colaborador.
4. **Sem overflow horizontal em 400px** — gráfico (col-5) e inspetor (col-7) empilham em 1 coluna.
5. **Período truncado é avisado** — nada de silenciar corte de 2000 batidas.

---

### Task A: Endpoint de agregação do espelho (`app.py`, `logica.py`, testes)

**Files:**
- Modify: `app.py` (nova rota, após `/api/espelho`)
- Test: `testes/test_vinculo_api.py` (acréscimos)

**Interfaces:**
- Produz: `GET /api/espelho/resumo?de=&ate=&grupo=` (exige `_autentica`) →
  `{"de","ate","grupo","colaboradores":[{"nome","grupo","dias_com_batida","dias_impares","dias_incompletos","extra_50_min","extra_100_min","noturno_min","deficit_min","interjornadas_insuficientes","sem_biometria"}],"totais":{"colaboradores","dias_impares","extra_50_min","extra_100_min","noturno_min","deficit_min","sem_biometria"},"truncado":false}`
  - `dias_impares`: dias **passados** (data < hoje) em que `parear_batidas` retorna `impares=True` (ciclo incompleto/órfã). Hoje NUNCA conta.
  - `dias_incompletos`: dias passados com algum slot obrigatório vazio.
  - `grupo` filtra por `grupo_membros`→`grupos.nome`; vazio = todos.
  - Jornada por colaborador: mesmo lookup de `/api/relatorio` (membro > grupo > 480min).
- Consome: `logica.parear_batidas`, `clt.apurar_dia`, `fechamento_mensal` se útil; tabelas `pontos`, `colaboradores`, `grupo_membros`, `grupos`, `ajustes`.
- Performance: 1 query de pontos do período + 1 de ajustes + 1 de grupos/membros; nada de N+1.

- [ ] **Step 1: testes que falham** (401 sem token; dia completo passado não é ímpar; dia ímpar passado conta 1; hoje incompleto não conta; extras somam)
- [ ] **Step 2: rodar e ver falhar**
- [ ] **Step 3: implementar a rota** (sem UPDATE/DELETE em pontos)
- [ ] **Step 4: suíte verde** (125 + novos)

### Task B: Correções da Visão Geral (`static/dashboard.html`)

**Files:**
- Modify: `static/dashboard.html`

**Consome:** `GET /api/espelho/resumo` (Task A).

Correções (as 8 da análise):
1. **Inspetor do dia visível** — mover o painel de `#inspetorDia` para dentro do `.grid-12` como `col-7`; cartão do gráfico vira `col-5` (CSS `.col-5/.col-7` já existe, linhas 474-475). O donut "Status da equipe" (`#donutSvg`, `#donutN`, `#legend`) sai do grid e passa a ocupar um painel próprio abaixo. Remover o atributo `hidden` do painel do inspetor e o container morto `#bars` (item 7) junto do código que o renderiza.
2. **Fim do N+1** — `carregarKpisPainel` deixa de chamar `/api/espelho` por colaborador; usa UMA chamada a `/api/espelho/resumo` para `cImpares`, `cSemBio` e o badge `#cExtrasBadge`.
3. **CSS** — uma única regra de altura para o gráfico: `#graficoSemana svg { min-height: 240px }` (remover a sobreposição de 200px da linha ~581).
4. **Assiduidade sem dados** — período sem batidas → valor `—`, subtítulo "sem dados no período", card sem cor de alerta.
5. **Truncamento avisado** — quando `/api/pontos` retornar exatamente o limite pedido, mostrar aviso discreto (ex.: em `#lblGraficoPeriodo`) de que o período foi truncado.
6. **Donut: folga ≠ ausente** — cruzar com `grupos.dias` (`/api/configuracao` + `/api/vinculos`): quem não tem escala para hoje entra como "Folga" (cor slate clara), não "Ausente".
7. **Remover render morto** — o container `#bars` e o laço que o preenche (a tabela "Jornada da equipe" já cobre).
8. **Saldo pendente real** — "Horas trabalhadas hoje" mantém valor nunca negativo e passa a calcular o saldo pendente de verdade (Σ `jornada − trabalhado` dos turnos abertos, via `/api/resumo`) em vez do ramo morto `trabalho_seg < 0`.

Preservar: todos os demais ids/funções, `#filtrosGlobais` e seus controles, KPIs das 2 linhas, `#tabUsuarios`, `#graficoSemana`/`#legendaTipos`, `#btnAbrirTotem`.

- [ ] **Step 1: snapshot + diff de ids/funções** antes
- [ ] **Step 2: aplicar 1-8 em pedaços pequenos**
- [ ] **Step 3: `node --check` no script inline; todo `$('id')` existe; 0 ids duplicados**
- [ ] **Step 4: suíte verde**
