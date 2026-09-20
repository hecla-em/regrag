#!/usr/bin/env bash
# Open a psql prompt on the database DB_* points at, read-only unless WRITABLE=1.
#
# Source the env file you want first, then pass any psql arguments through:
#   set -a; source backend/.env.prod; set +a
#   scripts/db/psql.sh
#   scripts/db/psql.sh -c 'select count(*) from chat_requests'
#
# Connection and TLS variables: scripts/db/pg-env.sh. Full runbook: docs/backups.md
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/pg-env.sh"

if [[ "${WRITABLE:-0}" == "1" ]]; then
  access="writable"
else
  access="read-only"
  export PGOPTIONS="-c default_transaction_read_only=on${PGOPTIONS:+ $PGOPTIONS}"
fi

# On stderr, so psql -c output stays pipeable.
echo "psql ${PGUSER}@${PGHOST}:${PGPORT}/${PGDATABASE} (sslmode=${PGSSLMODE}, ${access})" >&2
exec psql "$@"
