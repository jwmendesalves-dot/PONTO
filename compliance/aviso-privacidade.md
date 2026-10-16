# Aviso de Privacidade — Ponto Digital (Reconhecimento Facial)

**Controlador:** Rodrigo Brandão Corrêa Sociedade Individual de Advocacia
(Brandão Corrêa Assessoria Jurídica), CNPJ 28.651.615/0001-05
**Endereço:** Rua Gago Coutinho, 520, Araés, Cuiabá - MT, CEP 78005-730
**Encarregado (DPO):** [PREENCHER: nome e e-mail de contato]
**Última atualização:** [PREENCHER: data]

Este Aviso descreve como tratamos os dados pessoais no sistema de ponto
eletrônico com reconhecimento facial ("Ponto Digital"), em conformidade com a
Lei Geral de Proteção de Dados (Lei nº 13.709/2018 — LGPD).

---

## 1. Quais dados tratamos

| Categoria | Dados | Classificação LGPD |
|---|---|---|
| Identificação | Nome, CPF, telefone | Dado pessoal |
| Biométrico | Embedding facial (vetor de 512 dimensões — **a foto não é armazenada**) | **Dado pessoal sensível** (art. 5º, II) |
| Marcação de ponto | Data, hora, tipo (entrada/pausa/volta/término), NSR, hash | Dado pessoal |
| Localização | Latitude/longitude aproximada no momento da batida | Dado pessoal (art. 5º, I) |

## 2. Finalidade

- Registro e controle de jornada de trabalho, **obrigação legal** (CLT, art. 74,
  § 2º, para estabelecimentos com mais de 20 empregados);
- Autenticação do empregado na marcação de ponto (anti-fraude);
- Apuração de jornada, banco de horas, faltas e extras (fins trabalhistas e
  previdenciários).

## 3. Base legal

- **Dados sensíveis (biometria):** art. 11, II, "a" (obrigação legal) e "g"
  (garantia da prevenção à fraude e da segurança do titular, no contexto da
  autenticação). **Não** utilizamos consentimento como base, pois a relação de
  subordinação pode comprometer a liberdade do titular.
- **Demais dados:** art. 7º, II (obrigação legal) e IX (legítimo interesse).

## 4. Compartilhamento

- **Armazenamento:** banco de dados (PostgreSQL) em servidor próprio/VPS
  ([PREENCHER: provedor/infra]);
- **Liveness (anti-fraude):** a imagem é enviada pontualmente ao provedor de IA
  [agnes/APHub] para verificação de presença real, **sem armazenamento** por
  parte do provedor (ver Contrato de Operador — DPA).

## 5. Retenção

- Marcações de ponto (AFD/AEJ): **mínimo 5 anos** (legislação trabalhista);
- Embedding facial: eliminado ao **término do vínculo** de trabalho, observada a
  guarda legal dos registros de ponto.

## 6. Segurança (art. 46)

- Senha com hash bcrypt; sessão JWT; autenticação obrigatória nos endpoints de
  dados pessoais; rate limiting; controle de acesso por permissão;
- Embeddings em arquivos com permissão restrita (600) e criptografia em trânsito
  (HTTPS via Cloudflare Tunnel);
- Hash encadeado (SHA-256) garante a inviolabilidade das marcações.

## 7. Direitos do titular (art. 18)

Você pode solicitar, a qualquer momento: confirmação da existência de
tratamento, acesso, correção, anonimização/eliminação, portabilidade e
informação sobre compartilhamentos, através de **[PREENCHER: canal de contato]**.

## 8. Alterações

Este Aviso pode ser atualizado. A versão vigente estará sempre disponível em
**[PREENCHER: URL]**.
