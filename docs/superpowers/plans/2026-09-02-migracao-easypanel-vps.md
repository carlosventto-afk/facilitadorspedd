# Migração Docker local → VPS (Easypanel) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produzir os artefatos de repositório (compose de produção, scripts de export/import de dados, guia de deploy) necessários para migrar o FacilitadorSped do Docker local do usuário para a VPS Hostinger com Easypanel, sem depender do computador do usuário estar ligado.

**Architecture:** Postgres e Redis nativos do Easypanel; backend + celery_worker como um serviço "Compose" único compartilhando um volume de uploads (mesmo modelo do `docker-compose.yml` atual); frontend como serviço "App" separado com domínio próprio. Migração de dados via `pg_dump`/`psql` + tar do volume, com scripts dedicados. Nenhuma mudança de código de aplicação — só configuração/infra.

**Tech Stack:** Docker, Docker Compose, Bash, PostgreSQL (`pg_dump`/`psql`), Easypanel (Postgres/Redis templates, serviço tipo Compose e tipo App), Traefik (gerenciado pelo Easypanel).

**Spec:** `docs/superpowers/specs/2026-09-02-migracao-easypanel-vps-design.md`

## Global Constraints

- Nenhuma mudança de lógica de aplicação em `backend/` ou `frontend/` — só arquivos de infra/config/docs.
- Storage permanece em disco compartilhado entre backend e celery_worker (não migrar para S3 nesta migração — `backend/app/core/storage.py` já suporta isso depois, via env vars, sem mudança de código).
- Reaproveitar `SECRET_KEY`, `SENDGRID_API_KEY`, `EMAIL_FROM` já usados no `.env` local (não gerar novos) — evita invalidar sessões JWT ativas e quebrar o envio de e-mail.
- `FRONTEND_URL` do backend deve virar `https://facilitadorsped.gestaotecnologia.com` (já é lido dinamicamente pelo CORS em `backend/app/main.py`, sem mudança de código).
- Nomes reais do ambiente local, usados nos scripts: container do banco `facilitadorsped-db-1`, banco `facilitador_sped`, usuário `postgres`, volume de uploads `facilitadorsped_sped_uploads`.
- Diretório de uploads dentro do container: `/app/data/uploads` (`LOCAL_STORAGE_DIR=data/uploads`, resolvido a partir de `WORKDIR /app`); o volume Docker é montado na raiz `/app/data`, então o tar deve preservar essa estrutura (tar do conteúdo inteiro do volume, não só da subpasta).

---

### Task 1: Compose de produção para o Easypanel (backend + celery_worker)

**Files:**
- Create: `docker-compose.easypanel.yml`

**Interfaces:**
- Consumes: `backend/Dockerfile`, `frontend/Dockerfile` não são usados aqui (frontend vira serviço "App" separado no Easypanel, fora deste compose).
- Produces: arquivo compose que o serviço "Compose" do Easypanel vai apontar para subir `backend` + `celery_worker` compartilhando o volume `sped_uploads`.

- [ ] **Step 1: Criar o arquivo `docker-compose.easypanel.yml`**

Baseado no `docker-compose.yml` atual, removendo tudo que é específico de dev (hot reload, bind mount do código-fonte, publicação de porta de host — o Traefik do Easypanel acessa os containers pela rede interna do projeto, não por porta de host) e removendo os serviços `db`, `redis` e `frontend` (viram, respectivamente, os templates nativos do Easypanel e um serviço "App" separado):

