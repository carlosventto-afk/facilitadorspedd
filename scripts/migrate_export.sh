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

# Se pg_dump ou o tar via docker run falharem no meio do caminho, o
# redirecionamento (>) já criou o arquivo de saída — sem este trap ele
# ficaria pra trás, zerado ou truncado, e poderia passar por um export
# válido numa migração sem nenhum outro backup.
trap 'rm -f "$OUT_DIR/facilitador_sped.sql" "$OUT_DIR/sped_uploads.tar.gz"' ERR

echo "Exportando banco de dados ($DB_CONTAINER)..."
docker exec "$DB_CONTAINER" pg_dump -U "$DB_USER" "$DB_NAME" > "$OUT_DIR/facilitador_sped.sql"

echo "Exportando volume de uploads ($UPLOADS_VOLUME)..."
# MSYS_NO_PATHCONV prevents bash from converting /data to Windows paths
MSYS_NO_PATHCONV=1 docker run --rm \
  -v "$UPLOADS_VOLUME":/data:ro \
  alpine tar czf - -C /data . > "$OUT_DIR/sped_uploads.tar.gz"

echo ""
echo "Export concluído em: $OUT_DIR"
ls -lh "$OUT_DIR"
