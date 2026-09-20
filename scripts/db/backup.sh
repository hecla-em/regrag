#!/usr/bin/env bash
# Dump the regrag database and upload the dump to Cloudflare R2.
#
# Required env:
#   DB_HOST DB_PORT DB_USER DB_PASS DB_NAME         Source database. DB_PORT must be the
#                                                   direct port (5432), not a pooler.
#   R2_ACCOUNT_ID R2_ACCESS_KEY_ID                  R2 (S3 API) credentials, only when
#   R2_SECRET_ACCESS_KEY R2_BUCKET                  UPLOAD=true
# Optional env:
#   DB_SSLMODE       default verify-full, so prod credentials are never sent in the clear;
#                    set disable for the compose database, which serves no TLS
#   UPLOAD           default true; set false to dump locally with no R2 upload
#   OUT_DIR          default "."; directory the .dump file is written to
set -euo pipefail

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASS:?DB_PASS is required}"
: "${DB_NAME:?DB_NAME is required}"

UPLOAD="${UPLOAD:-true}"
OUT_DIR="${OUT_DIR:-.}"

timestamp="$(date -u +%Y%m%d-%H%M%S)"
filename="regrag-prod-${timestamp}.dump"
filepath="${OUT_DIR%/}/${filename}"

export PGPASSWORD="$DB_PASS"
export PGSSLMODE="${DB_SSLMODE:-verify-full}"

echo "Dumping ${DB_NAME} from ${DB_HOST}:${DB_PORT} (sslmode=${PGSSLMODE}) -> ${filepath}"
pg_dump \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --format=custom \
  --compress=9 \
  --no-owner \
  --no-privileges \
  --file="$filepath"

# A dump that pg_restore cannot read its way through is worth catching now, not on the day
# it is needed.
pg_restore --list "$filepath" > /dev/null
echo "Dump complete and readable ($(du -h "$filepath" | cut -f1))"

if [[ "$UPLOAD" != "true" ]]; then
  echo "UPLOAD=$UPLOAD — skipping R2 upload. File at $filepath"
  exit 0
fi

: "${R2_ACCOUNT_ID:?R2_ACCOUNT_ID is required for upload}"
: "${R2_ACCESS_KEY_ID:?R2_ACCESS_KEY_ID is required for upload}"
: "${R2_SECRET_ACCESS_KEY:?R2_SECRET_ACCESS_KEY is required for upload}"
: "${R2_BUCKET:?R2_BUCKET is required for upload}"

key="daily/${filename}"
echo "Uploading to s3://${R2_BUCKET}/${key}"
AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
aws s3 cp "$filepath" "s3://${R2_BUCKET}/${key}" \
  --region auto \
  --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

echo "Backup uploaded: ${key}"