```yaml
version: "3.9"

services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      CELERY_BROKER_URL: ${CELERY_BROKER_URL}
      CELERY_RESULT_BACKEND: ${CELERY_RESULT_BACKEND}
      DEBUG: "false"
      SECRET_KEY: ${SECRET_KEY}
      SENDGRID_API_KEY: ${SENDGRID_API_KEY}
      EMAIL_FROM: ${EMAIL_FROM}
      FRONTEND_URL: ${FRONTEND_URL}
    volumes:
      - sped_uploads:/app/data
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000

  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    restart: unless-stopped
    environment:
      DATABASE_URL: ${DATABASE_URL}
      REDIS_URL: ${REDIS_URL}
      CELERY_BROKER_URL: ${CELERY_BROKER_URL}
      CELERY_RESULT_BACKEND: ${CELERY_RESULT_BACKEND}
      SECRET_KEY: ${SECRET_KEY}
    volumes:
      - sped_uploads:/app/data
    command: celery -A app.workers.celery_app worker --loglevel=info --concurrency=2

volumes:
  sped_uploads:
```

Nota: `DATABASE_URL`, `REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` vêm dos templates Postgres/Redis nativos do Easypanel (o Easypanel preenche essas variáveis por serviço na própria UI — ver `docs/deploy-easypanel.md`, Task 4). `SECRET_KEY`, `SENDGRID_API_KEY`, `EMAIL_FROM`, `FRONTEND_URL` são preenchidos com os valores reais reaproveitados do `.env` local atual.

- [ ] **Step 2: Validar sintaxe do compose**

Run: `docker compose -f docker-compose.easypanel.yml config`

Expected: sem erro; a saída renderizada não deve conter `--reload` em nenhum `command`, nem `ports:` (nenhuma porta de host publicada), nem bind mount do código-fonte (só o volume nomeado `sped_uploads`). Como as variáveis `${...}` não estão setadas no shell local, o Docker Compose deve avisar com `WARN` sobre variável vazia — isso é esperado (elas só existem no ambiente do Easypanel) e não é uma falha do arquivo.

- [ ] **Step 3: Commit**

```bash
git add docker-compose.easypanel.yml
git commit -m "infra: adiciona compose de produção para o serviço Compose do Easypanel"
```

---

### Task 2: Script de export dos dados locais

**Files:**
- Create: `scripts/migrate_export.sh`
- Modify: `.gitignore` (adicionar `migration_export/`)

**Interfaces:**
- Consumes: containers Docker locais já rodando (`facilitadorsped-db-1`) e o volume `facilitadorsped_sped_uploads` (nomes fixos do ambiente local atual, confirmados via `docker ps`/`docker volume ls`).
- Produces: diretório `migration_export/<timestamp>/` contendo `facilitador_sped.sql` (dump em texto puro) e `sped_uploads.tar.gz` — consumidos pelo `scripts/migrate_import.sh` da Task 3.

- [ ] **Step 1: Adicionar `migration_export/` ao `.gitignore`**

Editar `.gitignore`, na seção "Storage local de arquivos de job", adicionando:

```
# Export local de dados para a migração pra VPS (dump SQL + uploads) —
# nunca deve ir pro histórico do git (dados reais de cliente).
migration_export/
```

- [ ] **Step 2: Criar `scripts/migrate_export.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Exporta o banco Postgres e os arquivos de upload do Docker local para
# um diretório, prontos para transferir pra VPS e restaurar com
# scripts/migrate_import.sh. Rodar da raiz do repositório, com o
# docker-compose.yml local em pé (containers em execução).
#
# Uso: ./scripts/migrate_export.sh

DB_CONTAINER="facilitadorsped-db-1"
DB_NAME="facilitador_sped"
DB_USER="postgres"
UPLOADS_VOLUME="facilitadorsped_sped_uploads"

OUT_DIR="migration_export/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT_DIR"

echo "Exportando banco de dados ($DB_CONTAINER)..."
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" > "$OUT_DIR/facilitador_sped.sql"

echo "Exportando volume de uploads ($UPLOADS_VOLUME)..."
docker run --rm \
  -v "$UPLOADS_VOLUME:/data:ro" \
  -v "$(pwd)/$OUT_DIR:/backup" \
  alpine tar czf /backup/sped_uploads.tar.gz -C /data .

echo ""
echo "Export concluído em: $OUT_DIR"
ls -lh "$OUT_DIR"
```

