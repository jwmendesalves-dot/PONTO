# Relatório de Impacto à Proteção de Dados Pessoais (RIPD)

**LGPD, art. 38** — Documento de comunicação à ANPD, mantido à disposição.

---

## 1. Descrição do tratamento

Registro eletrônico de ponto com **reconhecimento facial** para ~[PREENCHER]
colaboradores de Rodrigo Brandão Corrêa Sociedade Individual de Advocacia
(Brandão Corrêa Assessoria Jurídica), CNPJ 28.651.615/0001-05.

**Fluxo:** captura da imagem no totem/celular → extração do **embedding facial**
(vetor de 512 dimensões — o dado biométrico) → comparação por similaridade →
verificação de liveness via IA (imagem enviada pontualmente a terceiro) →
registro da marcação (data/hora/tipo/NSR/hash/geolocalização). A foto capturada
é armazenada localmente (`fotos/<nome>.jpg`) apenas para exibição no painel; o
embedding facial (`.npy`) é o dado biométrico utilizado na autenticação.

## 2. Natureza, escopo, contexto e finalidade

- **Natureza:** dado pessoal sensível (biometria, art. 5º II) + dado pessoal;
- **Escopo:** todos os colaboradores;
- **Contexto:** relação de emprego, controle de jornada (CLT art. 74 §2º);
- **Finalidade:** registro de ponto, apuração de jornada, anti-fraude.

## 3. Necessidade e proporcionalidade

- A biometria é **necessária** para autenticar inequivocamente o titular na
  marcação (alternativas — senha/cartão — não atendem à finalidade anti-fraude);
- **Minimização:** a imagem é armazenada localmente apenas para exibição no
  painel; o dado biométrico processado é o embedding facial (vetor `.npy`);
- Geolocalização: avaliar a necessidade; se mantida, reduzir a precisão ao
  mínimo necessário.

## 4. Riscos identificados e medidas de mitigação

| Risco | Probabilidade | Impacto | Mitigação |
|---|---|---|---|
| Acesso indevido à biometria | Baixa | Alto | Permissões 600, autenticação obrigatória, criptografia em trânsito |
| Acesso indevido a PII (CPF/telefone) | Baixa | Alto | Endpoints protegidos por autenticação |
| Fraude de marcação | Média | Médio | Liveness (IA), tipo decidido no servidor, hash encadeado |
| Exposição em terceiro (IA) | Baixa | Médio | DPA, processamento efêmero sem retenção |
| Vazamento de credenciais | Baixa | Alto | Segredos em arquivos 600, JWT independente |

## 5. Medidas de segurança (art. 46)

bcrypt + JWT; rate limiting; segredos em arquivos restritos; fail-closed de
banco (sem fallback silencioso); backup diário; hash SHA-256 encadeado nas
marcações; HTTPS (Cloudflare Tunnel).

## 6. Salvaguardas aos titulares

Aviso de privacidade publicado; canal de atendimento aos direitos (art. 18);
eliminação do embedding ao término do vínculo; retenção de registros por 5 anos
(obrigação trabalhista).

---

**Responsável pela elaboração:** [PREENCHER]  
**Data:** [PREENCHER]
