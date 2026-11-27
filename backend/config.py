"""
All runtime settings, read from environment variables and validated once at
startup. Invalid or missing production settings stop the server with a clear
message (config.ConfigError) instead of running insecurely or crashing later.

  ENV                development (default) | staging | production
  SECRET_KEY         signs login cookies. REQUIRED in staging/production (>= 32 chars).
                     In development a random key is generated once and kept in
                     backend/.dev_secret_key (git-ignored) -- there is no key in the code.
  ALLOWED_ORIGINS    comma-separated origins allowed to open a game connection, e.g.
                     https://dragonballarena.com. Development default: same origin only.
                     REQUIRED (https only) in staging/production; '*' is never accepted. If it's missing there,
                     RENDER_EXTERNAL_URL (set by Render: the site's own address) is used.
  DATABASE_URL       SQLAlchemy URL (default: SQLite file backend/game.db). REQUIRED in staging/production:
                     no silent fallback to a SQLite file inside the container (hosts wipe it on redeploy).
                     postgres:// and postgresql:// (what hosts hand out) become postgresql+psycopg:// (our driver).
  PORT               dev server port (default 5000)
  TURN_SECONDS       turn time limit (default 60, 1..600)
  RECONNECT_SECONDS  grace period to come back after a disconnect (default 30, 0..600)
  TURN_TIMER_THREAD  0 disables the background ticker (tests drive it by hand)
  LOGIN_FAILURE_LIMIT / LOGIN_WINDOW_SECONDS   failed logins allowed per client IP per window (default 5 / 300)
  REGISTER_LIMIT / REGISTER_WINDOW_SECONDS     new accounts allowed per client IP per window (default 5 / 3600)
  SESSION_DAYS       a login expires after this many days without any visit (default 30, 1..365)
  LOG_LEVEL          DEBUG | INFO (default) | WARNING | ERROR
  LOG_FORMAT         text (default) | json (one JSON object per line, for hosted log services)
  APP_VERSION        which build is running, shown in the startup log line (the Docker image sets it to the
                     git commit at build time; default 'dev'). Letters, digits and . _ - + only. If it's missing or
                     'unknown', RENDER_GIT_COMMIT (set by Render) is used, shortened.
  SOCKETIO_ASYNC_MODE  threading (default: python app.py, tests) | gevent (production: gunicorn -k gevent,
                     set by the Dockerfile). Explicit, because Flask-SocketIO would otherwise switch to gevent
                     by itself as soon as the package is installed.
  TRUSTED_PROXIES    how many reverse proxies sit in front of the app (default 0). Set it (e.g. 1 on Render)
                     so the real client IP is read from X-Forwarded-For -- otherwise every player shares the
                     proxy's IP and one attacker could rate-limit everybody.
  CLIENT_IP_HEADER   the header in which the host puts the visitor's address (default none), e.g. CF-Connecting-IP on Render,
                     where X-Forwarded-For has it at a different position for pages and websockets (SEC-9). Only set it
                     to a header the host always sets itself: any other one can be faked by every visitor.
"""
import os
import re
import secrets
from dataclasses import dataclass

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DEV_SECRET_FILE = os.path.join(BACKEND_DIR, '.dev_secret_key')
ENVIRONMENTS = ('development', 'staging', 'production')
MIN_SECRET_LENGTH = 32
# Publicly known keys (this one was the old hardcoded fallback) -- never accepted in production.
KNOWN_INSECURE_KEYS = {'dev-secret-key-change-in-production'}
GENERATE_HINT = 'generate one with: python -c "import secrets; print(secrets.token_hex(32))"'
ORIGIN_PATTERN = re.compile(r'^https?://[A-Za-z0-9.-]+(:[0-9]{1,5})?$')


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str
    allowed_origins: tuple   # () = same origin only
    database_url: str
    port: int
    turn_seconds: int
    reconnect_seconds: int
    turn_timer_thread: bool
    login_failure_limit: int
    login_window_seconds: int
    register_limit: int
    register_window_seconds: int
    trusted_proxies: int
    client_ip_header: str    # '' = the connection's own address (after TRUSTED_PROXIES)
    session_days: int
    log_level: str
    socketio_async_mode: str
    log_format: str
    app_version: str

    @property
    def is_production_like(self):
        return self.env in ('staging', 'production')


def _int(environ, name, default, low, high):
    raw = environ.get(name)
    if raw is None or raw == '':
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a whole number, got {raw!r}")
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


def _origins(environ, env):
    """Who may open a game connection. The login cookie travels with it, so
    '*' (any website) is never allowed."""
    raw = environ.get('ALLOWED_ORIGINS') or ''
    if not raw and env in ('staging', 'production'):
        raw = (environ.get('RENDER_EXTERNAL_URL') or '').rstrip('/')
    origins = tuple(o.strip() for o in raw.split(',') if o.strip())
    for origin in origins:
        if origin == '*':
            raise ConfigError("ALLOWED_ORIGINS can't be '*': logins use a cookie, so any website could act as "
                              "the player. List the site's own origin(s), e.g. https://dragonballarena.com")
        if not ORIGIN_PATTERN.match(origin):
            raise ConfigError(f"ALLOWED_ORIGINS entry {origin!r} must look like https://example.com "
                              f"(scheme + host [+ port], no path or trailing slash)")
    if env in ('staging', 'production'):
        if not origins:
            raise ConfigError(f"ALLOWED_ORIGINS is required when ENV={env} (behind an HTTPS proxy the "
                              f"same-origin check can't work), e.g. ALLOWED_ORIGINS=https://dragonballarena.com")
        insecure = [o for o in origins if not o.startswith('https://')]
        if insecure:
            raise ConfigError(f"ALLOWED_ORIGINS must use https:// when ENV={env}: {', '.join(insecure)}")
    return origins


