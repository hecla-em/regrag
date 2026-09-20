#!/usr/bin/env bash
# Translate the application's DB_* settings into the PG* variables libpq reads, so every
# script in here connects the way the application does. Source it, do not run it.
#
# Required env:
#   DB_HOST DB_PORT DB_USER DB_PASS DB_NAME         DB_PORT must be the direct port (5432),
#                                                   not a pooler
# Optional env:
#   ENVIRONMENT      default prod. Picks the sslmode default, the way core/config.py does
#   DB_SSLMODE       default verify-full for prod, otherwise prefer
#   DB_SSLROOTCERT   default system, the OS trust store. libpq would otherwise look for
#                    ~/.postgresql/root.crt, which no CI runner has

: "${DB_HOST:?DB_HOST is required}"
: "${DB_PORT:?DB_PORT is required}"
: "${DB_USER:?DB_USER is required}"
: "${DB_PASS:?DB_PASS is required}"
: "${DB_NAME:?DB_NAME is required}"

ENVIRONMENT="${ENVIRONMENT:-prod}"

export PGHOST="$DB_HOST"
export PGPORT="$DB_PORT"
export PGUSER="$DB_USER"
export PGPASSWORD="$DB_PASS"
export PGDATABASE="$DB_NAME"

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
