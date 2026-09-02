# Deploy no Easypanel (VPS Hostinger)

Guia passo a passo pra tirar o FacilitadorSped do Docker local e colocar
na VPS, de forma persistente. Etapas **[MANUAL — só você]** exigem acesso
à conta Hostinger/Easypanel e ao painel de DNS do domínio — eu não tenho
esse acesso. O código e os scripts (`docker-compose.easypanel.yml`,
`scripts/migrate_export.sh`, `scripts/migrate_import.sh`) já estão prontos.

## 1. Criar os serviços no Easypanel [MANUAL]

Dentro de um projeto novo (ou existente) no Easypanel:

1. **Add Service → Postgres** (template nativo). Na criação, escolha
   explicitamente a versão **16** (mesma versão do `postgres:16-alpine`
   usado localmente e hardcoded em `scripts/migrate_import.sh`) — uma
   versão mais antiga pode não conseguir restaurar um dump gerado pelo
   pg16. Nomeie o banco `facilitador_sped` (mesmo nome usado localmente);
   se o template não deixar escolher o nome, anote qual foi o nome gerado
   e use-o de forma consistente nas Sections 2 e 4 — o que importa é que
   o `DATABASE_URL` das duas sections aponte pro mesmo banco. Anote a
   `DATABASE_URL` gerada (aba "Credentials"/"Connect" do serviço) — é
   usada, em duas formas diferentes, nas Sections 2 e 4: a Section 2
   precisa de uma cópia com o prefixo trocado para `postgresql+asyncpg://`;
   a Section 4 precisa da string bruta, exatamente como o Easypanel gerou
   (sem `+asyncpg`), porque vai direto pro `psql` dentro do
   `scripts/migrate_import.sh`, que não entende esse prefixo. Guarde as
   duas formas separadamente.
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
| `DATABASE_URL` | a do Postgres do Easypanel (Section 1.1), **com prefixo trocado para `postgresql+asyncpg://`** (driver assíncrono, igual ao Railway) — essa é a forma modificada; não é a mesma string usada na Section 4 |
| `REDIS_URL`, `CELERY_BROKER_URL` | a do Redis do Easypanel (Section 1.2) |
| `CELERY_RESULT_BACKEND` | mesma URL do Redis, mas troque o índice do banco (`/0`, `/1`, etc., no final da URL) para `/1` — não apenas acrescente `/1` à URL como veio, senão vira `.../0/1` |
| `SECRET_KEY` | **o mesmo valor já usado no `.env` local hoje** — não gerar um novo, senão invalida sessões ativas |
| `SENDGRID_API_KEY`, `EMAIL_FROM` | os mesmos valores já usados no `.env` local hoje |
| `FRONTEND_URL` | `https://facilitadorsped.gestaotecnologia.com` |

### Serviço App (`frontend`)

| Variável | Valor |
|---|---|
| `NEXT_PUBLIC_API_URL` | `https://facilitadorsped-api.gestaotecnologia.com/api/v1` — variável de **build**, precisa estar marcada como "Build-time" no Easypanel (o Next.js grava isso no bundle do cliente durante o build) |

Depois de salvar essa variável, dispare um **Rebuild/redeploy** do serviço
`frontend` — como ela só é aplicada durante o build, qualquer build feito
antes de configurá-la não vai ter o valor correto no bundle do cliente.

## 3. Domínios e DNS [MANUAL]

