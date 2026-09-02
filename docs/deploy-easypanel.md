# Deploy no Easypanel (VPS Hostinger)

Guia passo a passo pra tirar o FacilitadorSped do Docker local e colocar
na VPS, de forma persistente. Etapas **[MANUAL — só você]** exigem acesso
à conta Hostinger/Easypanel e ao painel de DNS do domínio — eu não tenho
esse acesso. O código e os scripts (`docker-compose.easypanel.yml`,
`scripts/migrate_export.sh`, `scripts/migrate_import.sh`) já estão prontos.

## 1. Criar os serviços no Easypanel [MANUAL]

Dentro de um projeto novo (ou existente) no Easypanel:

1. **Add Service → Postgres** (template nativo). Anote a `DATABASE_URL`
   gerada (aba "Credentials"/"Connect" do serviço) — vai ser usada nas
   Sections 2 e 4.
2. **Add Service → Redis** (template nativo). Anote a URL de conexão.
3. **Add Service → Compose**, apontando pro `docker-compose.easypanel.yml`
   deste repositório (conectar o GitHub, escolher o arquivo). Isso cria
   `backend` e `celery_worker` compartilhando o volume `sped_uploads`.
4. **Add Service → App**, root directory `frontend`, Dockerfile padrão
   (build até o estágio final `runner` — sem overrides, diferente do
   `docker-compose.yml` local).

## 2. Variáveis de ambiente [MANUAL]

### Serviço Compose (`backend` e `celery_worker`)

| Variável | Valor |
|---|---|
| `DATABASE_URL` | a do Postgres do Easypanel (Section 1.1), com prefixo trocado para `postgresql+asyncpg://` (driver assíncrono, igual ao Railway) |
| `REDIS_URL`, `CELERY_BROKER_URL` | a do Redis do Easypanel (Section 1.2) |
| `CELERY_RESULT_BACKEND` | mesma URL do Redis, com `/1` no final |
| `SECRET_KEY` | **o mesmo valor já usado no `.env` local hoje** — não gerar um novo, senão invalida sessões ativas |
| `SENDGRID_API_KEY`, `EMAIL_FROM` | os mesmos valores já usados no `.env` local hoje |
| `FRONTEND_URL` | `https://facilitadorsped.gestaotecnologia.com` |

### Serviço App (`frontend`)

| Variável | Valor |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://facilitadorsped-api.gestaotecnologia.com/api/v1` — variável de **build**, precisa estar marcada como "Build-time" no Easypanel (o Next.js grava isso no bundle do cliente durante o build) |

## 3. Domínios e DNS [MANUAL]

1. No Easypanel, serviço `frontend` → aba Domains → adicionar
   `facilitadorsped.gestaotecnologia.com`. O Easypanel emite o certificado
   HTTPS automaticamente (Let's Encrypt) assim que o DNS resolver pra VPS.
2. Serviço `backend` (dentro do serviço Compose) → aba Domains → adicionar
   `facilitadorsped-api.gestaotecnologia.com`.
3. No painel de DNS do domínio `gestaotecnologia.com`, criar dois registros
   A (ou CNAME) apontando os dois subdomínios acima pro IP da VPS.

## 4. Migração dos dados

1. **[já pronto]** Na sua máquina, com o Docker local ainda rodando:
   ```bash
   ./scripts/migrate_export.sh
   ```
   Gera `migration_export/<timestamp>/` com `facilitador_sped.sql` e
   `sped_uploads.tar.gz`.

2. **[MANUAL]** Transferir essa pasta pra VPS (scp/SFTP):
   ```bash
   scp -r migration_export/<timestamp> usuario@vps:/root/migration_export
   ```

3. **[MANUAL]** Via SSH na VPS, descobrir os dois valores que o script de
   import precisa:
   ```bash
   docker network ls          # rede do projeto Easypanel, ex. "<projeto>_default"
   docker volume ls | grep -i upload   # volume de uploads do serviço Compose
   ```

4. **[já pronto]** Ainda via SSH na VPS, rodar:
   ```bash
   cd /root/migration_export/<timestamp>
   /caminho/pro/repo/scripts/migrate_import.sh . "<DATABASE_URL>" "<rede_docker>" "<volume_uploads>"
   ```
   (Se o repositório não estiver clonado na VPS, copiar só o
   `scripts/migrate_import.sh` junto com a pasta do export é suficiente —
   o script não depende de mais nada do repo. Os 4 argumentos, nessa ordem,
   são: diretório do export, `DATABASE_URL` do Postgres do Easypanel, nome
   da rede Docker e nome do volume de uploads descobertos no passo 3.)

## 5. Validação pós-migração [MANUAL]

- `GET https://facilitadorsped-api.gestaotecnologia.com/health` responde OK.
- Login funciona em `https://facilitadorsped.gestaotecnologia.com` com uma
  conta existente (confirma que o dump do banco restaurou os usuários).
- Empresas e jobs já processados aparecem nas telas correspondentes.
- Reprocessar um job de teste conclui com sucesso (confirma que o volume
  de uploads restaurou os arquivos de entrada, e que o crédito pendente do
  antecipado especial em `pending_antecipacao_credits` sobreviveu à
  migração corretamente — ver `docs/timing-credito-e111.md`).

## 6. Corte e rollback

Só depois da validação da Section 5: apontar o DNS final (se ainda não
apontado) e considerar a VPS como fonte de verdade. Manter o Docker local
**desligado, mas intacto** (não remover os volumes `facilitadorsped_postgres_data`
e `facilitadorsped_sped_uploads`) por alguns dias — se algo falhar, é só
religar o Docker local e reverter o DNS; nada foi destruído até a decisão
explícita de descartar esses volumes.

## Próximo passo recomendado (fora desta migração)

Ligar o backup automático do Postgres pela própria UI do Easypanel — hoje
não existe backup nenhum (nem local, nem na VPS), então isso é uma melhoria
estritamente positiva, mas não bloqueia a migração em si.

## O que já está pronto (não precisa fazer nada)

- `docker-compose.easypanel.yml` — compose de produção do serviço Compose
  (backend + celery_worker), sem hot reload e sem bind mount de código.
- `scripts/migrate_export.sh` — export do banco e dos uploads locais.
- `scripts/migrate_import.sh` — restore desses dados na VPS.
- CORS do backend (`backend/app/main.py`) já inclui `FRONTEND_URL`
  dinamicamente — não precisa editar código pra aceitar o novo domínio.
- Storage (`backend/app/core/storage.py`) já funciona em disco
  compartilhado sem nenhuma configuração extra — S3 continua disponível
  como opção futura, sem mudança de código.
