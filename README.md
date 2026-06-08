# Soulcuts Infrastructure

Production infrastructure for the Soulcuts project on a single Hetzner VPS.

This repo intentionally keeps the first deployment stage simple:

- Docker Compose runs production services on one VPS.
- Caddy terminates HTTPS and routes by hostname.
- GitHub Actions deploys only after changes are merged into this infra repo `main`.
- Frontend/backend repos build images and open PRs here to update versions.
- Ansible is used only for first server bootstrap.

## Repositories

- Frontend: `https://github.com/mharnichev/sc-fe`
- Backend: `https://github.com/mharnichev/sc-be`
- Domain: `soulcuts.com.ua`
- DNS provider: Cloudflare

## Routing

| Host | Service |
| --- | --- |
| `soulcuts.com.ua` | Nuxt public barbershop site |
| `www.soulcuts.com.ua` | Nuxt public barbershop site |
| `soulcuts.com.ua/blog` | Nuxt blog app |
| `admin.soulcuts.com.ua` | Nuxt admin/backoffice app |
| `api.soulcuts.com.ua` | FastAPI backend |

The admin app is not routed from the main domain. Caddy only sends `admin.soulcuts.com.ua` to the admin service.

## What Was Inspected

The frontend repo is a pnpm monorepo:

- `apps/barbershop` is the public Nuxt app.
- `apps/blog` is the Nuxt blog app served under `/blog`.
- `apps/backoffice` is the admin Nuxt app.
- The Nuxt apps already have separate Dockerfiles.
- The Nuxt apps read `NUXT_PUBLIC_API_BASE` through Nuxt runtime config.

The backend repo is FastAPI:

- The API listens on port `8000`.
- It uses PostgreSQL and Alembic.
- It exposes health at `/api/v1/public/health`.
- The current backend Dockerfile is development-oriented because it installs dev requirements and starts Uvicorn with `--reload`.

## Production Assumptions

Use Ubuntu 24.04 LTS or Debian 12 on the Hetzner VPS. Ubuntu 22.04 should also work.

Image names used by this repo:

```env
PUBLIC_SITE_IMAGE=ghcr.io/mharnichev/sc-fe/public-site:<tag>
BLOG_IMAGE=ghcr.io/mharnichev/sc-fe/blog:<tag>
ADMIN_APP_IMAGE=ghcr.io/mharnichev/sc-fe/admin:<tag>
BACKEND_IMAGE=ghcr.io/mharnichev/sc-be/api:<tag>
```

The example workflows in `examples/github-actions/` create PRs that update `versions/production.env`.

The app repositories should eventually adopt the production Dockerfile examples in `examples/frontend/` and `examples/backend/`. The current frontend Dockerfiles are usable as a starting point, but they do not use `pnpm install --frozen-lockfile`. The current backend image starts with `--reload`; this infra overrides the backend command in Compose, but the backend repo should still move to a production Dockerfile.

## Repository Layout

```text
.
├── .github/workflows/
│   ├── deploy-production.yml
│   └── validate.yml
├── ansible/
│   ├── inventory.example.ini
│   └── provision.yml
├── caddy/
│   └── Caddyfile
├── env/
│   ├── admin-app.env.example
│   ├── blog.env.example
│   ├── backend.env.example
│   ├── caddy.env.example
│   ├── postgres.env.example
│   └── public-site.env.example
├── examples/
│   ├── backend/
│   ├── frontend/
│   └── github-actions/
├── scripts/
│   ├── backup-db.sh
│   ├── deploy.sh
│   ├── restore-db.sh
│   └── rollback.sh
├── versions/
│   └── production.env
└── docker-compose.prod.yml
```

## Required GitHub Secrets

Create these secrets in this infra repository:

| Secret | Purpose |
| --- | --- |
| `PRODUCTION_HOST` | VPS public IP or hostname |
| `PRODUCTION_PORT` | SSH port, usually `22` |
| `PRODUCTION_USER` | Deploy user, default from Ansible is `deploy` |
| `PRODUCTION_SSH_KEY` | Private SSH key for the deploy user |
| `PRODUCTION_KNOWN_HOSTS` | Output of `ssh-keyscan -p <port> <host>` |
| `GHCR_USERNAME` | GitHub username allowed to pull packages |
| `GHCR_READ_TOKEN` | GitHub token with `read:packages` |

