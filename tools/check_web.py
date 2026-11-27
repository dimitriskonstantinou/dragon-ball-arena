"""
Builds and checks the new interface (web/: React + TypeScript + Vite), Step 46. Run from the repo root:

    python tools/check_web.py        (python tests.py runs it as the `web` suite)

Uses the local Node.js when it is new enough (Vite needs >= 20.19 / 22.12), otherwise the same build in a
node:24 Docker container -- so it works on any machine with either. Checks: exact versions from the lock file
(npm ci), 0 known vulnerabilities, the TypeScript check, the production build, its size, and that the build
loads nothing from another site. Leaves web/dist for the browser tests and the dev server (/next/).
Prints PASS/FAIL lines like the other suites; exit code 1 on any failure.
"""
import glob
import gzip
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, 'web')
NODE_IMAGE = 'node:24.11.1-slim'
MIN_NODE = (22, 12)
FAILURES = []


def check(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}", flush=True)
    else:
        FAILURES.append(name)
        print(f"  FAIL: {name}  {detail}", flush=True)


def local_node():
    node = shutil.which('node')
    if not node:
        return False
    version = subprocess.run([node, '--version'], capture_output=True, text=True).stdout.strip()
    m = re.match(r'v(\d+)\.(\d+)', version)
    return bool(m) and (int(m.group(1)), int(m.group(2))) >= MIN_NODE


def npm(args, use_docker):
    if use_docker:
        cmd = ['docker', 'run', '--rm', '-v', f'{WEB}:/web', '-w', '/web', NODE_IMAGE, 'npm', *args]
        env = dict(os.environ, MSYS_NO_PATHCONV='1')
    else:
        cmd = [shutil.which('npm') or 'npm', *args]
        env = os.environ
    return subprocess.run(cmd, cwd=WEB, capture_output=True, text=True, encoding='utf-8', errors='replace', env=env,
                          timeout=900, shell=(os.name == 'nt' and not use_docker))


def main():
    use_docker = not local_node()
    print(f"web: using {'Docker ' + NODE_IMAGE if use_docker else 'local Node.js'}", flush=True)
    if use_docker and not shutil.which('docker'):
        print("  FAIL: neither Node.js >= 22.12 nor Docker is available")
        sys.exit(1)

    lock = json.load(open(os.path.join(WEB, 'package-lock.json'), encoding='utf-8'))
    pinned = json.load(open(os.path.join(WEB, 'package.json'), encoding='utf-8'))
    exact = all(re.fullmatch(r'\d+\.\d+\.\d+', v) for part in ('dependencies', 'devDependencies')
                for v in pinned.get(part, {}).values())
    check("every package is pinned to an exact version", exact, pinned)
    check("the lock file records an integrity hash for every downloaded package",
          all(p.get('integrity') for name, p in lock['packages'].items() if name and not p.get('link')))

    ci = npm(['ci', '--no-fund', '--no-audit'], use_docker)
    check("npm ci installs exactly the lock file", ci.returncode == 0, (ci.stdout + ci.stderr)[-400:])
    audit = npm(['audit', '--json'], use_docker)
    try:
        found = json.loads(audit.stdout)['metadata']['vulnerabilities']
        total = sum(found.values())
    except (ValueError, KeyError):
        found, total = audit.stdout[-200:], -1
    check("npm audit: 0 known vulnerabilities", total == 0, found)
    build = npm(['run', 'build'], use_docker)
    check("TypeScript check + production build", build.returncode == 0, (build.stdout + build.stderr)[-800:])
    if build.returncode:
        sys.exit(1)

    dist = os.path.join(WEB, 'dist')
    files = [f for f in glob.glob(os.path.join(dist, '**', '*'), recursive=True) if os.path.isfile(f)]
    raw = sum(os.path.getsize(f) for f in files)
    packed = sum(len(gzip.compress(open(f, 'rb').read(), 9)) for f in files)
    print(f"  web build: {len(files)} files, {raw / 1024:.1f} KB, {packed / 1024:.1f} KB gzip", flush=True)
    check("the build stays below 120 KB gzip (React + socket.io-client today: ~82 KB)", packed < 120 * 1024, packed)
    index = open(os.path.join(dist, 'index.html'), encoding='utf-8').read()
    check("the page loads its files from /next/assets/ (hashed names: cacheable for a year)",
          re.search(r'src="/next/assets/index-[\w-]+\.js"', index) is not None, index)
    texts = ''.join(open(f, encoding='utf-8', errors='replace').read() for f in files if f.endswith(('.js', '.css', '.html')))
    foreign = sorted(set(re.findall(r'(?:src|href)=["\']?(https?://[^"\' >]+)', texts) +
                         re.findall(r'url\((https?://[^)]+)\)', texts) + re.findall(r'import\(["\'](https?://[^"\']+)', texts)))
    check("nothing is loaded from another site (Step 21)", foreign == [], foreign[:5])

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        sys.exit(1)
    print("Web checks passed.")


if __name__ == '__main__':
    main()
