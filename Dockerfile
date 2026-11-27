# Production image (DEPLOY_PLAN Stage 3). Build and run:
#   docker build --build-arg APP_VERSION=$(git rev-parse --short HEAD) -t dragon-ball-arena .
#   docker run -p 8000:8000 -e ENV=production -e SECRET_KEY=... -e ALLOWED_ORIGINS=https://your.site \
#              -e DATABASE_URL=postgresql+psycopg://user:pass@host/db -e TRUSTED_PROXIES=1 dragon-ball-arena
# All settings are environment variables (backend/config.py); nothing secret is baked into the image.
# Stage 1: build the new interface (web/, React + TypeScript + Vite). Only its output goes into the final image:
# no Node.js, no node_modules, no sources. `npm ci` installs exactly web/package-lock.json.
FROM node:24.11.1-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY web/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
# Dependencies first: this layer is reused until a requirements file changes.
COPY backend/requirements.txt backend/requirements-server.txt backend/
RUN pip install -r backend/requirements-server.txt

COPY backend/ backend/
COPY frontend/ frontend/
COPY --from=web /web/dist/ web/dist/

# Run as an unprivileged user; the code stays owned by root (read-only for the app).
RUN useradd --create-home --uid 10001 arena
USER arena
WORKDIR /app/backend

# Server settings (gevent, EXACTLY ONE worker, logging): backend/gunicorn.conf.py.
# APP_VERSION (the git commit) appears in the startup log line, so every deploy is visible in the logs.
ARG APP_VERSION=unknown
ENV SOCKETIO_ASYNC_MODE=gevent \
    PORT=8000 \
    APP_VERSION=${APP_VERSION}
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)"
CMD ["gunicorn", "-c", "gunicorn.conf.py", "app:app"]
