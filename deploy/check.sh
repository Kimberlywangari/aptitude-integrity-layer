#!/bin/sh
# Checks the two parts of deploy/ that a wrong edit would break without anyone noticing:
#   1. the staff lock in the Caddyfile, run against the pinned Caddy image;
#   2. the encrypt and decrypt steps of backup.sh and restore.sh, run against a throwaway key.
# Needs docker, curl and gpg. It changes nothing outside a temp folder and one short-lived container.
#
#   sh deploy/check.sh        (from the repository root or anywhere; CHECK_PORT=8099 is the test port)
set -u
cd "$(dirname "$0")/.."
PORT=${CHECK_PORT:-8099}
FAILED=0
ROOT=$(pwd)
WORK=$(mktemp -d)

ok() { echo "  ok    $1"; }
bad() { echo "  FAIL  $1"; FAILED=1; }

cleanup() {
  cd "$ROOT" || true # Windows cannot delete the folder it is standing in
  docker rm -f aptitude-check-caddy >/dev/null 2>&1
  GNUPGHOME="$WORK/gnupg" gpgconf --kill all >/dev/null 2>&1
  rm -rf "$WORK"
}
trap cleanup EXIT

for tool in docker curl gpg; do
  command -v "$tool" >/dev/null || { echo "$tool is needed for this check" >&2; exit 2; }
done

# ---- 1. staff lock ---------------------------------------------------------------------------------
IMAGE=$(grep -o 'caddy:2-alpine@sha256:[0-9a-f]*' docker-compose.prod.yml | head -n 1)
CADDYFILE="$(pwd -W 2>/dev/null || pwd)/deploy/Caddyfile"
STAFF_PATHS="/api/review/outcomes /api/admin/sittings /admin /review /overview /outcomes /login/admin /login/reviewer"
CANDIDATE_PATHS="/ /precheck /api/events /api/session/x/image/y"

# 403 is the lock. Anything else means the lock let the request through to the web container, which
# is not running here, so it is a 502 or a timeout (000).
probe() { # $1 = path
  curl -s -o /dev/null --max-time 2 -w '%{http_code}' "http://localhost:$PORT$1"
}

start_caddy() { # $1 = STAFF_ALLOWED_IPS
  docker rm -f aptitude-check-caddy >/dev/null 2>&1
  MSYS_NO_PATHCONV=1 docker run -d --name aptitude-check-caddy -p "$PORT:$PORT" \
    -e "SITE_ADDRESS=:$PORT" -e "STAFF_ALLOWED_IPS=$1" -v "$CADDYFILE:/etc/caddy/Caddyfile:ro" \
    "$IMAGE" >/dev/null || return 1
  sleep 4
}

echo "staff lock ($IMAGE)"
if start_caddy "203.0.113.0/24"; then
  for p in $STAFF_PATHS; do
    [ "$(probe "$p")" = "403" ] && ok "closed from another network: $p" || bad "$p was not closed"
  done
  for p in $CANDIDATE_PATHS; do
    [ "$(probe "$p")" != "403" ] && ok "candidates unaffected: $p" || bad "$p was closed to candidates"
  done
else
  bad "could not start Caddy"
fi
if start_caddy "0.0.0.0/0 ::/0"; then
  for p in $STAFF_PATHS; do
    [ "$(probe "$p")" != "403" ] && ok "open by default: $p" || bad "$p closed although the list is everybody"
  done
else
  bad "could not start Caddy"
fi

# ---- 2. encrypted backups --------------------------------------------------------------------------
# seal() and plain() are cut out of the real scripts, so this tests the code that runs on the server.
echo "encrypted backups"
mkdir -p "$WORK/gnupg" "$WORK/backups"
chmod 700 "$WORK/gnupg"
export GNUPGHOME="$WORK/gnupg"
gpg --batch --pinentry-mode loopback --passphrase '' --quick-generate-key "check <check@example.com>" \
  default default never >/dev/null 2>&1 || { bad "could not make a throwaway key"; exit 1; }
awk '/^seal\(\) \{/,/^\}/' deploy/backup.sh > "$WORK/seal.sh"
awk '/^plain\(\) \{/,/^\}/' deploy/restore.sh > "$WORK/plain.sh"
[ -s "$WORK/seal.sh" ] && [ -s "$WORK/plain.sh" ] || { bad "seal() or plain() not found in the scripts"; exit 1; }
. "$WORK/seal.sh"
. "$WORK/plain.sh"

cd "$WORK" || exit 1
RECIPIENT=check@example.com
printf 'select 1;\n' | gzip > expected.gz
cp expected.gz backups/db.sql.gz
seal backups/db.sql.gz
[ ! -e backups/db.sql.gz ] && [ -s backups/db.sql.gz.gpg ] && ok "seal keeps only the .gpg" || bad "seal left the plain file"
plain backups/db.sql.gz.gpg > got.gz 2>/dev/null
cmp -s expected.gz got.gz && ok "restore reads back the same bytes" || bad "decrypted bytes differ"
head -c 100 backups/db.sql.gz.gpg > backups/damaged.sql.gz.gpg
plain backups/damaged.sql.gz.gpg 2>/dev/null | gzip -t 2>/dev/null \
  && bad "a damaged archive passed the check" || ok "a damaged archive is refused"
cp expected.gz backups/plain.sql.gz
plain backups/plain.sql.gz | gzip -t && ok "an unencrypted archive still restores" || bad "plain archive failed"
cp expected.gz backups/nokey.sql.gz
RECIPIENT=nobody@example.com
( seal backups/nokey.sql.gz ) >/dev/null 2>&1 && bad "seal succeeded without the key" || ok "a missing key fails"
ls backups/nokey.sql.gz* >/dev/null 2>&1 && bad "a failed seal left files" || ok "a failed seal leaves nothing"

[ "$FAILED" = 0 ] && echo "all checks passed" || echo "SOME CHECKS FAILED"
exit "$FAILED"
