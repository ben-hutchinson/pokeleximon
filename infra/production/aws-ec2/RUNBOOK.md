# AWS EC2 Production Runbook

This runbook deploys Pokeleximon to a single Ubuntu 24.04 EC2 host using Docker Compose, server-local secrets, S3-backed puzzle artifacts, and optional S3 backup uploads.

## Platform Shape

- Region: `eu-west-2`
- Instance: `t3.small`
- Storage: one gp3 EBS volume
- Runtime: `Caddy + web + api + postgres + redis + Prometheus + Grafana + exporters` on one host
- DNS: point your registrar-managed `A` record at the EC2 public IPv4
- Artifact storage: S3 via `ARTIFACT_STORAGE_BACKEND=s3`
- Monitoring access: Grafana, Prometheus, and Alertmanager bind to `127.0.0.1` only and are reached through SSH tunneling

Important:

- AWS Free Plan lasts 6 months. If the account was created on March 11, 2026, upgrade before September 11, 2026 or the account can auto-close.
- Public IPv4 is billed separately on AWS, so keep the stack on one EC2 host in v1.
- Prefer an EC2 instance profile for S3 access. Leave static S3 credentials blank unless you have no alternative.

## Security Rules

- Keep runtime secrets only on the host under `/opt/pokeleximon/secrets`.
- Use `root:root` ownership and `0600` permissions for secret files.
- Do not commit copied env files.
- Do not place runtime secrets in GitHub Actions, workflow YAML, build args, or `.env.example`.
- Do not use `VITE_ADMIN_API_TOKEN` in production builds.
- Protect `/admin` and `/api/v1/admin/*` with reverse-proxy basic auth and the API admin token.

## AWS Prerequisites

1. Create the EC2 instance in `eu-west-2`:
   - Ubuntu 24.04 LTS
   - `t3.small`
   - attach gp3 storage
2. Attach an instance profile with S3 permissions for:
   - the artifact bucket in `ARTIFACT_S3_BUCKET`
   - the backup prefix in `BACKUP_S3_URI`
3. Create buckets:
   - one artifact bucket, for example `pokeleximon-prod-artifacts`
   - one backup bucket/prefix, for example `s3://pokeleximon-prod-backups/postgres`
4. Configure the security group:
   - allow inbound `80/tcp`
   - allow inbound `443/tcp`
   - restrict `22/tcp` to your IP and/or GitHub Actions deploy path
   - do not open `3000/tcp`, `9090/tcp`, or `9093/tcp`; monitoring stays loopback-only
5. Enable AWS Budget, billing alerts, and Free Plan/credit reviews.

## Server Layout

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

Monitoring persistence uses Docker named volumes:

- `pokeleximon-aws-prod_prometheus-data`
- `pokeleximon-aws-prod_grafana-data`

## First Boot

1. Install Docker Engine, Docker Compose plugin, `curl`, `tar`, and AWS CLI.
2. Create directories:

```bash
sudo bash infra/production/aws-ec2/bin/bootstrap_host.sh /opt/pokeleximon
```

3. Copy non-secret deploy config:

```bash
sudo cp infra/production/aws-ec2/env/deploy.env.template /opt/pokeleximon/app/deploy.env
sudo cp infra/production/aws-ec2/env/web.env.template /opt/pokeleximon/app/web.env
sudo chmod 0644 /opt/pokeleximon/app/deploy.env /opt/pokeleximon/app/web.env
```

4. Create the server-local secret files:

```bash
sudo bash infra/production/aws-ec2/bin/create_secrets.sh --root /opt/pokeleximon
```

For `t3.micro` or other 1 GiB hosts, add swap before starting the full stack:

```bash
sudo bash infra/production/aws-ec2/bin/configure_swap.sh --size 2G
```

5. Edit `/opt/pokeleximon/app/deploy.env` and set:
   - `SITE_HOST`
   - `SITE_ADDRESS`
   - `AWS_REGION`
   - `BACKUP_S3_URI`
6. Edit `/opt/pokeleximon/secrets/api.env` and fill any intentionally blank optional values:
   - `SENTRY_DSN`
   - `ALERT_WEBHOOK_URL`
   - `ALERTMANAGER_WEBHOOK_URL` in `/opt/pokeleximon/secrets/monitoring.env` if you want Prometheus alerts delivered externally
   - `ARTIFACT_S3_BUCKET`
   - `ARTIFACT_PUBLIC_BASE_URL` if needed later

Important:

- `SITE_ADDRESS` should include the scheme. Use `https://your-domain.example` for a real domain.
- For first boot without DNS, you can temporarily use `SITE_HOST=<public-ip>` and `SITE_ADDRESS=http://<public-ip>`.
- `DATABASE_URL` must continue to use `db` as the hostname.
- `REDIS_URL` must continue to use `redis` as the hostname.
- `PUBLISH_ON_STARTUP` stays `false` in production.
- `POKEAPI_REFRESH_ENABLED` stays `false` on EC2.
- `PROMETHEUS_RETENTION_TIME=3d` is a better default for low-memory single-host setups.
- `REDIS_MAXMEMORY=128mb` keeps cache growth bounded on small instances.
- Operator-only access values, including Grafana login, are stored in `/opt/pokeleximon/secrets/admin_access.txt`.
- The reverse proxy reads `/opt/pokeleximon/secrets/proxy.env`.
- Grafana reads `/opt/pokeleximon/secrets/monitoring.env`.

