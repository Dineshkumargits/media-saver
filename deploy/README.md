# Deploying Media Saver

Application-level only. Host setup — the reverse proxy, Cloudflare tunnel,
provisioning, firewall and backups — lives in the separate **infra** repo at
`/srv/infra`. Set that up first.

```
/srv/
├── infra/            <- shared: MySQL, Redis, Caddy, backups (separate repo)
└── media-saver/      <- this repo, both frontend and backend
```

No database is used, so `create-app-db.sh` is not needed for this app.

## First deploy

Assumes `infra` is already running and the `shared-net` network exists.

```bash
# 1. Configure
cd /srv/media-saver/backend
cp .env.example .env && $EDITOR .env

# 2. Reverse proxy vhosts
cp deploy/media-saver.caddy /srv/infra/caddy/sites/
docker exec shared-caddy caddy reload --config /etc/caddy/Caddyfile

# 3. Build and start
cd /srv/media-saver
docker compose up -d --build
docker compose logs -f backend
```

## Environment variables

From `backend/.env` — see `backend/.env.example`. Easy to miss:

- `ALLOWED_ORIGINS` must include `https://media-saver.adkdev.in` in
  production (defaults to the localhost dev origin only).
- `IG_USERNAME` / `IG_PASSWORD` — optional, enables the authenticated
  `instagrapi` fallback when anonymous Instagram scraping gets throttled.
  Session cookies persist to the `ig_sessions` named volume across restarts.

`NEXT_PUBLIC_API_BASE_URL` is baked into the Next.js bundle **at build
time** via the `frontend` service's `build.args` in `docker-compose.yml` —
not a runtime env var. It currently points at
`https://media-saver-api.adkdev.in`. Changing it means rebuilding the
`frontend` image, not just restarting the container.

## DNS

No A records, no exposed port 443 — this VPS has a shared public IP whose
port 443 is provider-reserved, so direct exposure was never an option here.
Public traffic arrives over an outbound Cloudflare Tunnel instead; TLS is
terminated at the Cloudflare edge, and the tunnel forwards over the Docker
network to `http://shared-caddy:80`, which dispatches by Host header to the
vhosts in `deploy/media-saver.caddy`.

1. `adkdev.in` is already registered at Cloudflare and owned by the
   `cloudflared-adkdev` tunnel/account — no new tunnel needed.
2. Zero Trust → Networks → Tunnels → the adkdev tunnel → **Public
   Hostnames** → add `media-saver-api.adkdev.in` and `media-saver.adkdev.in`,
   each pointing at `http://shared-caddy:80`. Cloudflare creates the proxied
   CNAME itself — don't hand-create A/CNAME records for these.

## Deploying an update

```bash
cd /srv/media-saver && git pull
docker compose up -d --build
```

Only this stack restarts — MySQL, Redis and Caddy keep running, so other
applications on the box are unaffected.

If `deploy/media-saver.caddy` changed, copy it over and reload Caddy again
(step 2 under First deploy).

If only `NEXT_PUBLIC_API_BASE_URL` or another frontend build arg changed,
`docker compose up -d --build` still picks it up since it's passed at build
time on every `--build` run.

## Operations

```bash
docker compose ps
docker compose logs -f --tail=100 backend
docker stats --no-stream
```