1. No Easypanel, serviço `frontend` → aba Domains → adicionar
   `facilitadorsped.gestaotecnologia.com`. O Easypanel emite o certificado
   HTTPS automaticamente (Let's Encrypt) assim que o DNS resolver pra VPS.
2. No serviço Compose → aba Domains → adicionar
   `facilitadorsped-api.gestaotecnologia.com`, selecionando explicitamente
   o serviço interno **`backend`** e a porta **`8000`** como destino (um
   grupo Compose tem mais de um serviço interno — `backend` e
   `celery_worker` — então é preciso apontar o domínio pro serviço e porta
   certos, não só "adicionar" o domínio genericamente).
3. No painel de DNS do domínio `gestaotecnologia.com`, criar dois registros
   A (ou CNAME) apontando os dois subdomínios acima pro IP da VPS.

## 4. Migração dos dados

1. **[MANUAL]** Abrir a janela de manutenção: pare de aceitar novos jobs no
   sistema local antes de exportar — não crie nem envie novos uploads, e
   deixe qualquer job em processamento terminar (ou cancele-o) antes do
   próximo passo. Esse é o corte de fato: qualquer job criado no Docker
   local depois deste ponto **não** vai pro export e não existirá na VPS.

2. **[já pronto]** Na sua máquina, com o Docker local ainda rodando:
   ```bash
   ./scripts/migrate_export.sh
   ```
   Gera `migration_export/<timestamp>/` com `facilitador_sped.sql` e
   `sped_uploads.tar.gz`.

   Antes de transferir, confira a integridade do export (não existe backup
   em nenhum outro lugar, então vale a pena checar antes de seguir):
   ```bash
   tail -c 200 migration_export/<timestamp>/facilitador_sped.sql
   # deve terminar com "-- PostgreSQL database dump complete"
   tar tzf migration_export/<timestamp>/sped_uploads.tar.gz | head
   # deve listar arquivos, sem erro
   ```

3. **[MANUAL]** Transferir essa pasta pra VPS (scp/SFTP). Primeiro crie o
   diretório de destino na VPS — se ele não existir, o `scp -r` cria
   `/root/migration_export` diretamente como cópia da pasta `<timestamp>`
   (sem uma subpasta com esse nome dentro), e o `cd` do passo 5 falha com
   "No such file or directory":
   ```bash
   ssh usuario@vps 'mkdir -p /root/migration_export'
   scp -r migration_export/<timestamp> usuario@vps:/root/migration_export
   ```

4. **[MANUAL]** Via SSH na VPS, descobrir os dois valores que o script de
   import precisa:
   ```bash
   docker network ls          # rede do projeto Easypanel, ex. "<projeto>_default"
   docker volume ls | grep -i upload   # volume de uploads do serviço Compose
   ```

5. **[já pronto]** Ainda via SSH na VPS, rodar:

   **Atenção:** não rode `alembic upgrade head` antes deste passo, mesmo
   que o `docs/deploy-railway.md` mencione esse comando pra um deploy do
   zero. O dump já inclui o schema completo (e a tabela `alembic_version`
   preenchida) — rodar migrations antes do restore só cria tabelas que o
   restore em seguida vai pular silenciosamente ou falhar ruidosamente ao
   tentar recriar. Só rode `alembic upgrade head` depois, num deploy
   futuro que adicione novas migrations.
   ```bash
   cd /root/migration_export/<timestamp>
   /caminho/pro/repo/scripts/migrate_import.sh . "<DATABASE_URL sem +asyncpg — a string bruta gerada pelo Easypanel>" "<rede_docker>" "<volume_uploads>"
   ```
   (Se o repositório não estiver clonado na VPS, copiar só o
   `scripts/migrate_import.sh` junto com a pasta do export é suficiente —
   o script não depende de mais nada do repo. Os 4 argumentos, nessa ordem,
   são: diretório do export, `DATABASE_URL` do Postgres do Easypanel, nome
   da rede Docker e nome do volume de uploads descobertos no passo 4.
   **Atenção:** use a `DATABASE_URL` bruta anotada na Section 1 — **não** a
   versão com `postgresql+asyncpg://` configurada na Section 2. O script
   passa esse valor direto pro `psql` [`scripts/migrate_import.sh:39`], que
   não reconhece o prefixo `+asyncpg`; usar a forma da Section 2 aqui quebra
   o restore.)

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
apontado) e considerar a VPS como fonte de verdade. Desligar o Docker
local com `docker compose down` (**sem** a flag `-v`) — `down -v` remove
os volumes `facilitadorsped_postgres_data` e `facilitadorsped_sped_uploads`,
exatamente o fallback que precisamos manter intacto. Manter o Docker local
**desligado, mas intacto** (não remover esses dois volumes) por alguns
dias — se algo falhar, é só religar o Docker local, reverter o DNS e
voltar a aceitar novos jobs localmente, encerrando a janela de manutenção
aberta na Section 4, passo 1; nada foi destruído até a decisão explícita
de descartar esses volumes.

Depois que a validação da Section 5 passar (e só depois), apague a cópia
do export que ficou na VPS — ela contém dump completo do banco (hashes de
senha, CNPJs reais, valores fiscais) e todos os uploads, sem criptografia
em repouso, e não deveria continuar ali indefinidamente:
```bash
ssh usuario@vps 'rm -rf /root/migration_export'
```
Mantenha a cópia local (`migration_export/<timestamp>/` na sua máquina)
por enquanto, conforme a janela de rollback acima.

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
