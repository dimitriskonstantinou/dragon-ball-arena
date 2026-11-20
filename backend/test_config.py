"""
Tests for config.py (environment settings). Run with: python test_config.py

Unit checks use fake environments and a temporary dev-key file; the startup
checks launch real interpreters importing app.py (temporary database, so the
real backend/game.db is never touched).
"""
import os
import subprocess
import sys
import tempfile

import config

FAILURES = []
BACKEND = os.path.dirname(os.path.abspath(__file__))
GOOD_KEY = 'k' * 64


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}")


def load(env, dev_file=None):
    """config.load with a fake environment; returns (settings, error message)."""
    dev_file = dev_file or os.path.join(tempfile.mkdtemp(), 'dev_key')
    try:
        return config.load(env, dev_secret_file=dev_file), None
    except config.ConfigError as e:
        return None, str(e)


def test_development_defaults():
    tmp = tempfile.mkdtemp()
    dev_file = os.path.join(tmp, 'dev_key')
    s, err = load({}, dev_file)
    check("no settings at all -> development with sensible defaults",
          err is None and s.env == 'development' and s.turn_seconds == 60 and s.reconnect_seconds == 30
          and s.port == 5000 and s.turn_timer_thread and s.database_url.endswith('game.db'), (s, err))
    check("the dev secret key is random (not a key from the source code) and long",
          len(s.secret_key) >= config.MIN_SECRET_LENGTH and s.secret_key not in config.KNOWN_INSECURE_KEYS)
    s2, _ = load({}, dev_file)
    check("...and stays the same across restarts (kept in the local key file)", s2.secret_key == s.secret_key)
    s3, _ = load({})
    check("...but differs between machines (a fresh key file gets a fresh key)", s3.secret_key != s.secret_key)
    s4, _ = load({'SECRET_KEY': 'my-own-dev-key'}, dev_file)
    check("an explicit SECRET_KEY always wins in development", s4.secret_key == 'my-own-dev-key')


def test_production_requires_a_real_secret():
    for env in ('production', 'staging'):
        _, err = load({'ENV': env})
        check(f"{env} without SECRET_KEY refuses to start, saying how to make one",
              err and 'SECRET_KEY is required' in err and 'secrets.token_hex' in err, err)
        _, err = load({'ENV': env, 'SECRET_KEY': 'short'})
        check(f"{env} with a short SECRET_KEY refuses to start", err and 'at least' in err, err)
        _, err = load({'ENV': env, 'SECRET_KEY': 'dev-secret-key-change-in-production'})
        check(f"{env} with the old public key refuses to start", err and 'publicly known' in err, err)
        s, err = load({'ENV': env, 'SECRET_KEY': GOOD_KEY})
        check(f"{env} with a proper SECRET_KEY starts", err is None and s.secret_key == GOOD_KEY and s.is_production_like,
              err)
    _, err = load({'ENV': 'prod'})
    check("an unknown ENV value is rejected (typos must not silently mean development)", err and 'ENV must be' in err,
          err)
    s, err = load({'ENV': ' Production ', 'SECRET_KEY': GOOD_KEY})
    check("ENV is case/space tolerant", err is None and s.env == 'production', err)


def test_number_settings_are_validated():
    for name, bad in (('TURN_SECONDS', 'abc'), ('TURN_SECONDS', '0'), ('TURN_SECONDS', '601'),
                      ('RECONNECT_SECONDS', '-1'), ('PORT', '70000'), ('PORT', '5.5')):
        _, err = load({name: bad})
        check(f"{name}={bad!r} is rejected with a clear message", err and name in err, err)
    s, err = load({'TURN_SECONDS': '2', 'RECONNECT_SECONDS': '0', 'PORT': '8080', 'TURN_TIMER_THREAD': '0'})
    check("valid values are used (incl. the short limits the browser tests use)",
          err is None and (s.turn_seconds, s.reconnect_seconds, s.port, s.turn_timer_thread) == (2, 0, 8080, False), err)


def start_app(extra_env):
    env = {k: v for k, v in os.environ.items() if k not in ('SECRET_KEY', 'ENV')}
    env.update(extra_env, TURN_TIMER_THREAD='0',
               DATABASE_URL='sqlite:///' + os.path.join(tempfile.mkdtemp(), 'cfg.db').replace('\\', '/'))
    return subprocess.run([sys.executable, '-c', 'import app; print("started", app.app.config["SECRET_KEY"] != "")'],
                          cwd=BACKEND, env=env, capture_output=True, text=True, timeout=120)


def test_real_server_startup():
    proc = start_app({'ENV': 'production'})
    check("a real production start without SECRET_KEY exits with a configuration error (no traceback)",
          proc.returncode != 0 and 'Configuration error: SECRET_KEY is required' in proc.stderr
          and 'Traceback' not in proc.stderr, (proc.returncode, proc.stderr[-300:]))
    proc = start_app({'ENV': 'production', 'SECRET_KEY': GOOD_KEY})
    check("a real production start with a proper SECRET_KEY works", proc.returncode == 0 and 'started True' in proc.stdout,
          (proc.returncode, proc.stderr[-300:]))
    proc = start_app({'TURN_SECONDS': 'soon'})
    check("a bad number setting stops the real server with a clear message",
          proc.returncode != 0 and 'TURN_SECONDS must be a whole number' in proc.stderr, proc.stderr[-300:])


TESTS = [v for k, v in list(globals().items()) if k.startswith('test_')]

if __name__ == '__main__':
    for t in TESTS:
        print(f"{t.__name__}:")
        t()
    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        raise SystemExit(1)
    print(f"All {len(TESTS)} test functions passed.")
