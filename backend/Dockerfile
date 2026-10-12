# FrameGen backend images, built from the repository root:
#   docker build -f backend/Dockerfile .                 the API (and one-off commands)
#   docker build -f backend/Dockerfile --target worker .  the worker, with Chromium to render

FROM python:3.12-slim AS dependencies
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /src
COPY backend/pyproject.toml backend/uv.lock backend/.python-version ./
# The optional build_ca secret adds a CA for building behind a TLS-inspecting proxy
# (deploy/README.md). Without it the build uses the system certificates.
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca PIP_CERT=/run/secrets/build_ca; fi \
    && pip install --no-cache-dir uv==0.11.32 \
    && uv sync --locked --no-dev --no-install-project

FROM dependencies AS build
COPY backend/framegen ./framegen
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi \
    && uv sync --locked --no-dev --no-editable

FROM python:3.12-slim AS api
RUN useradd --system --uid 10001 --no-create-home framegen
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1
USER framegen
EXPOSE 8000
# X-Forwarded-* headers from Caddy are not trusted yet; T-56 adds that together with HTTPS.
# On stop, open requests (such as job event streams) get 10 s to end, then are closed.
CMD ["uvicorn", "framegen.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers", "--timeout-graceful-shutdown", "10"]

# The worker renders frames in headless Chromium (DESIGN.md 9). Playwright is pinned in
# uv.lock, and it installs the matching Chromium build, so renders are the same everywhere.
# Chromium is installed from the dependencies alone, so a code change does not download it
# again; the app's own environment is copied over it afterwards.
FROM python:3.12-slim AS worker
RUN useradd --system --uid 10001 --no-create-home framegen
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
COPY --from=dependencies /app/.venv /app/.venv
RUN --mount=type=secret,id=build_ca,required=false \
    if [ -f /run/secrets/build_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/build_ca; fi \
    && playwright install --with-deps --only-shell chromium \
    && chmod -R a+rX /opt/playwright \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /app/.venv /app/.venv
USER framegen
CMD ["framegen-worker"]
