#!/usr/bin/env bash
# Restore a regrag dump into a TARGET database. DESTRUCTIVE — never defaults to prod.
#
# Source (pick one, default is the latest R2 backup):
#   (no flag)        download + restore the most recent daily/ backup from R2
#   --key  <r2key>   restore a specific R2 object, e.g. daily/regrag-prod-YYYYMMDD-HHMMSS.dump
#   --file <path>    restore a local .dump file (no R2 access needed)
# R2 access (needed unless --file is used):
#   R2_ACCOUNT_ID R2_ACCESS_KEY_ID R2_SECRET_ACCESS_KEY R2_BUCKET
#
# Target = the compose database by default (local dev values, not prod secrets). Deliberately
# TARGET_* rather than the DB_* of pg-env.sh: a shell that sourced .env.prod must not be able
# to aim a --clean restore at prod. Set these to restore elsewhere, and the confirmation
# prompt always shows the resolved target:
#   TARGET_DB_HOST  default 127.0.0.1
#   TARGET_DB_PORT  default 5432
#   TARGET_DB_USER  default postgres
#   TARGET_DB_PASS  default postgres
#   TARGET_DB_NAME  default regrag_restore_test   (must already exist, on an image with pgvector)
#   FORCE=1         skip the interactive confirmation, for unattended runs
#
# Full recovery runbook: docs/backups.md
set -euo pipefail

SOURCE_FILE=""
R2_KEY=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --file) SOURCE_FILE="${2:?--file needs a path}"; shift 2 ;;
    --key)  R2_KEY="${2:?--key needs an r2 key}"; shift 2 ;;
    *) echo "Unknown arg: $1" >&2; exit 2 ;;
  esac
done

TARGET_DB_HOST="${TARGET_DB_HOST:-127.0.0.1}"
TARGET_DB_PORT="${TARGET_DB_PORT:-5432}"
TARGET_DB_USER="${TARGET_DB_USER:-postgres}"
TARGET_DB_PASS="${TARGET_DB_PASS:-postgres}"
TARGET_DB_NAME="${TARGET_DB_NAME:-regrag_restore_test}"

if [[ -n "$SOURCE_FILE" ]]; then
  [[ -f "$SOURCE_FILE" ]] || { echo "Restore source not found: $SOURCE_FILE" >&2; exit 2; }
else
  : "${R2_ACCOUNT_ID:?R2_ACCOUNT_ID is required to download a backup}"
  : "${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is required to download a backup}"
  : "${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is required to download a backup}"
  : "${R2_BUCKET:?R2_BUCKET is required to download a backup}"
  export AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
  export AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
  endpoint="https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

  if [[ -z "$R2_KEY" ]]; then
    R2_KEY="$(aws s3api list-objects-v2 \
      --bucket "$R2_BUCKET" --prefix "daily/" \
      --query 'sort_by(Contents || `[]`, &LastModified)[-1].Key' --output text \
      --region auto --endpoint-url "$endpoint")"
    [[ -n "$R2_KEY" && "$R2_KEY" != "None" ]] ||
      { echo "No backups found in s3://${R2_BUCKET}/daily/" >&2; exit 1; }
    echo "Latest backup: ${R2_KEY}"
  fi

  SOURCE_FILE="$(basename "$R2_KEY")"
  echo "Downloading s3://${R2_BUCKET}/${R2_KEY}"
  aws s3 cp "s3://${R2_BUCKET}/${R2_KEY}" "$SOURCE_FILE" \
    --region auto --endpoint-url "$endpoint"
fi

echo "About to restore '${SOURCE_FILE}'"
echo "  INTO ${TARGET_DB_USER}@${TARGET_DB_HOST}:${TARGET_DB_PORT}/${TARGET_DB_NAME}"
echo "  This is DESTRUCTIVE (--clean --if-exists)."
if [[ "${FORCE:-0}" != "1" ]]; then
  read -r -p "Type the target db name to confirm: " confirm
  [[ "$confirm" == "$TARGET_DB_NAME" ]] || { echo "Aborted."; exit 1; }
fi

PGPASSWORD="$TARGET_DB_PASS" pg_restore \
  --host="$TARGET_DB_HOST" \
  --port="$TARGET_DB_PORT" \
  --username="$TARGET_DB_USER" \
  --dbname="$TARGET_DB_NAME" \
  --no-owner \
  --no-privileges \
  --clean \
  --if-exists \
  "$SOURCE_FILE"

echo "Restore complete into ${TARGET_DB_NAME}"
