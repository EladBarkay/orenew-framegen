# Deployment

`compose.yaml` starts every FrameGen service with one command (`DESIGN.md` section 9.2,
decision D2):

| Service | What it is | Reachable at |
|---|---|---|
| `web` | Caddy serving the web app and forwarding `/v1` to the API | http://localhost:8080 |
| `api` | FastAPI backend | through `web`, at `/v1` |
| `worker` | Background jobs (the queue arrives in T-08) | — |
| `psd-writer` | Internal PSD text-layer service (D8) | inside Compose only |
| `postgres` | PostgreSQL 17 with pgvector | localhost:5432 |
| `storage` | RustFS, S3-compatible file storage (D9) | localhost:9000 |
| `storage-init` | Creates the storage bucket on start, then exits | — |

## Running it locally

From the repository root:

```sh
docker compose -f deploy/compose.yaml up --build --wait
```

Then open http://localhost:8080. `GET /v1/health/ready` reports whether the API can reach
the database and storage.

- Stop: `docker compose -f deploy/compose.yaml down`. Data is kept in the
  `postgres-data` and `storage-data` volumes and is there on the next start.
- Start from empty: `docker compose -f deploy/compose.yaml down --volumes`.
- Ports are bound to `127.0.0.1` only.

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
  args: { HTTPS_PROXY: http://proxy.example:3128 }
  secrets: [build_ca]
services:
  api: { build: *proxy-build } # builds the backend image; storage-init and worker reuse it
  psd-writer: { build: *proxy-build }
  web: { build: *proxy-build }
secrets:
  build_ca: { file: /path/to/proxy-ca.pem }
```

```sh
docker compose -f deploy/compose.yaml -f compose.proxy.yaml build
```
