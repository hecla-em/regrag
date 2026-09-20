# Database backups

The prod database is backed up nightly to Cloudflare R2. PlanetScale takes its own
backups of the `hecla-em` cluster and those stay the first thing to restore from — this
job exists so a lost PlanetScale account or cluster does not take the backups with it.

## What runs

- **Workflow:** `.github/workflows/backup.yml` — daily at 02:00 UTC, an hour before the
  ingest run, plus manual `workflow_dispatch`.
- **Dump + upload:** `scripts/db/backup.sh` writes `daily/regrag-prod-<timestamp>.dump`
  to the `regrag-db-backups` R2 bucket, after checking the archive's table of contents with
  `pg_restore --list` so an unreadable dump fails the job rather than sitting in the bucket.
  That reads the archive header, not the whole file, so it does not prove the dump restores
  — see [Restore](#restore).
- **Retention:** a 30-day R2 lifecycle rule deletes old objects, configured in
  Cloudflare rather than the workflow.
- **Connection:** every script here takes its database from `DB_*` via
  `scripts/db/pg-env.sh`, which translates those into the `PG*` variables libpq reads. The
  port, TLS and trust-root rules below are all set in that one file.

The dump covers the whole `regrag` logical database. Most of it is the corpus, which
`ingest` rebuilds from CELLAR anyway — what could not be recovered any other way is the
chat ledger and the eval runs. Dumping everything is still simpler than picking tables.

## Connection notes

- **Port.** `DB_PORT` is the direct PlanetScale port, **5432**. `pg_dump` cannot run over a
  transaction pooler, which has no prepared-statement support, even though the
  application's driver connects over one fine.
- **TLS.** `pg-env.sh` picks its `sslmode` default from `ENVIRONMENT` the way
  `core/config.py` does: `verify-full` for prod, so credentials are never sent in the clear
  to a host that failed to prove itself, and `prefer` elsewhere, which the compose database
  accepts. `DB_SSLMODE` overrides it either way.
- **Trust roots.** `sslrootcert` is set to `system`, the OS trust store, which is what
  `certifi.where()` gives the application. Without it libpq looks for
  `~/.postgresql/root.crt`, which no CI runner has, and `verify-full` fails before the dump
  starts. Needs a client of PostgreSQL 16 or newer.
- **Client version.** The workflow installs `postgresql-client-17` to match the server:
  `pg_dump` refuses a server newer than itself, and a dump written by a newer `pg_dump`
  cannot be read by an older `pg_restore`.

## Secrets

Set on the `prod` GitHub environment, the same one the ingest workflow uses.

- Reused (already set): `DB_HOST`, `DB_USER`, `DB_PASS`, `R2_ACCOUNT_ID`. `DB_PORT` and
  `DB_NAME` are not secrets and are written into the workflow.
- New: `R2_BACKUP_ACCESS_KEY_ID` and `R2_BACKUP_SECRET_ACCESS_KEY`, an R2 token scoped to
  Object Read & Write on `regrag-db-backups` alone. The raw-docs token is deliberately not
  reused — neither bucket's credentials should reach the other.
- `R2_BUCKET` (`regrag-db-backups`) is non-sensitive config, written into the workflow.
  `restore.sh` still reads it from env, for manual restores.

## Manual backup

The nightly workflow sets every required variable itself, so this is only for ad-hoc runs
from a laptop. `backup.sh` reads its connection from `DB_*`, and `backend/.env.prod` /
`.env.dev` already hold exactly those, so source the one you want:

```bash
set -a; source backend/.env.prod; set +a
R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
  R2_BUCKET=regrag-db-backups \
  bash scripts/db/backup.sh
```

Notes:

- The filename carries `ENVIRONMENT` (`regrag-prod-…`, `regrag-dev-…`), which defaults to
  `prod`. Set `ENVIRONMENT=dev` when dumping anything else, so the file cannot be mistaken
  for a prod backup.
- The `.env.*` files hold the raw-docs R2 credentials, not the backup ones. Pass the
  backup token inline as above.
- For a local dump with no upload, into the working directory:
  `UPLOAD=false ENVIRONMENT=dev bash scripts/db/backup.sh`.

## A psql prompt

`scripts/db/psql.sh` connects with the same variables and the same TLS rules as the backup,
so an ad-hoc query needs no hand-translated flags. Sessions are **read-only** unless you pass
`WRITABLE=1` — the chat ledger is the one table nothing can rebuild.

```bash
set -a; source backend/.env.prod; set +a
scripts/db/psql.sh
scripts/db/psql.sh -c 'select count(*) from chat_requests'
```

Any psql argument passes straight through, and the banner naming the host, database and
sslmode goes to stderr, so `-c` output stays pipeable.

## List available backups

```bash
aws s3 ls s3://regrag-db-backups/daily/ --region auto \
  --endpoint-url "https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"
```

## Restore

These steps round-trip a dev dump through the compose database, but have not been
exercised against a real prod dump — expect to debug them the first time.

Restore is **destructive** and never targets prod by default — restore into a fresh
database, verify it, then promote. `restore.sh` asks you to type the target database name
to confirm, which `FORCE=1` skips in automation.

The target must be a Postgres with pgvector available, because the dump recreates the
extension. The compose `db` service is one:

```bash
docker compose -f backend/compose.yaml up -d db
PGPASSWORD=postgres createdb -h 127.0.0.1 -p 5432 -U postgres regrag_restore_test

# The latest backup (the usual case — no flag needed):
R2_ACCOUNT_ID=... R2_ACCESS_KEY_ID=... R2_SECRET_ACCESS_KEY=... \
  R2_BUCKET=regrag-db-backups \
  bash scripts/db/restore.sh

# Or one particular backup, with the same R2_* variables:
#   bash scripts/db/restore.sh --key daily/regrag-prod-YYYYMMDD-HHMMSS.dump
# Or a local dump file, needing no R2 access at all:
#   bash scripts/db/restore.sh --file /path/to/regrag-prod-*.dump
```

Override the target with `TARGET_DB_HOST`, `TARGET_DB_PORT`, `TARGET_DB_USER`,
`TARGET_DB_PASS` and `TARGET_DB_NAME`.

Check what came back before trusting it:

```bash
PGPASSWORD=postgres psql -h 127.0.0.1 -p 5432 -U postgres -d regrag_restore_test \
  -c "select count(*) from chat_requests" \
  -c "select count(*) from document_chunks where embedding is not null"
```
