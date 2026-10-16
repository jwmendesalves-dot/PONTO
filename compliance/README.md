# Compliance — Ponto Digital (REP-P + LGPD)

Documentos e artefatos de conformidade com a **Portaria MTP nº 671/2021**
(registro eletrônico de ponto) e a **LGPD** (Lei nº 13.709/2018).

## O que está implementado (código)

| Requisito | Status | Onde |
|---|---|---|
| AFD (Anexo I) — posições fixas, NSR, CRC-16, hash SHA-256 | ✅ | `fiscal.py`, `GET /api/afd` |
| AEJ (Anexo VI) — pipe-delimitado, registros 01–09 | ✅ | `fiscal.py`, `GET /api/aej` |
| Comprovante com hash SHA-256 | ✅ | resposta do `/api/reconhecer` |
| Hash encadeado (inviolabilidade) | ✅ | colunas `nsr`/`hash` na tabela `pontos` |
| Tipo da marcação decidido no servidor (não forjável) | ✅ | `proximo_tipo()` |
| Append-only das marcações | ⚠️ parcial | sem UPDATE/DELETE via API (falta trigger no banco) |
| Backups (retenção 5 anos) | ✅ | `backup.py` + cron diário |

## O que depende de ato externo (você precisa executar)

| Requisito | O que fazer | Documento |
|---|---|---|
| Registro no INPI (art. 91) | Registrar o programa no e-RPC | `registro-inpi.md` |
| Assinatura digital CAdES/PAdES (ICP-Brasil) | Adquirir certificado A1/A3 e integrar assinatura | `atestado-tecnico-termo-responsabilidade.md` |
| Atestado Técnico + Termo de Responsabilidade (art. 89 §4º) | Preencher e assinar | `atestado-tecnico-termo-responsabilidade.md` |
| Aviso de Privacidade (LGPD) | Preencher dados e publicar | `aviso-privacidade.md` |
| DPA/Contrato de Operador com a IA (art. 39/26/33) | Firmar com o provedor | `dpa-operador-ia.md` |
| RIPD (art. 38) | Preencher e arquivar | `ripd.md` |
| Indicação do DPO (art. 41) | Nomear e publicar | `aviso-privacidade.md` |

## Configuração (variáveis de ambiente no `ponto-facial.service`)

```
PONTO_EMPRESA_CNPJ=<CNPJ do empregador>
PONTO_EMPRESA_RAZAO=<razão social>
PONTO_EMPRESA_INPI=<nº do registro INPI>
PONTO_DEV_CNPJ=<CNPJ do desenvolvedor>
PONTO_DEV_EMAIL=<e-mail do desenvolvedor>
```

## Uso

```bash
# AFD (Arquivo Fonte de Dados)
curl -H "Authorization: Bearer $TOKEN" "https://ponto.acidentesbeneficiosinss.org/api/afd?de=2026-10-01&ate=2026-10-31"

# AEJ (Arquivo Eletrônico de Jornada)
curl -H "Authorization: Bearer $TOKEN" "https://ponto.acidentesbeneficiosinss.org/api/aej?de=2026-10-01&ate=2026-10-31"
```

Os arquivos são devolvidos como texto (leiaute oficial); para entrega ao
Auditor-Fiscal, assinar digitalmente (CAdES) e gravar em `.p7s` destacado.
