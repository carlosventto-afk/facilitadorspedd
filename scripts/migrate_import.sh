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
