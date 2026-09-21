# Database backups

PlanetScale's own backups of the `hecla-em` cluster are the first thing to restore from. This
nightly copy in R2 exists so that losing the PlanetScale account or cluster does not take the
backups with it.

## What runs

`.github/workflows/backup.yml` runs `uv run db backup` daily at 02:00 UTC. It writes a
`pg_dump` of the whole `regrag` database to `daily/regrag-prod-<timestamp>.dump` in the
`regrag-db-backups` bucket, which deletes objects after 30 days by a lifecycle rule set in
Cloudflare. Each run checks in with Sentry as `nightly-backup`, so a night that fails or never
starts raises an issue.

The upload uses the same R2 credentials as the raw documents, pointed at `BACKUP_BUCKET`, so
that token must cover both buckets. `pg_dump` needs the direct port 5432, not a pooler.

For a dump on your own machine: `uv run db backup --no-upload`, with `ENVIRONMENT=prod` to
read `.env.prod`. `uv run db shell` opens psql the same way, read-only unless `--writable`.

## Restore

`uv run db restore` fetches the newest prod dump from `BACKUP_BUCKET` and runs `pg_restore` into
the configured database, which must exist and be empty. That is the recovery path: point
`.env.prod` at a new cluster with pgvector, then run it with `ENVIRONMENT=prod`.

It restores in one transaction, so a database that already holds the tables makes it fail and
roll back. It cannot overwrite one.

To rehearse on the compose `db` service, name another database. A dump argument picks an
older dump by name, or a local file:

```bash
uv run db shell --writable -c "create database regrag_restored"
uv run db restore --database regrag_restored
uv run db shell -d regrag_restored -c "select count(*) from chat_requests"
```
