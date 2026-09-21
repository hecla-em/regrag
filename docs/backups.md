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

Not yet rehearsed against a real prod dump. Restore into a fresh database on a Postgres with
pgvector (the compose `db` service is one), check it, and only then point anything at it.

```bash
aws s3 cp s3://regrag-db-backups/daily/<dump> . --region auto \
  --endpoint-url "https://$R2_ACCOUNT_ID.r2.cloudflarestorage.com"

createdb -h 127.0.0.1 -U postgres regrag_restored
pg_restore -h 127.0.0.1 -U postgres -d regrag_restored --no-owner --no-privileges <dump>

psql -h 127.0.0.1 -U postgres -d regrag_restored -c "select count(*) from chat_requests"
```

`aws s3 ls s3://regrag-db-backups/daily/` with the same two flags lists what is there. The
`aws` commands need `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY` set to the R2 token.