- [ ] **Step 3: Tornar o script executável**

Run: `chmod +x scripts/migrate_export.sh`

- [ ] **Step 4: Rodar contra os containers locais reais e validar a saída**

Run: `./scripts/migrate_export.sh`

Expected: termina sem erro, imprime o diretório `migration_export/<timestamp>/` com dois arquivos. Validar:
- `head -5 migration_export/<timestamp>/facilitador_sped.sql` começa com comentários `-- PostgreSQL database dump` (confirma que o dump não veio vazio/corrompido).
- `tar tzf migration_export/<timestamp>/sped_uploads.tar.gz | head` lista arquivos (ou está vazio se ainda não há nenhum job processado localmente — nesse caso, sem erro do `tar` já é suficiente).

- [ ] **Step 5: Commit**

```bash
git add scripts/migrate_export.sh .gitignore
git commit -m "infra: adiciona script de export dos dados locais para migração"
```

(O conteúdo gerado em `migration_export/` não é commitado — já está no `.gitignore` da Step 1.)

---

### Task 3: Script de import dos dados na VPS

**Files:**
- Create: `scripts/migrate_import.sh`

**Interfaces:**
- Consumes: `migration_export/<timestamp>/facilitador_sped.sql` e `sped_uploads.tar.gz` gerados pela Task 2 (mesma estrutura de diretório), transferidos manualmente para a VPS (scp/SFTP — passo [MANUAL] documentado na Task 4).
- Produces: banco Postgres do Easypanel populado e volume de uploads do serviço Compose populado — estado pronto para o cutover.

- [ ] **Step 1: Criar `scripts/migrate_import.sh`**

```bash
#!/usr/bin/env bash
set -euo pipefail

# Restaura o dump e os uploads exportados por scripts/migrate_export.sh
# dentro da VPS. Rodar via SSH na VPS, com Docker disponível (o Easypanel
# usa Docker por baixo, então o CLI já está instalado no host).
#
# Uso:
#   ./migrate_import.sh <diretorio_do_export> "<database_url>" <rede_docker> <volume_uploads>
#
# <diretorio_do_export>: pasta com facilitador_sped.sql e sped_uploads.tar.gz
#   (a mesma gerada por migrate_export.sh, copiada pra VPS)
# <database_url>: string de conexão do Postgres criado no Easypanel, formato
#   postgresql://usuario:senha@host:porta/facilitador_sped — pegue na aba
#   "Credentials"/"Connect" do serviço Postgres no painel do Easypanel
# <rede_docker>: nome da rede Docker interna do projeto no Easypanel —
#   descobrir com: docker network ls (geralmente "<nome_do_projeto>_default")
# <volume_uploads>: nome do volume compartilhado criado pelo serviço Compose
#   (backend + celery_worker) — descobrir com: docker volume ls | grep -i upload

EXPORT_DIR="$1"
DATABASE_URL="$2"
DOCKER_NETWORK="$3"
UPLOADS_VOLUME="$4"

if [ ! -f "$EXPORT_DIR/facilitador_sped.sql" ] || [ ! -f "$EXPORT_DIR/sped_uploads.tar.gz" ]; then
  echo "Erro: $EXPORT_DIR precisa conter facilitador_sped.sql e sped_uploads.tar.gz" >&2
  exit 1
fi

echo "Restaurando banco de dados..."
docker run --rm -i \
  --network "$DOCKER_NETWORK" \
  -v "$(pwd)/$EXPORT_DIR:/backup" \
  postgres:16-alpine \
  psql "$DATABASE_URL" -f /backup/facilitador_sped.sql

echo "Restaurando arquivos de upload no volume $UPLOADS_VOLUME..."
docker run --rm \
  -v "$UPLOADS_VOLUME:/data" \
  -v "$(pwd)/$EXPORT_DIR:/backup" \
  alpine tar xzf /backup/sped_uploads.tar.gz -C /data

echo ""
echo "Import concluído."
```

