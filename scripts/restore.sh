#!/usr/bin/env bash
# Restore an Atlas database from a pg_dump custom-format dump (ADR-0055).
#
# Usage:
#   scripts/restore.sh <dump-file> [database]
#
# Environment (with sensible defaults):
#   PGHOST      (default: localhost)
#   PGPORT      (default: 5432)
#   PGUSER      (default: atlas)
#   PGPASSWORD  (required if the role needs a password)
#
# The dump is produced by `atlas backup` / the scheduled backup task, in
# PostgreSQL custom format, and is restored with pg_restore. --clean --if-exists
# drops existing objects first so the restore is idempotent.
set -euo pipefail

DUMP="${1:?usage: restore.sh <dump-file> [database]}"
DATABASE="${2:-atlas}"
: "${PGHOST:=localhost}"
: "${PGPORT:=5432}"
: "${PGUSER:=atlas}"

if [[ ! -f "$DUMP" ]]; then
  echo "error: dump file not found: $DUMP" >&2
  exit 1
fi

echo "Restoring '$DUMP' into database '$DATABASE' on $PGHOST:$PGPORT as $PGUSER"
read -r -p "This will DROP and recreate existing objects. Continue? [y/N] " reply
[[ "$reply" == "y" || "$reply" == "Y" ]] || { echo "aborted"; exit 1; }

pg_restore \
  --host "$PGHOST" \
  --port "$PGPORT" \
  --username "$PGUSER" \
  --dbname "$DATABASE" \
  --clean --if-exists --no-owner \
  "$DUMP"

echo "Restore complete."
