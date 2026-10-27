#!/bin/sh
# Put back a backup made by backup.sh. Run from the repository root.
#
#   sh deploy/restore.sh backups/db-<stamp>.sql.gz[.gpg] [backups/video-<stamp>.tar.gz[.gpg]]
#
# On a new server, or after losing the data, the database must be running and empty, and the API
# must not have started yet (it makes the tables when it starts, and a restore into tables that
# already exist fails):
#   docker compose -f docker-compose.prod.yml up -d db
#   sh deploy/restore.sh backups/db-<stamp>.sql.gz backups/video-<stamp>.tar.gz
#   docker compose -f docker-compose.prod.yml up -d
#
# A name ending in .gpg is an encrypted backup (see backup.sh). Restoring it needs the PRIVATE key in
# this machine's gpg keyring (gpg --import), and asks for its passphrase if it has one.
#
# It refuses a database that already has tables. To replace a live one, stop the API and the worker
# and recreate the database first (this deletes what is in it):
#   docker compose -f docker-compose.prod.yml stop api worker
#   docker compose -f docker-compose.prod.yml exec db psql -U integrity -d postgres \
#     -c "DROP DATABASE integrity" -c "CREATE DATABASE integrity OWNER integrity"
set -eu
COMPOSE="docker compose -f docker-compose.prod.yml"

if [ $# -lt 1 ] || [ $# -gt 2 ]; then
  echo "usage: sh deploy/restore.sh backups/db-<stamp>.sql.gz[.gpg] [backups/video-<stamp>.tar.gz[.gpg]]" >&2
  exit 2
fi
DB_FILE=$1
VIDEO_FILE=${2:-}

# The archive's own bytes: decrypted first when it is a .gpg file.
plain() {
  case "$1" in
    *.gpg) gpg --quiet --decrypt "$1" ;;
    *) cat "$1" ;;
  esac
}

for file in "$DB_FILE" ${VIDEO_FILE:+"$VIDEO_FILE"}; do
  [ -f "$file" ] || { echo "no such file: $file" >&2; exit 2; }
  plain "$file" | gzip -t 2>/dev/null \
    || { echo "$file is damaged, or this machine has no key that opens it: not restoring from it" >&2; exit 2; }
done

tables=$($COMPOSE exec -T db psql -U integrity -d integrity -tAc \
  "select count(*) from information_schema.tables where table_schema = 'public'")
if [ "$tables" != "0" ]; then
  echo "the database already has $tables tables, so nothing was changed." >&2
  echo "To replace it, see the top of this file." >&2
  exit 1
fi

# all or nothing: a restore that stops half way leaves the database empty, not half full
plain "$DB_FILE" | gunzip -c | $COMPOSE exec -T db psql -U integrity -d integrity -q -1 -v ON_ERROR_STOP=1 >/dev/null
echo "database restored from $DB_FILE"

if [ -n "$VIDEO_FILE" ]; then
  plain "$VIDEO_FILE" | gunzip -c | $COMPOSE run --rm --no-deps -T api tar -C /data -xf -
  echo "recordings restored from $VIDEO_FILE"
fi
