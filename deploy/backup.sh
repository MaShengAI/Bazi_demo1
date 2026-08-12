#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/.env.preprod}
BACKUP_DIR=${BACKUP_DIR:-$SCRIPT_DIR/backups}
mkdir -p "$BACKUP_DIR"
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
TARGET="$BACKUP_DIR/bazi-$STAMP.sql.gz"

docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/compose.yaml" exec -T mysql \
  sh -c 'exec mysqldump --single-transaction --quick --routines --triggers -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  | gzip -9 > "$TARGET"
gzip -t "$TARGET"
echo "Backup verified: $TARGET"

