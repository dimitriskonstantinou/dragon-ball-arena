"""
All runtime settings, read from environment variables and validated once at
startup. Invalid or missing production settings stop the server with a clear
message (config.ConfigError) instead of running insecurely or crashing later.

  ENV                development (default) | staging | production
  SECRET_KEY         signs login cookies. REQUIRED in staging/production (>= 32 chars).
                     In development a random key is generated once and kept in
                     backend/.dev_secret_key (git-ignored) -- there is no key in the code.
  DATABASE_URL       SQLAlchemy URL (default: SQLite file backend/game.db)
  PORT               dev server port (default 5000)
  TURN_SECONDS       turn time limit (default 60, 1..600)
  RECONNECT_SECONDS  grace period to come back after a disconnect (default 30, 0..600)
  TURN_TIMER_THREAD  0 disables the background ticker (tests drive it by hand)
"""
import os
import secrets
from dataclasses import dataclass

BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))
DEV_SECRET_FILE = os.path.join(BACKEND_DIR, '.dev_secret_key')
ENVIRONMENTS = ('development', 'staging', 'production')
MIN_SECRET_LENGTH = 32
# Publicly known keys (this one was the old hardcoded fallback) -- never accepted in production.
KNOWN_INSECURE_KEYS = {'dev-secret-key-change-in-production'}
GENERATE_HINT = 'generate one with: python -c "import secrets; print(secrets.token_hex(32))"'


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    env: str
    secret_key: str
    database_url: str
    port: int
    turn_seconds: int
    reconnect_seconds: int
    turn_timer_thread: bool

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

    return Settings(
        env=env,
        secret_key=secret,
        database_url=environ.get('DATABASE_URL') or f"sqlite:///{os.path.join(BACKEND_DIR, 'game.db')}",
        port=_int(environ, 'PORT', 5000, 1, 65535),
        turn_seconds=_int(environ, 'TURN_SECONDS', 60, 1, 600),
        reconnect_seconds=_int(environ, 'RECONNECT_SECONDS', 30, 0, 600),
        turn_timer_thread=(environ.get('TURN_TIMER_THREAD', '1') != '0'),
    )
