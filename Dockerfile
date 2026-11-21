# Production image (DEPLOY_PLAN Stage 3). Build and run:
#   docker build -t dragon-ball-arena .
#   docker run -p 8000:8000 -e ENV=production -e SECRET_KEY=... -e ALLOWED_ORIGINS=https://your.site \
#              -e DATABASE_URL=postgresql+psycopg://user:pass@host/db -e TRUSTED_PROXIES=1 dragon-ball-arena
# All settings are environment variables (backend/config.py); nothing secret is baked into the image.
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

# Run as an unprivileged user; the code stays owned by root (read-only for the app).
RUN useradd --create-home --uid 10001 arena
USER arena
WORKDIR /app/backend

# gevent: one process serves thousands of websocket connections. EXACTLY ONE worker (-w 1):
# live matches are kept in memory and can't be shared between processes.
ENV SOCKETIO_ASYNC_MODE=gevent \
    PORT=8000
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('PORT', '8000'), timeout=4)"
CMD ["sh", "-c", "exec gunicorn --worker-class gevent --workers 1 --bind 0.0.0.0:${PORT} --graceful-timeout 20 app:app"]
