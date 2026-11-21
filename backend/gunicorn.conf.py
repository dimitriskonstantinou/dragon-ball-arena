"""
gunicorn settings for the production image (the Dockerfile runs `gunicorn -c gunicorn.conf.py app:app`).

Settings come from config.py like everywhere else; a configuration error stops here,
before any worker starts, with the same message and exit code 3 the app uses.
"""
import sys

# Careful: gunicorn reads EVERY top-level name here as one of its settings -- and `config`
# is one (the config file path). So the app's modules are imported under other names.
import config as app_config
import logging_setup as app_logging

try:
    settings = app_config.load()
except app_config.ConfigError as e:
    print(f"Configuration error: {e}", file=sys.stderr, flush=True)
    sys.exit(3)

bind = f"0.0.0.0:{settings.port}"
# gevent: one process serves thousands of websocket connections. EXACTLY ONE worker:
# live matches are kept in memory and can't be shared between processes.
worker_class = 'gevent'
workers = 1
graceful_timeout = 20
# The app logs every request itself (arena.http, with user + timing), so no access log here;
# gunicorn's own lines use the app's format (logging_setup).
accesslog = None
errorlog = '-'
loglevel = settings.log_level.lower()
logconfig_dict = app_logging.gunicorn_logconfig(settings.log_level, settings.log_format)
