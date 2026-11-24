"""
Proves the production Docker image works (DEPLOY_PLAN Stage 3). Run from the repo root:

    python tools/check_container.py        (or: python tests.py --container)

Needs Docker running. Builds the image from the Dockerfile, then -- against fresh
databases in the throwaway PostgreSQL container that tests.py uses -- checks:
  1. the image: Python 3.12, unprivileged user, no local database / secrets / tests inside
  2. a start with real PRODUCTION settings: gunicorn + gevent, migrations on PostgreSQL,
     /healthz, Secure + HttpOnly + SameSite cookie, foreign origins refused, Docker HEALTHCHECK
  3. production refuses to start without its required settings
  4. the backend test suites pass on the image's Python (3.12)
  5. the browser tests play full matches through two containers over real websockets
Prints PASS/FAIL lines like the other suites; exit code 1 on any failure. Containers and
databases it creates are removed afterwards (the image `dragon-ball-arena:test` is kept).
"""
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests  # noqa: E402  (the PostgreSQL container helpers)

IMAGE = 'dragon-ball-arena:test'
FAILURES = []
NO_PATH_CONVERSION = dict(os.environ, MSYS_NO_PATHCONV='1')   # Git Bash would rewrite /container/paths


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}", flush=True)
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}", flush=True)


def docker(*args, timeout=600):
    return subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, env=NO_PATH_CONVERSION)


def http(url, data=None, headers=None):
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, dict(r.headers), r.read().decode('utf-8', 'replace')
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode('utf-8', 'replace')
    except OSError:
        return None, {}, ''


def wait_healthy(port, seconds=60):
    for _ in range(seconds):
        if http(f'http://127.0.0.1:{port}/healthz')[0] == 200:
            return True
        time.sleep(1)
    return False


def pg_url_for(database):
    """URL of `database` as seen from inside a container (the host's port 55432)."""
    # In the form hosts hand out (no '+psycopg'): config.py must turn it into our driver's.
    return f'postgresql://dba:dbatest@host.docker.internal:55432/{database}'


def run_container(name, port, env):
    docker('rm', '-f', name)
    # host.docker.internal = the machine running Docker (where the test Postgres listens). Docker Desktop
    # provides it; on Linux (CI runners) it must be mapped explicitly.
    args = ['run', '-d', '--name', name, '--add-host=host.docker.internal:host-gateway']
    if port:
        args += ['-p', f'{port}:8000']
    for k, v in env.items():
        args += ['-e', f'{k}={v}']
    return docker(*args, IMAGE)


