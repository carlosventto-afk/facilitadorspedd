# Design: migrar de Docker local para VPS (Easypanel)

## Contexto

Hoje o FacilitadorSped roda em "produção" via `docker-compose.yml` na máquina
Windows do usuário — o mesmo compose pensado para desenvolvimento local
(`--reload` no backend, bind-mount do código-fonte, hot reload no frontend).
Quando o Docker dessa máquina para (desligar o computador, reiniciar, etc.),
o sistema para junto — não há nenhum servidor sempre ligado.

Existe uma VPS Hostinger já contratada, com **Easypanel** instalado, hospedando
outros domínios do usuário. O `docs/deploy-railway.md` existente documenta um
caminho alternativo (Railway) que nunca chegou a ser usado — este spec cobre
o caminho real escolhido: Easypanel.

Easypanel é uma camada de gestão sobre Docker + Traefik: cada domínio/app
roda em containers isolados, com HTTPS automático via Let's Encrypt por
domínio configurado na própria UI. Suporta um tipo de serviço "Compose"
(vários containers definidos juntos, com volumes compartilhados entre eles —
o mesmo modelo do `docker-compose.yml` atual), além de templates nativos de
Postgres/Redis com backup pela UI.

## Objetivo

Ter o FacilitadorSped rodando de forma persistente na VPS, com os dados reais
(empresas, jobs, créditos pendentes, arquivos SPED/Excel processados) migrados
do Docker local, sem depender do computador do usuário estar ligado.

## Fora de escopo

- Migrar storage para S3/Object Storage — o `backend/app/core/storage.py` já
  suporta os dois backends (local vs. S3) via variável de ambiente, sem
  mudança de código; pode ser feito depois, se um dia fizer sentido, apenas
  configurando `AWS_*`.
- Zero-downtime durante o corte — a base de dados é pequena e o ambiente
  atual já é informal o suficiente para justificar uma janela curta de
  manutenção em vez de complexidade de migração sem downtime.
- Automatizar backup do Postgres na VPS — mencionado como próximo passo
  recomendado, mas não é bloqueador desta migração (hoje não existe backup
  nenhum, então ligar o backup nativo do Easypanel já é estritamente melhor
  que o estado atual, mesmo que fique para depois).

## Arquitetura alvo

Um único "projeto" no Easypanel (rede interna compartilhada entre os
serviços abaixo, resolvendo nomes de serviço como no `docker-compose.yml`
atual):

- **Postgres**: template nativo do Easypanel (ganha backup pela própria UI
  mais tarde).
- **Redis**: template nativo do Easypanel.
- **backend + celery_worker**: um único serviço tipo **Compose**, replicando
  a topologia do `docker-compose.yml` local — os dois containers montam o
  mesmo volume nomeado para os arquivos de job (upload de entrada, SPED de
  saída). Decisão explícita: manter o storage local em disco compartilhado
  (não migrar para S3 agora — ver "Fora de escopo").
- **frontend**: serviço tipo **App**, buildado a partir de `frontend/Dockerfile`
  (GitHub → build automático a cada push, como already documentado para
  Railway).

### Domínios

- `facilitadorsped.gestaotecnologia.com` → serviço frontend.
- Subdomínio novo para a API, ex. `facilitadorsped-api.gestaotecnologia.com`
  → serviço backend. Necessário porque o Next.js grava `NEXT_PUBLIC_API_URL`
  no bundle do cliente em **build time** — não há proxy de path configurável
  pela UI simples do Easypanel que permita servir front e API sob o mesmo
  domínio sem essa variável apontando para uma origem própria.
- Ambos os domínios precisam de registro DNS (A ou CNAME) apontando para a
  VPS — passo manual do usuário, fora do Easypanel.

### O que muda no repositório

Nenhuma mudança de lógica de aplicação. Apenas:

1. Um compose de produção para o Easypanel (variante do `docker-compose.yml`
   atual): sem `--reload`, sem bind-mount do código-fonte, frontend buildando
   o estágio final `runner` (não `deps`), sem publicar portas de host (o
   Traefik do Easypanel fala com os containers pela rede interna, não por
   porta exposta ao host).
2. `docs/deploy-easypanel.md`, no mesmo estilo do `docs/deploy-railway.md`
   existente — passo a passo com seções **[MANUAL — só você]** para tudo que
   exige acesso à conta Hostinger/Easypanel/DNS, e o que já está pronto no
   repo sem exigir ação nenhuma.

### Segredos e configuração

Reaproveitar os mesmos valores já usados pelo Docker local de hoje
(`SECRET_KEY`, `SENDGRID_API_KEY`, `EMAIL_FROM`) em vez de gerar novos —
gerar um `SECRET_KEY` novo invalidaria todas as sessões/tokens JWT ativos;
reaproveitar `SENDGRID_API_KEY` evita reconfigurar o SendGrid do zero.
`FRONTEND_URL` passa a ser `https://facilitadorsped.gestaotecnologia.com` —
o CORS (`backend/app/main.py`) já inclui `settings.FRONTEND_URL`
dinamicamente, então isso não exige mudança de código, só da variável de
ambiente no serviço backend do Easypanel.

## Migração dos dados

Janela curta de manutenção (parar de aceitar novos jobs no Docker local
antes do passo 1), sem preocupação com downtime zero:

1. `pg_dump` do Postgres local (volume `postgres_data` do
   `docker-compose.yml`) para um arquivo.
2. Compactar o conteúdo do volume `sped_uploads` local (arquivos de entrada
   e saída dos jobs já processados) em um `.tar.gz`.
3. Transferir os dois arquivos para a VPS (scp/SFTP).
4. Restaurar o dump no Postgres criado no Easypanel.
5. Extrair o `.tar.gz` no volume compartilhado do serviço Compose
   (backend + celery_worker) na VPS.
6. Subir os serviços (Postgres → Redis → backend/worker → frontend) e
   validar: `GET /health`, login, listagem de empresas/jobs já existentes,
   reprocessamento de um job de teste (confere que o crédito pendente do
   antecipado especial — `pending_antecipacao_credits` — sobreviveu à
   migração corretamente).
7. Apontar os DNS dos dois domínios para a VPS.
8. Manter o Docker local **desligado, mas intacto** (volumes não removidos)
   por alguns dias como fallback, antes de descartar.

### Rollback

Se algo falhar depois do corte (passo 7), voltar o DNS para o estado
anterior e religar o Docker local — nada foi destruído até a decisão
explícita de descartar os volumes locais (passo 8), então o rollback é
sempre possível durante a janela de validação.

## Testes / validação

Não há testes automatizados aplicáveis (é uma migração de infraestrutura,
não código). Validação é manual, coberta pelo passo 6 acima. O plano de
implementação deve detalhar os comandos exatos de `pg_dump`/`pg_restore` e
tar/untar dos volumes, e o checklist de verificação pós-corte.
