# OCI Production Runbook

This runbook sets up Pokeleximon on a single Oracle Cloud Always Free VM using Docker Compose and server-local secrets.

## Security Rules

- Keep runtime secrets only on the VM under `/opt/pokeleximon/secrets`.
- Use `root:root` ownership and `0600` permissions for secret files.
- Do not commit copied env files.
- Do not place runtime secrets in GitHub Actions, workflow YAML, build args, or `.env.example`.
- Do not use `VITE_ADMIN_API_TOKEN` in production builds.
- Protect `/admin` and `/api/v1/admin/*` with reverse-proxy basic auth and the API admin token.

## Server Layout

Persistent paths:

- `/opt/pokeleximon/app`
- `/opt/pokeleximon/app/releases`
- `/opt/pokeleximon/app/current`
- `/opt/pokeleximon/backups`
- `/opt/pokeleximon/data/postgres`
- `/opt/pokeleximon/data/redis`
- `/opt/pokeleximon/data/artifacts`
- `/opt/pokeleximon/data/caddy/data`
- `/opt/pokeleximon/data/caddy/config`
- `/opt/pokeleximon/secrets`

## First Boot

1. Install Docker Engine, Docker Compose plugin, `curl`, and `tar`.
2. Open inbound ports `80` and `443`.
3. Create directories:

```bash
sudo bash infra/production/oci/bin/bootstrap_host.sh /opt/pokeleximon
```

4. Copy non-secret deploy config:

```bash
sudo cp infra/production/oci/env/deploy.env.template /opt/pokeleximon/app/deploy.env
sudo cp infra/production/oci/env/web.env.template /opt/pokeleximon/app/web.env
sudo chmod 0644 /opt/pokeleximon/app/deploy.env /opt/pokeleximon/app/web.env
```

5. Create the API secret file from the template:

```bash
sudo bash infra/production/oci/bin/create_secrets.sh --root /opt/pokeleximon
```

6. Edit `/opt/pokeleximon/app/deploy.env` and set:
   - `SITE_HOST`
   - any non-secret frontend build overrides you want
7. Edit `/opt/pokeleximon/secrets/api.env` and fill only the optional values that were intentionally left blank, such as:
   - `SENTRY_DSN`
   - `ALERT_WEBHOOK_URL`

Important:

- `DATABASE_URL` must continue to point to `db` as the hostname.
- `REDIS_URL` must continue to point to `redis` as the hostname.
- `PUBLISH_ON_STARTUP` stays `false` in production.
- The generated admin token, proxy username/password, and Postgres password are not printed by the helper script.
- Operator-only access values are stored in `/opt/pokeleximon/secrets/admin_access.txt`.
- The reverse proxy reads `/opt/pokeleximon/secrets/proxy.env`.

## GitHub Actions Secrets

Add only these repository secrets:

- `OCI_DEPLOY_HOST`
- `OCI_DEPLOY_USER`
- `OCI_DEPLOY_SSH_KEY`

These are deployment-access secrets, not runtime application secrets.

The deploy user should have:

- SSH key access
- permission to run Docker
- passwordless `sudo` for the deploy script, or full passwordless `sudo`

## Deploy

Deploys are performed by the GitHub Actions workflow in `.github/workflows/deploy-oci.yml`.

Manual equivalent:

```bash
tar -czf /tmp/pokeleximon-release.tgz .
scp /tmp/pokeleximon-release.tgz deploy@your-host:/tmp/pokeleximon-release.tgz
scp infra/production/oci/bin/deploy_remote.sh deploy@your-host:/tmp/deploy_remote.sh
ssh deploy@your-host "chmod 755 /tmp/deploy_remote.sh && sudo /tmp/deploy_remote.sh --release-archive /tmp/pokeleximon-release.tgz --release-id manual-$(date +%Y%m%d%H%M%S)"
```

The deploy script:

- extracts a release into `/opt/pokeleximon/app/releases/<release-id>`
- repoints `/opt/pokeleximon/app/current`
- starts Postgres and Redis
- runs Alembic migrations
- rebuilds and restarts the stack
- verifies API health and same-origin proxy routing

Before the first deploy, and after any secret rotation, run:

```bash
sudo bash /opt/pokeleximon/app/current/infra/production/oci/bin/preflight.sh --root /opt/pokeleximon
```

## Rollback

1. List previous releases:

```bash
ls -1 /opt/pokeleximon/app/releases
```

2. Repoint `current` to the prior release:

```bash
sudo ln -sfn /opt/pokeleximon/app/releases/<previous-release-id> /opt/pokeleximon/app/current
```

3. Restart the stack:

```bash
sudo docker compose --env-file /opt/pokeleximon/app/deploy.env \
  -f /opt/pokeleximon/app/current/infra/production/oci/docker-compose.prod.yml \
  up -d --build
```

4. Verify health:

```bash
curl -kfsS --resolve "your-domain.example:443:127.0.0.1" https://your-domain.example/health
```

## Backup

Nightly backup command:

```bash
sudo /opt/pokeleximon/bin/backup_postgres.sh /opt/pokeleximon
```

Recommended crontab entry:

```cron
15 2 * * * /opt/pokeleximon/bin/backup_postgres.sh /opt/pokeleximon >> /var/log/pokeleximon-backup.log 2>&1
```

Backups are written to `/opt/pokeleximon/backups` and rotated locally after 14 days.

## Restore

Restore is destructive. Use only with a known-good dump.

```bash
sudo /opt/pokeleximon/bin/restore_postgres.sh \
  --input /opt/pokeleximon/backups/postgres_YYYYMMDDTHHMMSSZ.sql.gz \
  --root /opt/pokeleximon \
  --yes
```

After restore, verify:

- `/health`
- `/api/v1/puzzles/daily?gameType=crossword`
- admin reserve status

## Secret Rotation

To rotate the admin token or DB credentials:

1. Edit `/opt/pokeleximon/secrets/api.env`
2. Restart the affected services:

```bash
sudo docker compose --env-file /opt/pokeleximon/app/deploy.env \
  -f /opt/pokeleximon/app/current/infra/production/oci/docker-compose.prod.yml \
  up -d --build api db
```

3. Verify:

```bash
curl -kfsS --resolve "your-domain.example:443:127.0.0.1" https://your-domain.example/health
```

4. Invalidate any old admin token copies held by operators.

If you want to regenerate the admin token and DB password together, run:

```bash
sudo bash /opt/pokeleximon/app/current/infra/production/oci/bin/create_secrets.sh --root /opt/pokeleximon --force
sudo bash /opt/pokeleximon/app/current/infra/production/oci/bin/preflight.sh --root /opt/pokeleximon
```

Admin access is now layered:

1. Reverse-proxy basic auth gates `/admin` and `/api/v1/admin/*`
2. The admin UI still requires the API admin token for admin requests

That means public users do not see an admin link, cannot browse to admin without proxy credentials, and still cannot call admin APIs without the separate token.

## Monthly Maintenance

- Apply OS package updates.
- Update Docker Engine and Compose plugin on a controlled cadence.
- Review free disk space under `/opt/pokeleximon`.
- Confirm backups exist and are restorable.
- Review old releases and prune if needed.
