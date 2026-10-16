# Deploy de produção — Ponto Digital

## Variáveis de ambiente obrigatórias

| Variável | Descrição |
|---|---|
| `PONTO_DATABASE_URL` | String de conexão Postgres (Supabase/pooler). |
| `PONTO_ADMIN_SENHA` | Senha inicial do admin (vira hash bcrypt na 1ª criação). |
| `PONTO_JWT_SECRET` | Segredo HS256 dos tokens (≥ 32 bytes, aleatório). |
| `PONTO_BITRIX_WEBHOOK` | Webhook de busca de colaboradores no Bitrix. |
| `AGNES_KEY` | Chave da IA Agnes (fallback: `/root/.agnes/tokenplan.key`). |
| `PONTO_EMPRESA_TIPO_ID` | `1`=CNPJ, `2`=CPF (AFD/AEJ). |
| `PONTO_EMPRESA_CNPJ` | CNPJ do empregador (AFD/AEJ). |
| `PONTO_EMPRESA_RAZAO` | Razão social do empregador (AFD/AEJ). |
| `PONTO_EMPRESA_INPI` | Nº do registro INPI (AFD/AEJ). |

Opcionais: `PONTO_BASE_URL` (padrão `http://localhost:8898`), `PONTO_BACKUP_DIR` (padrão `/opt/ponto/backups`).

## systemd

`/etc/systemd/system/ponto-facial.service`:

```ini
[Unit]
Description=Ponto Digital
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ponto
WorkingDirectory=/opt/ponto/ponto-codigo-fonte-extract
EnvironmentFile=/etc/ponto/ponto.env
ExecStart=/opt/ponto/ponto-codigo-fonte-extract/.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8898
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Arquivo de segredos com permissão 0600:

```bash
install -d -m 700 /etc/ponto
install -m 600 /dev/null /etc/ponto/ponto.env   # preencha com as variáveis acima
chmod 644 /etc/systemd/system/ponto-facial.service
systemctl daemon-reload
systemctl enable --now ponto-facial
```

## HTTPS / proxy reverso

Nginx com TLS na 443 encaminhando para o app local:

```nginx
server {
    listen 443 ssl;
    server_name ponto.empresa.com.br;
    ssl_certificate     /etc/letsencrypt/live/ponto.empresa.com.br/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/ponto.empresa.com.br/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8898;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Emissão do certificado: `certbot certonly --nginx -d ponto.empresa.com.br`.

## Backup

Cron diário (rotação mantém os 14 mais recentes):

```cron
0 2 * * * cd /opt/ponto/ponto-codigo-fonte-extract && ./.venv/bin/python backup.py >> /var/log/ponto-backup.log 2>&1
```

Grava em `PONTO_BACKUP_DIR` (padrão `/opt/ponto/backups/<timestamp>/`): `banco.json` + embeddings `.npy`. Para Postgres, complemente com `pg_dump` (o JSON é snapshot sem importador automático).

## Restauração

1. Embeddings: copie os `.npy` do backup para `/opt/ponto/embeddings/`.
2. Banco: recrie as tabelas subindo o app (`criar_schema` roda no startup) e recarregue os dados com `pg_restore` do `pg_dump`; o `banco.json` serve como snapshot legível de emergência.