def _database_url(environ):
    url = environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(BACKEND_DIR, 'game.db')}"
    # Without a driver name SQLAlchemy would look for psycopg2, which we don't use.
    return re.sub(r'^postgres(ql)?://', 'postgresql+psycopg://', url)


def _dev_secret(path):
    """A random key kept in a local file, so dev logins survive restarts
    without any key living in the source code."""
    try:
        with open(path, encoding='utf-8') as fh:
            key = fh.read().strip()
        if len(key) >= MIN_SECRET_LENGTH:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write(key)
    return key


def load(environ=None, dev_secret_file=DEV_SECRET_FILE):
    environ = os.environ if environ is None else environ
    env = (environ.get('ENV') or 'development').strip().lower()
    if env not in ENVIRONMENTS:
        raise ConfigError(f"ENV must be one of {', '.join(ENVIRONMENTS)}, got {env!r}")

    secret = environ.get('SECRET_KEY') or ''
    if env in ('staging', 'production'):
        if not secret:
            raise ConfigError(f"SECRET_KEY is required when ENV={env}; {GENERATE_HINT}")
        if len(secret) < MIN_SECRET_LENGTH:
            raise ConfigError(f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters when ENV={env}; "
                              f"{GENERATE_HINT}")
        if secret in KNOWN_INSECURE_KEYS:
            raise ConfigError(f"SECRET_KEY is a publicly known value; {GENERATE_HINT}")
    elif not secret:
        secret = _dev_secret(dev_secret_file)

    allowed_origins = _origins(environ, env)
    if env in ('staging', 'production') and not environ.get('DATABASE_URL'):
        raise ConfigError(f"DATABASE_URL is required when ENV={env} (e.g. postgresql+psycopg://user:pass@host/db); "
                          f"a SQLite file inside the server would be wiped on every redeploy")

    return Settings(
        env=env,
        secret_key=secret,
        allowed_origins=allowed_origins,
        database_url=_database_url(environ),
        port=_int(environ, 'PORT', 5000, 1, 65535),
        turn_seconds=_int(environ, 'TURN_SECONDS', 60, 1, 600),
        reconnect_seconds=_int(environ, 'RECONNECT_SECONDS', 30, 0, 600),
        turn_timer_thread=(environ.get('TURN_TIMER_THREAD', '1') != '0'),
        login_failure_limit=_int(environ, 'LOGIN_FAILURE_LIMIT', 5, 1, 100_000),
        login_window_seconds=_int(environ, 'LOGIN_WINDOW_SECONDS', 300, 1, 86_400),
        register_limit=_int(environ, 'REGISTER_LIMIT', 5, 1, 100_000),
        register_window_seconds=_int(environ, 'REGISTER_WINDOW_SECONDS', 3600, 1, 86_400),
        trusted_proxies=_int(environ, 'TRUSTED_PROXIES', 0, 0, 5),
        client_ip_header=_client_ip_header(environ),
        session_days=_int(environ, 'SESSION_DAYS', 30, 1, 365),
        log_level=_log_level(environ),
        log_format=_log_format(environ),
        app_version=_app_version(environ),
        socketio_async_mode=_async_mode(environ),
    )


def _client_ip_header(environ):
    name = (environ.get('CLIENT_IP_HEADER') or '').strip()
    if name and not re.fullmatch(r'[A-Za-z][A-Za-z0-9-]{1,39}', name):
        raise ConfigError(f"CLIENT_IP_HEADER must be a header name such as CF-Connecting-IP, got "
                          f"{environ.get('CLIENT_IP_HEADER')!r}")
    return name


ASYNC_MODES = ('threading', 'gevent')


def _async_mode(environ):
    mode = (environ.get('SOCKETIO_ASYNC_MODE') or 'threading').strip().lower()
    if mode not in ASYNC_MODES:
        raise ConfigError(f"SOCKETIO_ASYNC_MODE must be one of {', '.join(ASYNC_MODES)}, "
                          f"got {environ.get('SOCKETIO_ASYNC_MODE')!r}")
    return mode


LOG_LEVELS = ('DEBUG', 'INFO', 'WARNING', 'ERROR')


LOG_FORMATS = ('text', 'json')


def _log_format(environ):
    fmt = (environ.get('LOG_FORMAT') or 'text').strip().lower()
    if fmt not in LOG_FORMATS:
        raise ConfigError(f"LOG_FORMAT must be one of {', '.join(LOG_FORMATS)}, got {environ.get('LOG_FORMAT')!r}")
    return fmt


def _app_version(environ):
    version = (environ.get('APP_VERSION') or '').strip()
    if version in ('', 'unknown'):   # 'unknown' = the Dockerfile's default when the build isn't told the commit
        version = (environ.get('RENDER_GIT_COMMIT') or '').strip()[:7] or version or 'dev'
    if not re.fullmatch(r'[A-Za-z0-9._+-]{1,64}', version):
        raise ConfigError(f"APP_VERSION must be 1-64 letters, digits or . _ - +, got {environ.get('APP_VERSION')!r}")
    return version


def log_settings(environ=None):
    """(level, format) on their own -- for gunicorn.conf.py, which configures logging
    before the app (and the rest of the settings) is loaded."""
    environ = os.environ if environ is None else environ
    return _log_level(environ), _log_format(environ)


def _log_level(environ):
    level = (environ.get('LOG_LEVEL') or 'INFO').strip().upper()
    if level not in LOG_LEVELS:
        raise ConfigError(f"LOG_LEVEL must be one of {', '.join(LOG_LEVELS)}, got {environ.get('LOG_LEVEL')!r}")
    return level
