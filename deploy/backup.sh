#!/bin/sh
# A dated copy of the database and the recordings, kept in ./backups. Run from the repository root:
#   sh deploy/backup.sh        (cron: 0 2 * * * cd /srv/aptitude && sh deploy/backup.sh)
# Copy ./backups somewhere off this machine as well; a backup on the same disk is not a backup.
# To put one back: deploy/restore.sh.
set -eu
COMPOSE="docker compose -f docker-compose.prod.yml"
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p backups

# Each is written to a file first and checked, not piped into gzip: in plain sh a failing pg_dump
# at the front of a pipe is not noticed, and the result is an empty archive and a "backed up" line.
$COMPOSE exec -T db pg_dump -U integrity integrity > "backups/db-$STAMP.sql"
if ! tail -n 5 "backups/db-$STAMP.sql" | grep -q "PostgreSQL database dump complete"; then
  rm -f "backups/db-$STAMP.sql"
  echo "the database dump did not finish; nothing was kept" >&2
  exit 1
fi
gzip "backups/db-$STAMP.sql"

$COMPOSE exec -T api tar -C /data -cf - video > "backups/video-$STAMP.tar"
gzip "backups/video-$STAMP.tar"

gzip -t "backups/db-$STAMP.sql.gz" "backups/video-$STAMP.tar.gz"

# keep the last 14 of each
for kind in db video; do ls -1t backups/$kind-* 2>/dev/null | tail -n +15 | xargs -r rm -f; done
echo "backed up to backups/*-$STAMP.*"
