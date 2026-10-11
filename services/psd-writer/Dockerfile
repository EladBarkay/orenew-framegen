# psd-writer: internal service that writes PSD text layers (DESIGN.md D8).
# Build from the repository root: docker build -f services/psd-writer/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /src
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY services/psd-writer/package.json services/psd-writer/
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi \
    && npm install --global pnpm@10.28.0 \
    && pnpm install --frozen-lockfile --filter @framegen/psd-writer
COPY services/psd-writer services/psd-writer
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi \
    && pnpm --filter @framegen/psd-writer build \
    && pnpm --filter @framegen/psd-writer deploy --legacy --prod /out

FROM node:22-alpine
WORKDIR /app
COPY --from=build /out ./
ENV NODE_ENV=production PORT=8090
USER node
EXPOSE 8090
CMD ["node", "dist/main.js"]
