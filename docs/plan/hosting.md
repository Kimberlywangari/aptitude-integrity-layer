# Hosting on the Cytonn-provided server

Status, 24 Oct 2026. Everything below is ready in the repository; nothing has been deployed. I can
do the deployment over SSH once you give me access and say go. Until then this is the runbook.

## What runs

`docker-compose.prod.yml` starts five containers on one machine:

| Container | Job | Reachable from outside |
|-----------|-----|------------------------|
| `proxy` (Caddy) | HTTPS on ports 80 and 443, gets and renews the certificate | yes, the only one |
| `web` (nginx) | serves the built app, passes `/api` to the API | no |
| `api` (FastAPI) | the test, the log, flags, review, admin | no |
| `worker` | hourly housekeeping: delete video that is due, note unfinished uploads | no |
| `db` (Postgres 16) | all data | no |

Two Docker volumes hold the data: `pgdata` (database) and `videodata` (recordings). The camera only
works over HTTPS, which is why the proxy is part of the stack.

## What I need from you

1. **SSH access** to the server (user, address, key), and whether it has `sudo`.
2. **A host name** that points at the server, for example `aptitude.cytonn.com`, and ports 80 and 443
   open to the internet. Without public ports 80 and 443 Caddy cannot get a free certificate. In that
   case Cytonn's IT gives you a certificate and key file instead (see the top of `deploy/Caddyfile`).
3. **Docker and the Compose plugin** on the server. If missing, I install them (Ubuntu: the official
   Docker apt repository).
4. **Disk space.** Video is about 80 MB an hour per candidate at most. 100 candidates of 40 minutes
   is about 5 GB. Retention deletes video after 30 days.
5. **Cytonn's API key** for the question bank (`APTITUDE_API_KEY`), and, if you want AI, a Claude key
   (see `ai-provider-switch.md`).
6. **Who may reach the console.** Staff sign-in is by password. To limit it to Cytonn's network, ask
   their IT for the public address or range (and any VPN) staff leave from; it goes in `.env` as
   `STAFF_ALLOWED_IPS` (see "Locking the staff console" below). Until it is known the console is open to
   everybody.
7. **Whether backups are encrypted, and where the copies go.** See "Backups" and "Encrypted backups"
   below. A key has to be made and its private half kept somewhere other than the server.

## Steps

On the server, in a folder such as `/srv/aptitude`:

1. Get the code there (`git clone` of the repository, or a copy).
2. `cp .env.example .env` and fill in, **at minimum**:
   ```
   ENV=production
   PUBLIC_BASE_URL=https://aptitude.cytonn.com
   SITE_ADDRESS=aptitude.cytonn.com
   SESSION_SECRET=<48+ random characters>
   POSTGRES_PASSWORD=<letters and digits only, 24+ characters>
   APTITUDE_API_KEY=<Cytonn's key>
   ```
   Make the two secrets with `openssl rand -hex 32`. The API refuses to start if the secret is short,
   still the default, or the address is not `https://`.
3. `docker compose -f docker-compose.prod.yml up -d --build`. The first build takes a few minutes.
   The database is migrated by the API on start.
4. Load the question bank:
   `docker compose -f docker-compose.prod.yml exec api python -m scripts.jobs fetch_cytonn_bank`
5. Create the first admin (it asks for a password):
   `docker compose -f docker-compose.prod.yml exec api python -m scripts.jobs create_reviewer --email <address> --role admin`
6. Open `https://aptitude.cytonn.com/admin/login`, sign in, make a sitting, and run one test yourself
   in Chrome or Edge, with camera and microphone.
7. Check: `docker compose -f docker-compose.prod.yml ps` shows every container `healthy` or `running`.

## Backups

`sh deploy/backup.sh` writes a dated database dump and a recordings archive into `./backups`, checks
both, and keeps the last 14. Run it nightly from cron (`0 2 * * * cd /srv/aptitude && sh deploy/backup.sh`)
and copy `./backups` off the machine (ask Cytonn where: their backup server, another host by `rsync`, or
object storage; nothing copies them for you).

**Restoring** (new server, or after losing the data): `up -d db`, then
`sh deploy/restore.sh backups/db-<stamp>.sql.gz backups/video-<stamp>.tar.gz`, then `up -d`. The
database must be empty (the API makes the tables when it starts, so it must not have run yet); the
script refuses otherwise, and its first lines say how to replace a live database. Do not use a bare
`gunzip | psql` into a database that already has tables: it fails part way.
Rehearsed 26 Oct 2026 on a throwaway copy of this stack: backup, delete all containers and volumes,
restore, start. 23 of 23 tables had the same row counts; a recording matched byte for byte. Not yet
rehearsed on the real server: do it once there before the first sitting.

## Locking the staff console to Cytonn's network

Ask Cytonn's IT for the public address or range their staff (and any VPN) leave the building from.
Then put it in `.env` as `STAFF_ALLOWED_IPS="203.0.113.0/24 198.51.100.7"` (space-separated) and run
`docker compose -f docker-compose.prod.yml up -d proxy`. From other addresses the console and its API
answer 403; candidates are untouched. Until the address is known, leave it empty (everybody). Test it
from a staff computer straight away. If the server sits behind another proxy, the address Caddy sees is
the proxy's, and `deploy/Caddyfile` needs `client_ip` with `trusted_proxies` (see its comment).

## Encrypted backups

Make a key on your own computer, put only the public half on the server, and set
`BACKUP_GPG_RECIPIENT` in `.env` (steps: README, "Backups, restoring, and knowing when it is down").
Keep the private key and a copy of it off the server. Restoring needs it. `sh deploy/check.sh` drills
the encrypt and decrypt steps against a throwaway key, but the encrypted path has **not** been
rehearsed on a whole stack: do it once on the real server (back up, wipe a copy, restore) before
relying on it. Backups made before encryption was switched on stay unencrypted until they rotate out.

## Knowing when it breaks

- Point a free uptime monitor (UptimeRobot or similar) at `https://<host>/api/health`, checking for the
  text `"status":"ok"`, every 1 to 5 minutes, alerting an email address that someone reads during a
  sitting. It fails if the API or database is down. Under 10 GB free where recordings are kept it says
  `"status":"low_disk"` (still HTTP 200), so the keyword check is what catches it.
- The staff Overview page shows "Recordings disk" under System checks.
- Video is about 80 MB an hour per candidate; the 10 GB threshold is about 125 candidate-hours.

## After the sitting closes

The admin presses **Prepare for review** on the sitting's page once recordings have finished arriving
(up to 48 hours after the test). Until then reviewers see the rule order only. It can be repeated.

## Updating

`git pull`, then `docker compose -f docker-compose.prod.yml up -d --build`. Migrations run on start.
Take a backup first.

## Things to know

- **Only the proxy is public.** The database, API and web containers have no published ports.
- **Candidate addresses.** nginx trusts the proxy's `X-Forwarded-For` (`deploy/real-ip.conf`) so each
  candidate has their own wrong-code limit and not one shared limit.
- **Clock.** Time always comes from the server. Keep the server on NTP.
- **AI.** With no key and no Ollama on the server, set `AI_PROVIDER=rules` and sittings use the
  Cytonn bank. AI-written questions need Claude (or Ollama on the host).
- **Logs.** `docker compose -f docker-compose.prod.yml logs -f api`.
- **Stopping.** `docker compose -f docker-compose.prod.yml down` keeps the data. Adding `-v` deletes it.
