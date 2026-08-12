#!/usr/bin/env sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$SCRIPT_DIR/preflight.py" --env-file "${ENV_FILE:-$SCRIPT_DIR/.env.preprod}" "$@"

