#!/usr/bin/env bash
# Dump the regrag database and upload the dump to Cloudflare R2.
#
# Required env:
#   DB_*                                            Source database, see scripts/db/pg-env.sh
#   R2_ACCOUNT_ID R2_ACCESS_KEY_ID                  R2 (S3 API) credentials, only when
#   R2_SECRET_ACCESS_KEY R2_BUCKET                  UPLOAD=true
# Optional env:
#   ENVIRONMENT      default prod. Names the dump, and picks the sslmode default
#   UPLOAD           default true. Set false to dump into the working directory with no
#                    R2 upload
#
# Full recovery runbook: docs/backups.md
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/pg-env.sh"

UPLOAD="${UPLOAD:-true}"

timestamp="$(date -u +%Y%m%d-%H%M%S)"
filename="regrag-${ENVIRONMENT}-${timestamp}.dump"

echo "Dumping ${PGDATABASE} from ${PGHOST}:${PGPORT} (sslmode=${PGSSLMODE}) -> ${filename}"
pg_dump \
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