Create this secret in `sc-fe` and `sc-be`:

| Secret | Purpose |
| --- | --- |
| `INFRA_REPO_PAT` | Fine-grained PAT that can push branches and open PRs in this infra repo |

## Server Bootstrap

Install Ansible on your local machine:

```bash
python3 -m pip install --user ansible
ansible-galaxy collection install ansible.posix community.general
```

Copy the inventory example:

```bash
cp ansible/inventory.example.ini ansible/inventory.ini
```

Edit `ansible/inventory.ini` and set the VPS IP. Then run:

```bash
ansible-playbook -i ansible/inventory.ini ansible/provision.yml \
  --user root \
  --extra-vars "deploy_ssh_public_key='$(cat ~/.ssh/id_ed25519.pub)'"
```

The playbook installs Docker, Docker Compose plugin, UFW, fail2ban, creates the `deploy` user, creates `/opt/soulcuts`, and hardens basic SSH settings.

Before closing your root SSH session, verify that deploy login works:

```bash
ssh deploy@<server-ip>
docker compose version
```

## Server Environment Files

Secrets are not committed. On the server, create:

```text
/opt/soulcuts/env/caddy.env
/opt/soulcuts/env/postgres.env
/opt/soulcuts/env/backend.env
/opt/soulcuts/env/public-site.env
/opt/soulcuts/env/blog.env
/opt/soulcuts/env/admin-app.env
```

Use the files in `env/*.example` as templates.

From your local infra repo checkout, copy the templates to the server:

```bash
scp -P <ssh-port> env/*.example deploy@<server-ip>:/tmp/
ssh -p <ssh-port> deploy@<server-ip>
install -m 0600 /tmp/caddy.env.example /opt/soulcuts/env/caddy.env
install -m 0600 /tmp/postgres.env.example /opt/soulcuts/env/postgres.env
install -m 0600 /tmp/backend.env.example /opt/soulcuts/env/backend.env
install -m 0600 /tmp/public-site.env.example /opt/soulcuts/env/public-site.env
install -m 0600 /tmp/blog.env.example /opt/soulcuts/env/blog.env
install -m 0600 /tmp/admin-app.env.example /opt/soulcuts/env/admin-app.env
rm /tmp/*.env.example
```

Then edit the values:

```bash
sudo nano /opt/soulcuts/env/postgres.env
sudo nano /opt/soulcuts/env/backend.env
sudo nano /opt/soulcuts/env/caddy.env
```

Use a long random `SECRET_KEY` and strong `POSTGRES_PASSWORD`.

For backend email notifications, set these values in `/opt/soulcuts/env/backend.env` using real SMTP credentials from the selected mail provider:

```env
EMAIL_NOTIFICATIONS_ENABLED=true
SMTP_HOST=<provider-smtp-host>
SMTP_PORT=587
SMTP_USERNAME=<provider-smtp-login>
SMTP_PASSWORD=<provider-smtp-password>
SMTP_FROM_EMAIL=bookings@your-domain.com
SMTP_FROM_NAME=Soulcuts
SMTP_USE_TLS=true
SMTP_TIMEOUT_SECONDS=10
```

After changing backend environment values, restart the backend service:

```bash
docker compose --project-name soulcuts --env-file versions/production.env -f docker-compose.prod.yml restart backend
```

Redis is not included because the inspected backend does not currently require it. Add it later only if the backend gets a real Redis dependency such as queues, caching, or rate limiting.

## Cloudflare DNS

Create these records:

| Type | Name | Value |
| --- | --- | --- |
| `A` | `@` | VPS IPv4 |
| `A` | `www` | VPS IPv4 |
| `A` | `admin` | VPS IPv4 |
| `A` | `api` | VPS IPv4 |

For the first deploy, use DNS only mode so Caddy can obtain Let's Encrypt certificates directly. After certificates are issued, you can enable Cloudflare proxy and set SSL/TLS mode to `Full (strict)`.

The firewall must allow ports `22`, `80`, and `443`.

## First Deploy

1. Push this repo to GitHub.
2. Confirm `versions/production.env` points at existing GHCR images.
3. Configure all infra repo secrets listed above.
4. Merge a PR into this repo `main`, or run `Deploy production` manually from GitHub Actions.

The deployment workflow:

