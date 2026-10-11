# Web app: the static SvelteKit build, served by Caddy, which also forwards /v1 to the API.
# Build from the repository root: docker build -f web/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY sdk/typescript/package.json sdk/typescript/
COPY web/package.json web/
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi \
    && npm install --global pnpm@10.28.0 \
    && pnpm install --frozen-lockfile --filter @framegen/web...
COPY sdk/typescript sdk/typescript
COPY web web
RUN pnpm --filter @framegen/sdk build && pnpm --filter @framegen/web build

FROM caddy:2.10-alpine
COPY web/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /src/web/build /srv
