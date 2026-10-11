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

Run the app locally:

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

FrameGen is free software under the GNU Affero General Public License, version 3 only.
See `LICENSE`.
