#!/bin/sh
# A dated copy of the database and the recordings, kept in ./backups. Run from the repository root:
#   sh deploy/backup.sh        (cron: 0 2 * * * cd /srv/aptitude && sh deploy/backup.sh)
# Copy ./backups somewhere off this machine as well; a backup on the same disk is not a backup.
set -eu
COMPOSE="docker compose -f docker-compose.prod.yml"
STAMP=$(date +%Y%m%d-%H%M%S)
mkdir -p backups
$COMPOSE exec -T db pg_dump -U integrity integrity | gzip > "backups/db-$STAMP.sql.gz"
$COMPOSE exec -T api tar -C /data -cf - video | gzip > "backups/video-$STAMP.tar.gz"
# keep the last 14 of each
for kind in db video; do ls -1t backups/$kind-* 2>/dev/null | tail -n +15 | xargs -r rm -f; done
echo "backed up to backups/*-$STAMP.*"
