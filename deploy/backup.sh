#!/bin/sh
# A dated copy of the database and the recordings, kept in ./backups. Run from the repository root:
#   sh deploy/backup.sh        (cron: 0 2 * * * cd /srv/aptitude && sh deploy/backup.sh)
# Copy ./backups somewhere off this machine as well; a backup on the same disk is not a backup.
# To put one back: deploy/restore.sh.
#
# Encrypting. The dumps hold candidates' names and addresses, and the recordings hold their faces and
# voices. Set BACKUP_GPG_RECIPIENT (a key id or address in this machine's gpg keyring; in the
# environment or in .env) and every archive is stored encrypted for that key alone (*.gpg), so a
# copy that leaves the machine, or a lost disk, shows nothing. Only the PUBLIC half of the key belongs
# on this machine. The private half is what restores the backups: keep it, and a copy, somewhere safe,
# because without it they cannot be opened. If the key is asked for but missing, nothing is written.
set -eu
COMPOSE="docker compose -f docker-compose.prod.yml"
STAMP=$(date +%Y%m%d-%H%M%S)

RECIPIENT=${BACKUP_GPG_RECIPIENT:-}
if [ -z "$RECIPIENT" ] && [ -f .env ]; then
  RECIPIENT=$(sed -n 's/^BACKUP_GPG_RECIPIENT=//p' .env | tail -n 1 | tr -d '\r' | tr -d "\"'")
fi
if [ -n "$RECIPIENT" ]; then
  command -v gpg >/dev/null || { echo "BACKUP_GPG_RECIPIENT is set but gpg is not installed" >&2; exit 1; }
  gpg --batch --list-keys "$RECIPIENT" >/dev/null 2>&1 \
    || { echo "gpg has no key for $RECIPIENT: import the public key first" >&2; exit 1; }
fi

# Encrypts a finished archive in place when a recipient is set; the plain file never stays behind.
seal() {
  [ -n "$RECIPIENT" ] || return 0
  gpg --batch --yes --trust-model always --encrypt --recipient "$RECIPIENT" --output "$1.gpg" "$1" \
    || { rm -f "$1" "$1.gpg"; echo "encrypting $1 failed; nothing was kept" >&2; exit 1; }
  rm -f "$1"
}

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
seal "backups/db-$STAMP.sql.gz"
seal "backups/video-$STAMP.tar.gz"

# keep the last 14 of each
for kind in db video; do ls -1t backups/$kind-* 2>/dev/null | tail -n +15 | xargs -r rm -f; done
echo "backed up to backups/*-$STAMP.*${RECIPIENT:+ (encrypted for $RECIPIENT)}"
