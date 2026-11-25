"""
Logging for every way the server runs (python app.py, gunicorn, flask CLI, tests):
one format, UTC timestamps, to stderr (hosts collect stdout/stderr).

  LOG_FORMAT=text (default):  2026-11-21T17:26:37.068Z INFO arena.match: Match ended: room=ab12cd34 ...
  LOG_FORMAT=json:            {"ts": "...", "level": "INFO", "logger": "arena.match", "msg": "Match ended: ..."}

Loggers: `arena.http` (requests), `arena.auth` (accounts + security), `arena.socket`
(connections), `arena.match` (matchmaking + matches), `arena.stats` (periodic health
numbers), `app` (startup, database, errors), plus gunicorn / alembic / engineio.
NEVER log passwords, cookies, SECRET_KEY, database passwords or emails -- the smoke
test captures a whole run's logs and fails if one appears.
"""
import json
import logging
import re
import sys
import time
from urllib.parse import urlsplit

TEXT_FORMAT = '%(asctime)s %(levelname)s %(name)s: %(message)s'
# Libraries that attach their OWN output handler (each line would then appear twice, once
# unformatted -- which also breaks LOG_FORMAT=json). Their handlers are removed; they log through ours.
LIBRARY_LOGGERS_TO_UNIFY = ('gunicorn.error', 'gunicorn.access', 'engineio.server', 'socketio.server')


class UTCFormatter(logging.Formatter):
    converter = time.gmtime

    def formatTime(self, record, datefmt=None):
        return time.strftime('%Y-%m-%dT%H:%M:%S', self.converter(record.created)) + f'.{int(record.msecs):03d}Z'


class JsonFormatter(UTCFormatter):
    """One JSON object per line -- what hosted log services (Better Stack, Datadog, ...) parse best."""

    def format(self, record):
        entry = {'ts': self.formatTime(record), 'level': record.levelname, 'logger': record.name,
                 'msg': record.getMessage()}
        if record.exc_info:
            entry['exc'] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class ClientMistakes(logging.Filter):
    """engineio logs what a visitor did wrong (foreign website, unknown connection id, ...) as ERROR, with the
    visitor's raw text. Here that is a WARNING, cut to a safe length, with connection ids shortened. Real crashes
    (they carry a traceback) pass unchanged."""

    def filter(self, record):
        if record.levelno != logging.ERROR or record.exc_info:
            return True
        text = record.getMessage().split(' (further occurrences')[0]
        text = re.sub(r'[A-Za-z0-9_-]{20,}', lambda m: m.group(0)[:6] + '...', text)
        record.levelno, record.levelname = logging.WARNING, 'WARNING'
        record.msg, record.args = 'Rejected a game connection: %s', (short(text),)
        return logging.getLogger().isEnabledFor(logging.WARNING)


def make_formatter(fmt):
    return JsonFormatter() if fmt == 'json' else UTCFormatter(TEXT_FORMAT)


def configure(level, fmt='text'):
    """Sets up the root logger once (a host that configured logging itself is left
    alone) and routes gunicorn's own loggers through it, so every line looks the same."""
    root = logging.getLogger()
    if not root.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(make_formatter(fmt))
        root.addHandler(handler)
        root.setLevel(level)
    unify_library_loggers()


def unify_library_loggers():
    """Call again after creating SocketIO (engineio adds its handler at that point)."""
    if not logging.getLogger().handlers:
        return
    for name in LIBRARY_LOGGERS_TO_UNIFY:
        lib = logging.getLogger(name)
        if lib.handlers:
            lib.handlers = []
            lib.propagate = True
    engineio = logging.getLogger('engineio.server')
    if not any(isinstance(f, ClientMistakes) for f in engineio.filters):
        engineio.addFilter(ClientMistakes())


def gunicorn_logconfig(level, fmt='text'):
    """logconfig_dict for gunicorn.conf.py: the master process (before the app is
    imported) logs in the same format as the app."""
    formatter = {'()': JsonFormatter} if fmt == 'json' else {'()': UTCFormatter, 'format': TEXT_FORMAT}
    return {
        'version': 1,
        'disable_existing_loggers': False,
        'formatters': {'arena': formatter},
        'handlers': {'stderr': {'class': 'logging.StreamHandler', 'formatter': 'arena', 'stream': 'ext://sys.stderr'}},
        'root': {'level': level, 'handlers': ['stderr']},
        'loggers': {
            'gunicorn.error': {'level': level, 'handlers': [], 'propagate': True},
            # Off: the app logs every API request itself, and these lines hold full connection ids. gunicorn writes
            # them whenever a logconfig is set, whatever `accesslog` says (BE-16) -- so they are dropped here.
            'gunicorn.access': {'level': 'CRITICAL', 'handlers': [], 'propagate': False},
        },
    }


def safe_database_url(url):
    """The database URL without its password (for the startup line)."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return '?'
    if parts.scheme.startswith('sqlite'):
        # File name only -- a full local path (C:\\Users\\<name>\\...) doesn't belong in logs.
        return parts.scheme + ':' + re.split(r'[\\/]', parts.path)[-1]
    host = parts.hostname or '?'
    port = f':{parts.port}' if parts.port else ''
    return f"{parts.scheme}://{parts.username or ''}{'@' if parts.username else ''}{host}{port}{parts.path}"


def short(value, limit=200):
    """repr() of untrusted input, cut to `limit` characters (for error context)."""
    text = repr(value)
    return text if len(text) <= limit else text[:limit] + '...'
