# Guia de Registro do Programa no INPI

**Portaria MTP nº 671/2021, art. 91** — o REP-P exige **certificado de registro
de programa de computador no INPI** (Instituto Nacional da Propriedade
Industrial).

---

## O que registrar

O software "Ponto Digital" (programa de registro eletrônico de ponto via
programa — REP-P), com o número do registro informado no campo `190-206` do AFD
(cabeçalho) e no registro tipo 02 do AEJ (`nrRep`).

## Passos

1. Acessar o **e-RPC** (sistema eletrônico de registro de programas de
   computador do INPI): https://www.gov.br/inpi/pt-br/servicos/programas-de-computador
2. Preencher o formulário com: título, autor(es), titular, linguagem, campo de
   aplicação e resumo do programa;
3. Anexar a documentação técnica (código-fonte ou trechos, conforme instruções
   do INPI);
4. Recolher a retribuição (guia GRU);
5. Obter o **certificado de registro** com o número oficial.

## Após o registro

- Inserir o número do INPI nas variáveis de ambiente do serviço:

```
PONTO_EMPRESA_INPI=<número do registro>
PONTO_EMPRESA_CNPJ=<CNPJ do empregador>
PONTO_EMPRESA_RAZAO=<razão social>
PONTO_DEV_CNPJ=<CNPJ do desenvolvedor>
PONTO_DEV_EMAIL=<e-mail do desenvolvedor>
```

Esses valores passam a preencher automaticamente o AFD e o AEJ.

## Observação

O registro no INPI é um **ato administrativo** do titular do software (não pode
ser executado por terceiro em nome da empresa). Este guia orienta o
procedimento; a efetivação é responsabilidade da empresa/desenvolvedor.