1. Validates Compose and Caddy config.
2. Copies the repository to `/opt/soulcuts/releases/<timestamp>-<sha>`.
3. Logs the server into GHCR.
4. Runs `scripts/deploy.sh` on the server.
5. Updates `/opt/soulcuts/current` only after services become healthy.

## Normal Release Flow

Frontend/backend repos do not deploy production directly.

1. Merge app code into `sc-fe/main` or `sc-be/main`.
2. That app repo builds and pushes Docker images to GHCR.
3. That app repo opens a PR in this infra repo updating `versions/production.env`.
4. Review the infra PR.
5. Merge the infra PR into `main`.
6. The infra deploy workflow updates production.

This keeps production deployment controlled by the infra repo.

## Updating Versions Manually

Edit `versions/production.env`:

```env
PUBLIC_SITE_IMAGE=ghcr.io/mharnichev/sc-fe/public-site:<new-tag>
BLOG_IMAGE=ghcr.io/mharnichev/sc-fe/blog:<new-tag>
ADMIN_APP_IMAGE=ghcr.io/mharnichev/sc-fe/admin:<new-tag>
BACKEND_IMAGE=ghcr.io/mharnichev/sc-be/api:<new-tag>
```

Open a PR and merge it into `main`.

## Rollback

SSH to the server:

```bash
ssh deploy@<server-ip>
cd /opt/soulcuts/current
./scripts/rollback.sh
```

By default rollback selects the previous release directory. To rollback to a specific release:

```bash
./scripts/rollback.sh /opt/soulcuts/releases/20260523-120000-abc1234
```

Rollback changes running containers back to an older image set. It does not downgrade database migrations. For risky backend releases, take a database backup first.

## Database Backup And Restore

Backup:

```bash
ssh deploy@<server-ip>
cd /opt/soulcuts/current
./scripts/backup-db.sh
```

Restore:

```bash
ssh deploy@<server-ip>
cd /opt/soulcuts/current
CONFIRM_RESTORE=production ./scripts/restore-db.sh /opt/soulcuts/backups/<backup-file>.dump
```

Restore stops the backend, recreates the database from the dump, and starts the backend again.

## Frontend Repo Setup

Copy `examples/github-actions/frontend-build-and-pr.yml` to:

```text
sc-fe/.github/workflows/build-images-and-update-infra.yml
```

Recommended Dockerfile replacements:

```text
examples/frontend/Dockerfile.public-site -> sc-fe/apps/barbershop/Dockerfile
examples/frontend/Dockerfile.blog -> sc-fe/apps/blog/Dockerfile
examples/frontend/Dockerfile.admin-app -> sc-fe/apps/backoffice/Dockerfile
examples/frontend/.dockerignore -> sc-fe/.dockerignore
```

The workflow builds:

- `ghcr.io/mharnichev/sc-fe/public-site:<sha>`
- `ghcr.io/mharnichev/sc-fe/blog:<sha>`
- `ghcr.io/mharnichev/sc-fe/admin:<sha>`

All frontend apps should use:

```env
NUXT_PUBLIC_API_BASE=https://api.soulcuts.com.ua/api/v1
```

The blog app must also be built with:

```env
NUXT_APP_BASE_URL=/blog/
NUXT_PUBLIC_BLOG_SITE_URL=https://soulcuts.com.ua/blog
```

## Backend Repo Setup

Copy `examples/github-actions/backend-build-and-pr.yml` to:

```text
sc-be/.github/workflows/build-image-and-update-infra.yml
```

Recommended Dockerfile replacement:

```text
examples/backend/Dockerfile.production -> sc-be/Dockerfile
examples/backend/start-production.sh -> sc-be/scripts/start-production.sh
examples/backend/.dockerignore -> sc-be/.dockerignore
```

The workflow builds:

```text
ghcr.io/mharnichev/sc-be/api:<sha>
```

## Useful Server Commands

Inspect services:

```bash
cd /opt/soulcuts/current
docker compose --project-name soulcuts --env-file versions/production.env -f docker-compose.prod.yml ps
```

View logs:

```bash
docker compose --project-name soulcuts --env-file versions/production.env -f docker-compose.prod.yml logs -f backend
docker compose --project-name soulcuts --env-file versions/production.env -f docker-compose.prod.yml logs -f caddy
```

Restart one service:

```bash
docker compose --project-name soulcuts --env-file versions/production.env -f docker-compose.prod.yml up -d backend
```
