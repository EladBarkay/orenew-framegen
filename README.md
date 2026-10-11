# Orenew FrameGen

FrameGen makes decorative photo frames for event photographers: landscape and portrait,
with a truly transparent window, from an existing template, an invitation, a photo of an
object, or a few words. It is a web app with a public API. `DESIGN.md` defines the
product and how it is built.

FrameGen is in development and has no release yet.

## Layout

| Folder | What it is |
|---|---|
| `backend/` | Python package `framegen`: the API (FastAPI) and the worker |
| `services/psd-writer/` | Small internal Node service that writes PSD text layers |
| `web/` | Web app (SvelteKit), a thin client of the API |
| `sdk/typescript/` | TypeScript client generated from the API's OpenAPI document |
| `deploy/` | Docker Compose and deployment files |

## Working on it

You need Python with [uv](https://docs.astral.sh/uv/), Node 22.17 or later, and pnpm 10.

```sh
pnpm install                 # Node packages for web, SDK and psd-writer
(cd backend && uv sync)      # Python packages for the backend
```

Run everything (database, storage, API, worker, web) in Docker with one command, then
open http://localhost:8080 (see `deploy/README.md`):

```sh
docker compose -f deploy/compose.yaml up --build --wait
```

Or run the API and web app directly while developing (the API expects Postgres and
storage, which you can start alone with
`docker compose -f deploy/compose.yaml up -d postgres storage storage-init`):

```sh
(cd backend && uv run uvicorn framegen.api.app:app --reload)   # API on :8000
pnpm --filter @framegen/web dev                                 # web app on :5173
```

Checks (the same ones CI runs on every pull request):

```sh
cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
pnpm format:check && pnpm lint && pnpm check && pnpm test && pnpm build
```

After changing the API, regenerate the SDK with `pnpm sdk:generate` and commit the
result; CI fails if it is out of date.

## Terms

Copyright (C) 2026 Elad Barkay

FrameGen is free software: you can redistribute it and/or modify it under the terms of
the GNU Affero General Public License as published by the Free Software Foundation,
version 3 only.

FrameGen is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR
PURPOSE. See the GNU Affero General Public License in `LICENSE` for more details.

Anyone who runs a changed FrameGen as a service for others must offer those users its
source code (section 13 of the licence). FrameGen does this itself: the web app links
to its source, and the API document names its licence and source.

## The name

The names "Orenew FrameGen", "FrameGen" and "Orenew" and their logos belong to the
project and are not covered by these terms. Unchanged copies may be shared and run under
these names. A changed version passed on or run as a service by someone else must use a
different name and logo, and must not suggest it is the official FrameGen or Orenew. See
`NAME-AND-LOGO.md`.

## Contributing

See `CONTRIBUTING.md`.
