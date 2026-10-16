# Atestado Técnico e Termo de Responsabilidade

**Conforme Portaria MTP nº 671/2021, art. 89, § 4º e Anexo VII**

---

## ATESTADO TÉCNICO

O desenvolvedor abaixo identificado declara, sob as penas da lei, que o sistema
de registro eletrônico de ponto descrito atende aos requisitos técnicos da
Portaria MTP nº 671/2021 e legislação correlata.

| Item | Conteúdo |
|---|---|
| **Programa** | Ponto Digital (REP-P — Registrador Eletrônico de Ponto via Programa) |
| **Versão** | 1.0.0 |
| **Desenvolvedor** | [PREENCHER: nome/razão social], CNPJ/CPF [PREENCHER] |
| **Registro INPI** | [PREENCHER: nº do certificado de registro de programa] |
| **Arquivos gerados** | AFD (Anexo I), AEJ (Anexo VI), comprovante de marcação |
| **Assinatura** | CAdES (AFD/AEJ) e PAdES (comprovante), certificado ICP-Brasil |

**Requisitos atendidos:**

1. Coleta, armazenamento e tratamento de marcações de ponto;
2. Geração do **AFD** com NSR sequencial, CRC-16 e hash SHA-256 encadeado
   (inviolabilidade — impossibilidade de alteração/eliminação retroativa);
3. Geração do **AEJ** conforme Anexo VI;
4. Comprovante de marcação com hash SHA-256;
5. Tipo da marcação decidido exclusivamente pelo servidor (máquina de estados),
   sem possibilidade de o empregado forjar entrada/saída;
6. Execução em servidor dedicado/ambiente de nuvem com registro.

Data: [PREENCHER]  
Assinatura do desenvolvedor: ____________________________

---

## TERMO DE RESPONSABILIDADE

O desenvolvedor acima identificado declara-se responsável pelo funcionamento do
programa, pela geração dos arquivos fiscais (AFD/AEJ) em conformidade com os
leiautes oficiais, e pela manutenção dos requisitos de segurança e
inviolabilidade exigidos pela Portaria MTP nº 671/2021.

A empresa usuária é responsável pela guarda dos arquivos gerados (mínimo 5
anos), pela configuração dos horários contratuais e pela operação do sistema.

| **Empresa usuária** | Rodrigo Brandão Corrêa Sociedade Individual de Advocacia, CNPJ 28.651.615/0001-05 |
|---|---|
| **Responsável** | [PREENCHER: nome do responsável legal] |
| **Local** | Rua Gago Coutinho, 520, Araés, Cuiabá - MT |

Data: [PREENCHER]  
Assinatura do responsável: ____________________________

---

> **Observação:** os arquivos AFD/AEJ gerados devem ser **assinados digitalmente**
> (CAdES, arquivo `.p7s` destacado) com certificado ICP-Brasil do desenvolvedor,
> e os comprovantes de marcação em PAdES (PDF), conforme Portaria MTP nº
> 1.486/2022. A integração de assinatura depende do certificado digital.