def main():
    pg_admin, why_not = tests.ensure_postgres()
    if not pg_admin:
        print(f"  FAIL: PostgreSQL container unavailable: {why_not}")
        sys.exit(1)

    print("build:", flush=True)
    start = time.perf_counter()
    version = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                             text=True).stdout.strip() or 'unknown'
    build = docker('build', '--build-arg', f'APP_VERSION={version}', '-t', IMAGE, ROOT, timeout=1200)
    check(f"the image builds ({time.perf_counter() - start:.0f}s)", build.returncode == 0, build.stderr[-600:])
    if build.returncode:
        sys.exit(1)
    size = docker('image', 'inspect', '-f', '{{.Size}}', IMAGE).stdout.strip()
    print(f"  image size: {int(size) // 1_000_000} MB" if size.isdigit() else "  image size: ?")

    print("image contents:", flush=True)
    inside = docker('run', '--rm', IMAGE, 'sh', '-c',
                    'python --version; whoami; ls -a /app/backend; ls /app/frontend').stdout
    check("runs Python 3.12 (the production version)", 'Python 3.12.' in inside, inside[:80])
    check("runs as the unprivileged user 'arena', not root", '\narena\n' in inside, inside[:120])
    check("contains no local database, secret key or test files",
          not any(x in inside for x in ('game.db', '.dev_secret_key', 'test_game_engine.py')), inside)
    check("contains the server and the frontend", 'app.py' in inside and 'index.html' in inside)

    containers, databases = [], []
    try:
        print("production settings:", flush=True)
        _, prod_db = tests.pg_database(pg_admin)
        databases.append(prod_db)
        key = secrets.token_hex(32)
        prod_env = {'ENV': 'production', 'SECRET_KEY': key, 'ALLOWED_ORIGINS': 'https://arena.example',
                    'TRUSTED_PROXIES': '1', 'DATABASE_URL': pg_url_for(prod_db), 'LOG_FORMAT': 'json'}
        run_container('dba-check-prod', 18100, prod_env)
        containers.append('dba-check-prod')
        up = wait_healthy(18100)
        logs = docker('logs', 'dba-check-prod').stdout + docker('logs', 'dba-check-prod').stderr
        check("starts under gunicorn with the gevent worker", up and 'Using worker: gevent' in logs, logs[-600:])
        check("...builds the schema on PostgreSQL by running the migrations at startup",
              'PostgresqlImpl' in logs and 'Running upgrade' in logs, logs[-400:])
        check(f"...and logs which build is running (version={version}) -- every deploy is visible in the logs",
              f'Server starting: version={version} env=production' in logs, logs[-400:])
        status, _, body = http('http://127.0.0.1:18100/healthz')
        check("/healthz answers 200 {status: ok}", status == 200 and '"ok"' in body, (status, body))
        check("the game page and the self-hosted socket.io client are served",
              http('http://127.0.0.1:18100/')[0] == 200
              and http('http://127.0.0.1:18100/vendor/socket.io-4.5.4.min.js')[0] == 200)
        name = 'Prod' + uuid.uuid4().hex[:6]
        status, headers, _ = http('http://127.0.0.1:18100/api/register',
                                  data=f'{{"username":"{name}","email":"{name}@x.io","password":"secret12"}}'.encode(),
                                  headers={'Content-Type': 'application/json'})
        cookie = headers.get('Set-Cookie', '')
        check("registering works and the login cookie is Secure, HttpOnly, SameSite=Lax",
              status == 201 and all(f in cookie for f in ('Secure', 'HttpOnly', 'SameSite=Lax')), (status, cookie[-80:]))
        status = http('http://127.0.0.1:18100/socket.io/?EIO=4&transport=polling',
                      headers={'Origin': 'https://evil.example'})[0]
        check("a game connection from a foreign website is refused", status == 400, status)
        held = subprocess.run(['docker', 'exec', '-i', 'dba-check-prod', 'python', '-'], input=MANY_WEBSOCKETS,
                              capture_output=True, text=True, timeout=180, env=NO_PATH_CONVERSION)
        check("1,200 websockets can be open at once and /healthz still answers (gunicorn's default stops at 1,000)",
              held.stdout.strip() == 'open=1200 healthz=200', (held.stdout + held.stderr)[-300:])
        health = ''
        for _ in range(45):
            health = docker('inspect', '-f', '{{.State.Health.Status}}', 'dba-check-prod').stdout.strip()
            if health != 'starting':
                break
            time.sleep(1)
        check("Docker's own HEALTHCHECK reports the container healthy", health == 'healthy', health)
        logs = docker('logs', 'dba-check-prod').stdout + docker('logs', 'dba-check-prod').stderr
        lines = [line for line in logs.splitlines() if line.strip()]
        not_json = []
        for line in lines:
            try:
                json.loads(line)
            except ValueError:
                not_json.append(line)
        check(f"with LOG_FORMAT=json every log line ({len(lines)}, gunicorn's included) is one JSON object",
              lines and not not_json, not_json[:3])
        check("...including the request log and the account events",
              '"arena.http"' in logs and 'Account created: user=' in logs, logs[-500:])
        check("...and no log line contains the database password or the secret key",
              'dbatest' not in logs and key not in logs, '(a secret is in the logs)')

        print("refuses to start insecurely:", flush=True)
        for missing in ('SECRET_KEY', 'DATABASE_URL'):
            env = {k: v for k, v in prod_env.items() if k != missing}
            name = f'dba-check-refuse-{missing.lower()}'
            run_container(name, 0, env)
            containers.append(name)
            state = ''
            for _ in range(60):     # gunicorn must STOP (not restart the worker forever)
                state = docker('inspect', '-f', '{{.State.Status}} {{.State.ExitCode}}', name).stdout.strip()
                if state.startswith('exited'):
                    break
                time.sleep(1)
            out = docker('logs', name).stdout + docker('logs', name).stderr
            check(f"production without {missing} stops with a clear configuration error (no restart loop)",
                  state.startswith('exited') and not state.endswith(' 0')
                  and f'Configuration error: {missing} is required' in out
                  and out.count('Booting worker') <= 1, (state, out[-300:]))

        print("backend suites on the image's Python 3.12:", flush=True)
        suites = docker('run', '--rm', '-v', f'{ROOT}:/src:ro', '-w', '/src/backend',
                        '-e', 'PYTHONDONTWRITEBYTECODE=1', '-e', f'SECRET_KEY={key}', '-e', 'REGISTER_LIMIT=100000',
                        '-e', 'SOCKETIO_ASYNC_MODE=threading', '-e', 'DATABASE_URL=sqlite:////tmp/smoke.db', IMAGE,
                        'sh', '-c', 'for t in test_game_engine.py test_content.py test_rate_limit.py '
                        'test_integration_smoke.py; do python $t > /tmp/o 2>&1; '
                        'echo "$t exit=$? fail=$(grep -cE "^\\s*FAIL" /tmp/o) pass=$(grep -cE "^\\s*PASS" /tmp/o)"; done; '
                        'env -u DATABASE_URL python test_migrations.py > /tmp/o 2>&1; '
                        'echo "test_migrations.py exit=$? fail=$(grep -cE "^\\s*FAIL" /tmp/o) pass=$(grep -cE "^\\s*PASS" /tmp/o)"',
                        timeout=900)
        for line in suites.stdout.strip().splitlines():
            check(f"Python 3.12: {line}", ' exit=0 fail=0 ' in line + ' ', line)
        if not suites.stdout.strip():
            check("Python 3.12 suites ran", False, suites.stderr[-400:])

        print("full matches in a real browser through the containers:", flush=True)
        for label, port, extra in (('main', 18101, {}), ('fast', 18102, {'TURN_SECONDS': '2', 'RECONNECT_SECONDS': '3'})):
            _, db = tests.pg_database(pg_admin)
            databases.append(db)
            # development mode: production correctly refuses plain-http origins, and this local test has no TLS
            run_container(f'dba-check-{label}', port, {'SECRET_KEY': key, 'REGISTER_LIMIT': '100000',
                                                       'DATABASE_URL': pg_url_for(db), **extra})
            containers.append(f'dba-check-{label}')
        ready = wait_healthy(18101) and wait_healthy(18102)
        check("(both game containers are up)", ready)
        text_logs = docker('logs', 'dba-check-main').stdout + docker('logs', 'dba-check-main').stderr
        first = [line for line in text_logs.splitlines() if line.strip()][:3]
        check("gunicorn's own lines use the app's log format (UTC time, level, logger)",
              first and all(re.match(r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z (INFO|WARNING|DEBUG) \S+: ', line)
                            for line in first), first)
        e2e = subprocess.run([sys.executable, 'test_browser_e2e.py'], cwd=os.path.join(ROOT, 'backend'),
                             env=dict(os.environ, E2E_URL='http://127.0.0.1:18101', E2E_FAST_URL='http://127.0.0.1:18102'),
                             capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=900)
        passed = sum(1 for l in e2e.stdout.splitlines() if l.strip().startswith('PASS'))
        failed = [l.strip() for l in e2e.stdout.splitlines() if l.strip().startswith('FAIL')]
        check(f"all browser tests pass through the production image ({passed} checks: matches, reload, surrender, "
              f"timeouts, disconnects)", e2e.returncode == 0 and not failed and passed > 0, failed[:3] or e2e.stdout[-400:])
        ws = subprocess.run([sys.executable, '-c', WEBSOCKET_PROBE, 'http://127.0.0.1:18101'], capture_output=True,
                            text=True, timeout=120)
        check("the browser really uses a websocket (not the long-polling fallback)",
              ws.stdout.strip() == 'websocket', ws.stdout.strip() or ws.stderr[-300:])
    finally:
        for c in containers:
            docker('rm', '-f', c)
        for db in databases:
            tests.pg_database(pg_admin, create=False, name=db)

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("Container checks passed.")


# Runs INSIDE the container: opens real websockets (handshake answered with 101), holds them, asks /healthz.
MANY_WEBSOCKETS = r'''
import socket, urllib.request
REQ = (b"GET /socket.io/?EIO=4&transport=websocket HTTP/1.1\r\nHost: 127.0.0.1:8000\r\nUpgrade: websocket\r\n"
       b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n")
held = []
for _ in range(1200):
    try:
        s = socket.create_connection(("127.0.0.1", 8000), timeout=5)
        s.sendall(REQ)
        if not s.recv(64).startswith(b"HTTP/1.1 101"):
            break
    except OSError:
        break
    held.append(s)
try:
    health = urllib.request.urlopen("http://127.0.0.1:8000/healthz", timeout=5).status
except Exception as e:
    health = type(e).__name__
print(f"open={len(held)} healthz={health}")
'''

WEBSOCKET_PROBE = r'''
import sys, uuid
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.goto(sys.argv[1])
    page.wait_for_selector("#login-form a", state="visible")
    page.click("#login-form a")
    name = "ws" + uuid.uuid4().hex[:6]
    page.fill("#register-username", name); page.fill("#register-email", name + "@x.io")
    page.fill("#register-password", "secret12")
    page.click("#register-form .big-btn")
    page.wait_for_selector("#lobby-screen", state="visible")
    page.wait_for_function("socket.io.engine && socket.io.engine.transport.name === 'websocket'", timeout=10000)
    print(page.evaluate("socket.io.engine.transport.name"))
    b.close()
'''

if __name__ == '__main__':
    main()
