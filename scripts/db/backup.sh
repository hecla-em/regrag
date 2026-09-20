#!/usr/bin/env bash
# Dump the regrag database and upload the dump to Cloudflare R2.
#
# Required env:
#   DB_HOST DB_PORT DB_USER DB_PASS DB_NAME         Source database. DB_PORT must be the
#                                                   direct port (5432), not a pooler.
#   R2_ACCOUNT_ID R2_ACCESS_KEY_ID                  R2 (S3 API) credentials, only when
#   R2_SECRET_ACCESS_KEY R2_BUCKET                  UPLOAD=true
# Optional env:
#   ENVIRONMENT      default prod. Names the dump and picks the sslmode default, the way
#                    core/config.py does
#   DB_SSLMODE       default verify-full for prod, otherwise prefer
#   DB_SSLROOTCERT   default system, the OS trust store. libpq would otherwise look for
#                    ~/.postgresql/root.crt, which no CI runner has
#   UPLOAD           default true. Set false to dump into the working directory with no
#                    R2 upload
#
# Full recovery runbook: docs/backups.md
set -euo pipefail

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASS:?DB_PASS is required}"
: "${DB_NAME:?DB_NAME is required}"

ENVIRONMENT="${ENVIRONMENT:-prod}"
UPLOAD="${UPLOAD:-true}"

timestamp="$(date -u +%Y%m%d-%H%M%S)"
filename="regrag-${ENVIRONMENT}-${timestamp}.dump"

export PGPASSWORD="$DB_PASS"
if [[ "$ENVIRONMENT" == "prod" ]]; then
  export PGSSLMODE="${DB_SSLMODE:-verify-full}"
else
  export PGSSLMODE="${DB_SSLMODE:-prefer}"
fi
# What certifi.where() is to the application: the roots the server is checked against. libpq
# rejects it alongside the weaker modes, which check no certificate at all.
if [[ "$PGSSLMODE" == verify-* ]]; then
  export PGSSLROOTCERT="${DB_SSLROOTCERT:-system}"
fi

echo "Dumping ${DB_NAME} from ${DB_HOST}:${DB_PORT} (sslmode=${PGSSLMODE}) -> ${filename}"
pg_dump \
  --host="$DB_HOST" \
  --port="$DB_PORT" \
  --username="$DB_USER" \
  --dbname="$DB_NAME" \
  --format=custom \
  --no-owner \
  --no-privileges \
  --file="$filename"

# Cheap sanity check on the archive's table of contents. It reads the header rather than the
# whole dump, so it catches an unreadable archive, not a truncated one.
pg_restore --list "$filename" > /dev/null
echo "Dump complete, table of contents readable ($(du -h "$filename" | cut -f1))"

if [[ "$UPLOAD" != "true" ]]; then
  echo "UPLOAD=$UPLOAD — skipping R2 upload. File at $filename"
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
aws s3 cp "$filename" "s3://${R2_BUCKET}/${key}" \
  --region auto \
  --endpoint-url "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com"

echo "Backup uploaded: ${key}"