## GitHub Actions Secrets

Add only these repository secrets:

- `AWS_EC2_DEPLOY_HOST`
- `AWS_EC2_DEPLOY_USER`
- `AWS_EC2_DEPLOY_SSH_KEY`

These are deployment-access secrets, not runtime application secrets.

## Deploy

Deploys are performed by `.github/workflows/deploy-aws-ec2.yml`.

Manual equivalent:

```bash
tar -czf /tmp/pokeleximon-release.tgz .
scp /tmp/pokeleximon-release.tgz deploy@your-host:/tmp/pokeleximon-release.tgz
scp infra/production/aws-ec2/bin/deploy_remote.sh deploy@your-host:/tmp/deploy_remote.sh
ssh deploy@your-host "chmod 755 /tmp/deploy_remote.sh && sudo /tmp/deploy_remote.sh --release-archive /tmp/pokeleximon-release.tgz --release-id manual-$(date +%Y%m%d%H%M%S)"
```

The deploy script:

- extracts a release into `/opt/pokeleximon/app/releases/<release-id>`
- repoints `/opt/pokeleximon/app/current`
- starts Postgres and Redis
- runs Alembic migrations
- rebuilds and restarts the stack, including Prometheus/Grafana/exporters
- verifies API health and same-origin proxy routing

Before the first deploy, and after any secret rotation, run:

```bash
sudo bash /opt/pokeleximon/app/current/infra/production/aws-ec2/bin/preflight.sh --root /opt/pokeleximon
```

## Monitoring

The EC2 compose stack provisions:

- Prometheus scraping `api`, `node-exporter`, `postgres-exporter`, `redis-exporter`, and itself
- Prometheus rule evaluation for host, API, data, and reserve alerts
- Alertmanager for local alert state and optional webhook forwarding
- Grafana with repo-provisioned dashboards and datasource config

Access stays local to the host:

- Grafana: `127.0.0.1:3000`
- Prometheus: `127.0.0.1:9090`
- Alertmanager: `127.0.0.1:9093`

Use an SSH tunnel from your workstation:

```bash
ssh -L 3000:127.0.0.1:3000 -L 9090:127.0.0.1:9090 deploy@your-host
```

Then open:

- Grafana: `http://127.0.0.1:3000`
- Prometheus: `http://127.0.0.1:9090`
- Alertmanager: `http://127.0.0.1:9093`

Grafana credentials are stored in `/opt/pokeleximon/secrets/admin_access.txt`.

Alert delivery:

- Prometheus alerts always evaluate locally.
- If `ALERTMANAGER_WEBHOOK_URL` is set in `/opt/pokeleximon/secrets/monitoring.env`, Alertmanager forwards alert payloads to that webhook.
- If it is blank, alerts are still visible in Prometheus and Alertmanager UIs but are not sent anywhere.

Provisioned dashboards:

- `Pokeleximon Go Live Overview`
- `Pokeleximon API and Data Plane`
- `Pokeleximon Gameplay and Content Ops`

Implemented alert coverage:

- API down, Redis down, Postgres down
- exporter gaps for node/postgres/redis metrics
- sustained API 5xx rate
- sustained high p95 latency
- sustained heavy 429/rate-limit pressure
- high CPU, memory, and root disk usage on the host
- reserve below minimum, reserve empty, and low date coverage
- open critical in-app operational alerts
- failure of the custom DB-backed metrics collector

## Rollback

```bash
ls -1 /opt/pokeleximon/app/releases
sudo ln -sfn /opt/pokeleximon/app/releases/<previous-release-id> /opt/pokeleximon/app/current
sudo docker compose --env-file /opt/pokeleximon/app/deploy.env \
  -f /opt/pokeleximon/app/current/infra/production/aws-ec2/docker-compose.prod.yml \
  up -d --build
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

Behavior:

- local backups are written to `/opt/pokeleximon/backups`
- local backups older than 14 days are pruned
- when `BACKUP_S3_ENABLED=true`, the backup is also uploaded to `BACKUP_S3_URI`

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

```bash
sudo docker compose --env-file /opt/pokeleximon/app/deploy.env \
  -f /opt/pokeleximon/app/current/infra/production/aws-ec2/docker-compose.prod.yml \
  up -d --build api db
curl -kfsS --resolve "your-domain.example:443:127.0.0.1" https://your-domain.example/health
sudo bash /opt/pokeleximon/app/current/infra/production/aws-ec2/bin/create_secrets.sh --root /opt/pokeleximon --force
sudo bash /opt/pokeleximon/app/current/infra/production/aws-ec2/bin/preflight.sh --root /opt/pokeleximon
```

Admin access remains layered:

1. Reverse-proxy basic auth gates `/admin` and `/api/v1/admin/*`
2. The admin UI still requires the API admin token for admin requests

## Monthly Maintenance

- Apply OS package updates.
- Update Docker Engine, Compose plugin, and AWS CLI on a controlled cadence.
- Review free disk space under `/opt/pokeleximon`.
- Confirm backups exist locally and in S3.
- Review Prometheus retention pressure and Grafana access credentials.
- Confirm the instance profile still has the required S3 permissions.
- Review AWS spend and remaining Free Plan credits.
