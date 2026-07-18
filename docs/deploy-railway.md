# Deploy no Railway

Guia passo a passo pra colocar o FacilitadorSped no ar. As etapas marcadas
**[MANUAL — só você]** exigem acesso a contas (Railway, AWS, SendGrid) que
eu não tenho — precisam ser feitas por você direto no navegador/CLI. O
código e a configuração (`railway.toml`, Dockerfiles, `docker-compose.yml`)
já estão prontos, só falta ligar os fios do lado das contas reais.

## 1. Pré-requisitos [MANUAL]

- Conta no [Railway](https://railway.app) (tem plano gratuito com limite de
  uso mensal, suficiente pra validar o MVP antes de assinar um plano pago).
- Repositório no GitHub com este projeto (Railway faz deploy a partir de um
  repo Git — se ainda não subiu pro GitHub, precisa subir antes).
- Uma chave real do SendGrid (ver conversa anterior — `backend/app/core/email.py`
  já está pronto, só falta a chave em `SENDGRID_API_KEY`).
- Credenciais AWS com permissão de leitura/escrita num bucket S3 (ver seção 4).

## 2. Criar o projeto e os serviços gerenciados [MANUAL]

1. No painel do Railway, **New Project** → **Deploy from GitHub repo** →
   selecione este repositório.
2. **Add Postgres** (plugin gerenciado do Railway) dentro do mesmo projeto.
3. **Add Redis** (plugin gerenciado do Railway) dentro do mesmo projeto.

## 3. Criar os 3 serviços de aplicação [MANUAL]

O Railway detecta múltiplos serviços a partir do mesmo repo apontando cada
um para um diretório/Dockerfile diferente. Crie 3 serviços, todos a partir
do mesmo repositório GitHub:

| Serviço | Root Directory | Config-as-code Path | Comando |
|---|---|---|---|
| `backend` | `backend` | `railway.toml` (padrão) | API FastAPI |
| `celery_worker` | `backend` | `backend/railway.worker.toml` | Worker Celery |
| `frontend` | `frontend` | `railway.toml` (padrão) | Next.js |

Para o `celery_worker`, na aba **Settings** do serviço, em **Config-as-code**,
aponte explicitamente para `backend/railway.worker.toml` (o Railway usaria
`backend/railway.toml` — o do serviço da API — por padrão, já que os dois
compartilham o mesmo diretório raiz).

## 4. Variáveis de ambiente [MANUAL]

### `backend` e `celery_worker` (as mesmas nos dois)

| Variável | Valor |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` — pegue a `DATABASE_URL` que o plugin Postgres do Railway gera (aba Variables do plugin) e **troque o prefixo `postgresql://` por `postgresql+asyncpg://`** (o driver assíncrono não é o padrão do Railway) |
| `REDIS_URL`, `CELERY_BROKER_URL` | `redis://...` do plugin Redis do Railway |
| `CELERY_RESULT_BACKEND` | mesma URL do Redis, com `/1` no final (banco lógico separado) |
| `SECRET_KEY` | gere com `openssl rand -hex 32` — **não reaproveitar o valor de dev** |
| `SENDGRID_API_KEY` | sua chave real (ver `docs/` ou a conversa sobre SendGrid) |
| `EMAIL_FROM` | e-mail verificado no SendGrid |
| `FRONTEND_URL` | URL pública do serviço `frontend` no Railway (ou domínio customizado) |
| `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET` | credenciais reais da AWS (ver seção 5) — **sem isso, os dois serviços não compartilham arquivo nenhum, upload feito num não aparece no outro** |
| `DEBUG` | `false` (desliga `/docs` público e mensagens de erro verbosas) |

### `frontend`

| Variável | Valor |
|---|---|
| `NEXT_PUBLIC_API_URL` | URL pública do serviço `backend` + `/api/v1` — **variável de build**, precisa estar configurada como "Build-time" no Railway (Next.js grava `NEXT_PUBLIC_*` no bundle do cliente durante o build, não em runtime) |

## 5. Bucket S3 real [MANUAL]

1. No console AWS → S3 → **Create bucket** (nome único globalmente, ex.
   `facilitador-sped-prod`).
2. IAM → criar um usuário (ou role) com uma policy restrita só a esse bucket
   (`s3:GetObject`, `s3:PutObject`, `s3:DeleteObject` em
   `arn:aws:s3:::facilitador-sped-prod/*`) — evite usar uma chave com acesso
   total à conta.
3. Gerar as Access Keys desse usuário e colocar em `AWS_ACCESS_KEY_ID` /
   `AWS_SECRET_ACCESS_KEY` nas variáveis do Railway (seção 4).

O backend detecta a presença de `AWS_ACCESS_KEY_ID` automaticamente e liga o
backend S3 sozinho (ver `backend/app/core/storage.py`) — sem isso, cai no
disco local, que **não funciona** com `backend`/`celery_worker` como
serviços Railway separados (não compartilham filesystem).

## 6. Migration e usuário admin inicial [MANUAL, primeira vez só]

Depois do primeiro deploy do serviço `backend` (via Railway CLI, ou usando
o "Shell" da aba do serviço no painel):

```bash
alembic upgrade head
SEED_ADMIN_EMAIL=seu-email-real@empresa.com SEED_ADMIN_PASSWORD='SenhaForte!123' python -m scripts.seed
```

**Não use os valores padrão do `scripts/seed.py`** (`admin@facilitadorsped.com.br`
/ `Admin@123`) em produção — defina `SEED_ADMIN_EMAIL`/`SEED_ADMIN_PASSWORD`
como mostrado acima.

## 7. CORS e domínio [MANUAL, se o domínio final for diferente]

`backend/app/main.py` já tem `https://facilitadorsped.com.br` e
`https://www.facilitadorsped.com.br` na lista de origens permitidas
(`allow_origins`). Se o domínio real for outro, editar essa lista antes do
deploy final.

## O que já está pronto (não precisa fazer nada)

- `backend/railway.toml`, `backend/railway.worker.toml`, `frontend/railway.toml`
  — configuração de build/start/healthcheck de cada serviço.
- Dockerfiles de `backend/` e `frontend/` já buildam em modo produção por
  padrão (sem `--reload`, com `next build` + standalone) — o
  `docker-compose.yml` local só os sobrescreve para o fluxo de
  desenvolvimento (hot reload), não afeta o Railway.
- `GET /health` já existe (`backend/app/main.py`) — usado pelo healthcheck
  do `railway.toml` do backend.
- Storage S3 (`backend/app/core/storage.py`) já resolve o problema de
  `backend`/`celery_worker` serem serviços separados sem disco
  compartilhado, desde que as credenciais AWS estejam configuradas
  (seção 4/5).
