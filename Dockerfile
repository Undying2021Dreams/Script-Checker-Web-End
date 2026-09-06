# One image serving both the API and the built frontend.
#
# Two services would mean two things to deploy, two things to keep in
# sync, and a CORS configuration between them. One container is cheaper
# on a fixed credit and removes cross-origin entirely: the page and the
# API it calls share an origin.

# ── Stage 1: build the frontend ─────────────────────────────────────
FROM node:22-slim AS frontend

WORKDIR /build

# Copied before the sources so a change to application code doesn't
# invalidate the dependency layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./

# Entra ID's client id is read at build time by Vite and baked into the
# bundle. It isn't a secret — a public SPA client id is visible to
# anyone who opens the page — but it does have to be present when the
# bundle is built, not when the container starts.
ARG VITE_AZURE_CLIENT_ID=""
ARG VITE_AZURE_TENANT_ID="common"
ARG VITE_AZURE_API_SCOPE=""
ENV VITE_AZURE_CLIENT_ID=$VITE_AZURE_CLIENT_ID \
    VITE_AZURE_TENANT_ID=$VITE_AZURE_TENANT_ID \
    VITE_AZURE_API_SCOPE=$VITE_AZURE_API_SCOPE

RUN npm run build

# ── Stage 2: the application ────────────────────────────────────────
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # The renderer's browser runs beside the app, so it reads the app's
    # own static files directly rather than going out through ingress.
    RENDER_BASE_URL=http://localhost:8000 \
    # Chromium is installed as root but the app runs as an unprivileged
    # user, and Playwright looks for browsers under the *running* user's
    # home cache. Without a shared path it installs to /root/.cache and
    # is then invisible, so every PDF render fails with "Executable
    # doesn't exist" — in the container only, never locally.
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# poppler-utils: pdf2image shells out to pdftoppm/pdftocairo, which are
# native binaries `pip install pdf2image` does not provide.
# libzbar0: pyzbar's QR decoder needs the native zbar library. Without
# it the import fails at call time and the fallback decoder silently
# never runs, leaving only OpenCV's own — weaker on small or skewed
# codes, which is exactly the case that matters on a photographed page.
# libgl1/libglib2.0-0: OpenCV links against these even headless.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        poppler-utils libzbar0 libgl1 libglib2.0-0 curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
# The heavy wheels here (opencv, chromium) are big enough that a single
# slow response from the index kills the whole build — which it did, on
# a read timeout partway through. Retry rather than restart from
# scratch, and split the two steps so a network failure in one doesn't
# discard the layer the other already produced.
RUN pip install --no-cache-dir --retries 5 --timeout 120 -r requirements.txt
RUN python -m playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright

COPY backend/ .

# Built frontend, served by the app itself (see main.py).
COPY --from=frontend /build/dist ./frontend_dist

# Runs as a non-root user: a container that only needs to read its own
# code and talk to Postgres has no reason to be root.
RUN useradd --create-home --uid 10001 webend \
    && chown -R webend:webend /app
USER webend

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# Migrations run before the server starts, so a deploy that changes the
# schema can't serve traffic against the old one. A failure here stops
# the container rather than letting it come up half-migrated.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
