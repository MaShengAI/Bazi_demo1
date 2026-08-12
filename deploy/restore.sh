#!/usr/bin/env sh
set -eu

if [ "$#" -ne 1 ]; then
  echo "Usage: CONFIRM_RESTORE=RESTORE_BAZI ./restore.sh backups/bazi-TIMESTAMP.sql.gz" >&2
  exit 2
fi
if [ "${CONFIRM_RESTORE:-}" != "RESTORE_BAZI" ]; then
  echo "Restore refused: set CONFIRM_RESTORE=RESTORE_BAZI explicitly." >&2
  exit 2
fi

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE=${ENV_FILE:-$SCRIPT_DIR/.env.preprod}
SOURCE=$1
gzip -t "$SOURCE"
gzip -dc "$SOURCE" | docker compose --env-file "$ENV_FILE" -f "$SCRIPT_DIR/compose.yaml" exec -T mysql \
  sh -c 'exec mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"'
echo "Restore completed from: $SOURCE"