- [ ] **Step 2: Validar sintaxe do script (sem executar — não há VPS acessível neste ambiente)**

Run: `bash -n scripts/migrate_import.sh`

Expected: sem saída, exit code 0 (script sintaticamente válido).

- [ ] **Step 3: Tornar executável e commitar**

```bash
chmod +x scripts/migrate_import.sh
git add scripts/migrate_import.sh
git commit -m "infra: adiciona script de import dos dados na VPS"
```

---

### Task 4: Guia de deploy no Easypanel (`docs/deploy-easypanel.md`)

**Files:**
- Create: `docs/deploy-easypanel.md`

**Interfaces:**
- Consumes: `docker-compose.easypanel.yml` (Task 1), `scripts/migrate_export.sh` (Task 2), `scripts/migrate_import.sh` (Task 3) — o guia referencia os três pelo nome/caminho exato.
- Produces: documento final que o usuário segue passo a passo para executar a migração de verdade (fora do escopo deste plano automatizável — exige acesso à conta Hostinger/Easypanel e DNS).

- [ ] **Step 1: Escrever `docs/deploy-easypanel.md`**

Seguir o mesmo estilo do `docs/deploy-railway.md` existente — seções **[MANUAL — só você]** para tudo que exige acesso à conta, e uma seção final "o que já está pronto" para o que este plano já entrega. Conteúdo:

```markdown
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
   o script não depende de mais nada do repo.)

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
```

- [ ] **Step 2: Self-review do documento contra o spec**

Reler `docs/superpowers/specs/2026-09-02-migracao-easypanel-vps-design.md`
seção por seção e confirmar que cada decisão tem um passo correspondente
no guia: arquitetura (Postgres/Redis nativos, Compose backend+worker,
App frontend) — Section 1; domínios — Section 3; segredos reaproveitados —
Section 2; procedimento de migração — Section 4; validação — Section 5;
rollback — Section 6; backups como próximo passo, não bloqueador — última
seção. Nenhuma lacuna deve sobrar; se sobrar, adicionar a seção faltante
antes de prosseguir.

- [ ] **Step 3: Commit**

```bash
git add docs/deploy-easypanel.md
git commit -m "docs: guia de deploy e migração de dados para o Easypanel"
```

---

## Self-Review (executado ao escrever este plano)

- **Cobertura do spec:** arquitetura alvo → Task 1 (compose) + Task 4
  Section 1/3 (serviços Postgres/Redis/App via UI, documentados pois não
  são artefato de repositório); segredos → Task 4 Section 2; migração de
  dados → Task 2 + Task 3 + Task 4 Section 4; validação → Task 4 Section 5;
  rollback → Task 4 Section 6; backup como próximo passo → Task 4, última
  seção. Nenhum requisito do spec ficou sem task correspondente.
- **Placeholders:** nenhum "TBD"/"implementar depois" — os únicos valores
  parametrizados (URL de conexão do Postgres, nome da rede Docker, nome do
  volume de uploads na VPS) são inerentemente descobertos só depois que os
  serviços existem no Easypanel (não é informação que exista hoje), e cada
  um vem com o comando exato pra descobrir o valor real.
- **Consistência de nomes:** `sped_uploads` (nome do volume dentro do
  `docker-compose.easypanel.yml`) é interno ao Compose service e não tem
  relação direta com `facilitadorsped_sped_uploads` (nome do volume local
  atual, gerado pelo Docker Compose local a partir do nome do projeto) —
  os scripts tratam os dois corretamente como coisas diferentes (export lê
  do volume local pelo nome real `facilitadorsped_sped_uploads`; import
  escreve no volume da VPS, cujo nome real só existe depois de criado,
  daí ser parâmetro do script em vez de constante).
