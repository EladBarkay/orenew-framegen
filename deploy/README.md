# Deployment

`compose.yaml` starts every FrameGen service with one command (`DESIGN.md` section 9.2,
decision D2):

| Service | What it is | Reachable at |
|---|---|---|
| `web` | Caddy serving the web app, forwarding `/v1` to the API and `/<bucket>/` to the storage | http://localhost:8080 ¹ |
| `api` | FastAPI backend | through `web`, at `/v1` |
| `worker` | Runs background jobs from the queue (Procrastinate, in Postgres), and renders frames in headless Chromium | — |
| `psd-writer` | Internal PSD text-layer service (D8) | inside Compose only |
| `postgres` | PostgreSQL 17 with pgvector | localhost:5432 ¹ |
| `storage` | RustFS, S3-compatible file storage (D9) | localhost:9000 ¹ |
| `storage-init` | Creates the storage bucket on start, then exits | — |
| `migrate` | Brings the database schema up to date on start, then exits | — |

¹ The default; see [Ports](#ports) to change it.

## Running it locally

Needs Docker Compose v2 (`docker compose`). From the repository root:

```sh
docker compose -f deploy/compose.yaml up --build --wait
```

Then open http://localhost:8080 (or your `FRAMEGEN_WEB_PORT`). `GET /v1/health` says the API is running. Whether it can
reach the database and storage is `GET /internal/health/ready`, which Caddy does not
forward; ask the API directly:

```sh
docker compose -f deploy/compose.yaml exec api python -c \
  "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/internal/health/ready').read().decode())"
```

- Stop: `docker compose -f deploy/compose.yaml down`. Data is kept in the
  `postgres-data` and `storage-data` volumes and is there on the next start.
- Start from empty: `docker compose -f deploy/compose.yaml down --volumes`.
- Ports are bound to `127.0.0.1` only; see [Ports](#ports).

## Ports

If a port is already taken on your machine (another Postgres on 5432, say), choose others
in a `.env` file next to `compose.yaml` (git ignores it), so every later `docker compose`
command uses them too:

```sh
# deploy/.env
FRAMEGEN_POSTGRES_PORT=15432
```

| Variable | Default | Port of |
|---|---|---|
| `FRAMEGEN_WEB_PORT` | 8080 | the site (`web`); pre-signed links follow it unless `FRAMEGEN_PUBLIC_URL` is set |
| `FRAMEGEN_POSTGRES_PORT` | 5432 | `postgres` |
| `FRAMEGEN_STORAGE_PORT` | 9000 | `storage` |

Inside Compose the services do not use these ports. The backend run directly on your
machine (as in the main README) does, and it does not read `deploy/.env`: export the
same ports in the shell you run it from, before any `uv run` (tests included, which
would otherwise create their database on whatever answers at 5432):

```sh
export FRAMEGEN_DB_PORT=15432
export FRAMEGEN_S3_ENDPOINT_URL=http://localhost:19000 FRAMEGEN_S3_PUBLIC_URL=http://localhost:19000
```

Files are uploaded and downloaded straight to and from the storage with pre-signed links
(`DESIGN.md` section 6.2). The links point at the site itself (`FRAMEGEN_PUBLIC_URL`,
`http://localhost:` and the web port by default), and Caddy forwards the bucket's path, `/framegen/`,
to the storage. So browsers need only the one address, and the bucket's name is not
available as a page path. When the site is reached at another address, set
`FRAMEGEN_PUBLIC_URL` to it.

The names, passwords and keys in `compose.yaml` are defaults for a developer's own
machine. They can be overridden with environment variables (`FRAMEGEN_DB_NAME`,
`FRAMEGEN_DB_USER`, `FRAMEGEN_DB_PASSWORD`, `FRAMEGEN_S3_BUCKET`,
`FRAMEGEN_S3_ACCESS_KEY`, `FRAMEGEN_S3_SECRET_KEY`); each is passed both to the server
that uses it and to the backend. Postgres takes its user, password and database name only
when its volume is first created, so after changing one of those, start from empty
(`down --volumes`). Production (T-56) adds its own
settings, secrets and HTTPS on top of this file; `web/Caddyfile` already reads
`FRAMEGEN_SITE_ADDRESS` for that.

## Building behind a TLS-inspecting proxy

If your network replaces TLS certificates (a company proxy, some sandboxes), the image
builds need its CA certificate. Every Dockerfile accepts an optional build secret named
`build_ca` and uses it only while downloading packages; it is not kept in the images.
Pass it with a Compose override file of your own, for example:

```yaml
# compose.proxy.yaml (keep it out of the repository)
x-proxy-build: &proxy-build
  # Both: the worker's system packages are fetched over plain HTTP.
  args: { HTTP_PROXY: http://proxy.example:3128, HTTPS_PROXY: http://proxy.example:3128 }
  secrets: [build_ca]
services:
  api: { build: *proxy-build } # builds the backend image; storage-init and migrate reuse it
  worker: { build: *proxy-build } # the backend image plus Chromium
  psd-writer: { build: *proxy-build }
  web: { build: *proxy-build }
secrets:
  build_ca: { file: /path/to/proxy-ca.pem }
```

```sh
docker compose -f deploy/compose.yaml -f compose.proxy.yaml build
```
