"""
One command that checks the whole project, before and after every change.

    python tests.py                     # everything (~80 s): all suites + probe + coverage + lint + guards
    python tests.py --quick             # fast loop (~12 s): engine, content, rate limit, smoke, runner gates
    python tests.py --no-browser        # everything except the Playwright browser run
    python tests.py --update-baseline   # after an INTENDED change: accept the new numbers (explain why in the report)
    python tests.py --save report.md    # also write the report to a file

Green means more than "no test failed". Every run is compared with the baseline
(tools/tests_baseline.json, committed) and fails when:
  - a suite fails, crashes, or prints FAIL
  - a suite runs FEWER checks than the baseline (a test silently deleted/skipped)
  - the exploit probe confirms a problem that isn't on the known-open list
  - the per-player update-state payload grows (fixed sample, no random dice)
  - coverage drops by more than 1 point, or pyflakes reports more issues
  - the real backend/game.db was touched (size/mtime/content) -- tests must use temp databases
Engine speed is compared too, but only warns (timing on a dev machine is noisy).

Exit code 0 = all green, 1 = problems (listed at the end). Never touches backend/game.db.
"""
import argparse
import copy
import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.join(ROOT, 'backend')
BASELINE_FILE = os.path.join(ROOT, 'tools', 'tests_baseline.json')
REAL_DB = os.path.join(BACKEND, 'game.db')

# name, script (in backend/), part of --quick, runs under coverage
SUITES = [
    ('engine', 'test_game_engine.py', True, True),
    ('content', 'test_content.py', True, True),
    ('config', 'test_config.py', False, True),
    ('rate_limit', 'test_rate_limit.py', True, True),
    ('migrations', 'test_migrations.py', False, False),
    ('smoke', 'test_integration_smoke.py', True, True),
    ('browser', 'test_browser_e2e.py', False, False),
]

PAYLOAD_TOLERANCE_BYTES = 0      # any growth must be accepted on purpose (--update-baseline)
COVERAGE_TOLERANCE_POINTS = 1.0
SPEED_WARN_FACTOR = 1.5

lines = []


def out(s=''):
    lines.append(s)
    print(s, flush=True)


# --- pure gate logic (unit-tested in tools/test_tests_runner.py) -------------------------------------

def count_checks(text):
    """PASS / FAIL / SKIPPED lines in a suite's output."""
    return (len(re.findall(r'^\s*PASS\b', text, re.M)), len(re.findall(r'^\s*FAIL\b', text, re.M)),
            len(re.findall(r'\bSKIPPED\b', text)))


def probe_confirmed(text):
    """Titles of the probe's [CONFIRMED] items (text up to the first ' (' detail)."""
    return sorted(re.split(r' \(', m, maxsplit=1)[0].strip()
                  for m in re.findall(r'^\[CONFIRMED\] (.*)$', text, re.M))


def compare(results, baseline):
    """results/baseline: {'suites': {name: {'pass', 'fail', 'skipped', 'exit'}}, 'probe_confirmed': [...],
    'payload_bytes', 'coverage', 'lint_issues', 'turn_ms'}. Returns (problems, warnings) as text lists."""
    problems, warnings = [], []
    base_suites = baseline.get('suites', {})
    for name, r in results.get('suites', {}).items():
        if r.get('not_run'):
            problems.append(f"{name}: couldn't run ({r['not_run']})")
            continue
        if r['exit'] != 0:
            problems.append(f"{name}: exited with code {r['exit']}")
        if r['fail']:
            problems.append(f"{name}: {r['fail']} check(s) FAILED")
        b = base_suites.get(name)
        if b:
            if r['pass'] < b['pass']:
                problems.append(f"{name}: only {r['pass']} checks passed, the baseline has {b['pass']} "
                                f"(a test was removed or stopped running?)")
            elif r['pass'] > b['pass']:
                warnings.append(f"{name}: {r['pass'] - b['pass']} new check(s) -- run --update-baseline to keep them")
            if r['skipped'] > b.get('skipped', 0):
                problems.append(f"{name}: {r['skipped']} SKIPPED (baseline {b.get('skipped', 0)})")
    if 'probe_confirmed' in results:
        new = sorted(set(results['probe_confirmed']) - set(baseline.get('probe_confirmed', [])))
        gone = sorted(set(baseline.get('probe_confirmed', [])) - set(results['probe_confirmed']))
        for title in new:
            problems.append(f"probe: NEW confirmed problem: {title}")
        for title in gone:
            warnings.append(f"probe: no longer confirmed (fixed?): {title} -- run --update-baseline")
    if 'payload_bytes' in results and 'payload_bytes' in baseline:
        grew = results['payload_bytes'] - baseline['payload_bytes']
        if grew > PAYLOAD_TOLERANCE_BYTES:
            problems.append(f"payload: update-state grew by {grew} bytes ({baseline['payload_bytes']} -> "
                            f"{results['payload_bytes']}); if intended, explain it and run --update-baseline")
        elif grew < 0:
            warnings.append(f"payload: {-grew} bytes smaller -- run --update-baseline to lock it in")
    if 'coverage' in results and 'coverage' in baseline:
        if results['coverage'] < baseline['coverage'] - COVERAGE_TOLERANCE_POINTS:
            problems.append(f"coverage dropped: {baseline['coverage']}% -> {results['coverage']}%")
    if 'lint_issues' in results and 'lint_issues' in baseline:
        if results['lint_issues'] > baseline['lint_issues']:
            problems.append(f"lint: {results['lint_issues']} pyflakes issue(s), baseline {baseline['lint_issues']}")
    if 'turn_ms' in results and baseline.get('turn_ms'):
        if results['turn_ms'] > baseline['turn_ms'] * SPEED_WARN_FACTOR:
            warnings.append(f"speed: a turn takes {results['turn_ms']:.3f} ms, baseline {baseline['turn_ms']:.3f} ms "
                            f"(re-run to rule out noise)")
    if results.get('real_db_changed'):
        problems.append("backend/game.db was modified during the run -- a test is using the real database!")
    return problems, warnings


# --- running things -----------------------------------------------------------------------------------

def run(args, env_extra=None, cwd=BACKEND):
    env = dict(os.environ, **(env_extra or {}))
    start = time.perf_counter()
    proc = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, encoding='utf-8', errors='replace')
    return proc, time.perf_counter() - start


def has_module(name):
    return subprocess.run([sys.executable, '-c', f'import {name}'], capture_output=True).returncode == 0


def browser_available():
    probe = "from playwright.sync_api import sync_playwright\nwith sync_playwright() as p: p.chromium.launch().close()"
    return subprocess.run([sys.executable, '-c', probe], capture_output=True).returncode == 0


def db_fingerprint():
    if not os.path.exists(REAL_DB):
        return None
    st = os.stat(REAL_DB)
    with open(REAL_DB, 'rb') as fh:
        return st.st_size, st.st_mtime_ns, hashlib.sha256(fh.read()).hexdigest()


def run_suites(names, tmp, use_coverage):
    results, details = {}, []
    cov_file = os.path.join(tmp, 'cov', '.coverage')
    os.makedirs(os.path.dirname(cov_file), exist_ok=True)
    out('| Suite | Result | PASS | FAIL | SKIPPED | Time |')
    out('|---|---|---|---|---|---|')
    for name, script, _, covered in [s for s in SUITES if s[0] in names]:
        env = {'DATABASE_URL': 'sqlite:///' + os.path.join(tmp, f'{name}.db').replace('\\', '/')}
        if name == 'browser' and not browser_available():
            results[name] = {'not_run': 'pip install -r requirements-dev.txt; python -m playwright install chromium'}
            out(f'| {name} | NOT RUN | | | | |')
            continue
        cmd = [sys.executable, script]
        if use_coverage and covered:
            cmd = [sys.executable, '-m', 'coverage', 'run', '-p', f'--data-file={cov_file}', '--source=.',
                   '--omit=test_*,migrations/*', script]
        proc, secs = run(cmd, env)
        text = proc.stdout + proc.stderr
        passed, failed, skipped = count_checks(text)
        results[name] = {'pass': passed, 'fail': failed, 'skipped': skipped, 'exit': proc.returncode}
        verdict = 'ok' if proc.returncode == 0 and not failed else 'FAILED'
        out(f'| {name} | {verdict} | {passed} | {failed} | {skipped} | {secs:.1f}s |')
        for line in text.splitlines():
            if re.match(r'^\s*PASS\b', line):
                continue
            if re.match(r'^\s*FAIL\b', line) or (proc.returncode != 0 and re.match(r'^\s*(Traceback|\w+Error\b)', line)):
                details.append(f'    {name}: {line.strip()[:200]}')
    for d in details:
        out(d)
    coverage = None
    if use_coverage:
        run([sys.executable, '-m', 'coverage', 'combine', f'--data-file={cov_file}'], cwd=os.path.dirname(cov_file))
        proc, _ = run([sys.executable, '-m', 'coverage', 'report', f'--data-file={cov_file}'])
        m = re.search(r'^TOTAL\s+\d+\s+\d+\s+(\d+)%', proc.stdout, re.M)
        coverage = float(m.group(1)) if m else None
    return results, coverage


def run_probe(tmp):
    proc, secs = run([sys.executable, os.path.join(ROOT, 'tools', 'probe_exploits.py')],
                     {'DATABASE_URL': 'sqlite:///' + os.path.join(tmp, 'probe.db').replace('\\', '/')}, cwd=ROOT)
    text = proc.stdout + proc.stderr
    return probe_confirmed(text), len(re.findall(r'^\[not reproduced\]', text, re.M)), secs


def lint_issues():
    files = sorted(glob.glob(os.path.join(BACKEND, '*.py'))) + [os.path.join(ROOT, 'tests.py')] \
        + sorted(glob.glob(os.path.join(ROOT, 'tools', '*.py')))
    proc, _ = run([sys.executable, '-m', 'pyflakes'] + files)
    return [l.replace(ROOT + os.sep, '') for l in proc.stdout.splitlines() if l.strip()]


def payload_and_speed():
    """update-state bytes for a FIXED sample (no random dice) and engine time per turn (min of rounds)."""
    sys.path.insert(0, BACKEND)
    import content_loader
    import game_engine
    chars = content_loader.catalog()
    ids = sorted(chars)[:3]

    def new_game():
        team = [dict(copy.deepcopy(chars[i]), defense=0) for i in ids]
        g = {'roomId': 'x', 'turn': 'p1', 'winner': None, 'turn_count': 1, 'pending_moves': [],
             'players': {k: {'id': 'sid', 'resources': list(game_engine.CHAKRA_TYPES[:3]), 'status': [],
                             'team': copy.deepcopy(team)} for k in ('p1', 'p2')}}
        return g
    payload = len(json.dumps(game_engine.view_for(new_game(), 'p1')))

    def one_round(n=300):
        g = new_game()
        for p in ('p1', 'p2'):
            for c in g['players'][p]['team']:
                c['health'] = c['maxHealth'] = 10 ** 9
                for _ in range(3):
                    game_engine.add_status(c, {'type': 'dot', 'value': 1, 'duration': 10 ** 6, 'tag': 'harmful'})
        start = time.perf_counter()
        for _ in range(n):
            game_engine.resolve_turn(g, [])
        return (time.perf_counter() - start) / n * 1000
    turn_ms = min(one_round() for _ in range(7))
    return payload, round(turn_ms, 3)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--quick', action='store_true', help='fast loop: engine, content, rate limit, smoke, gates')
    ap.add_argument('--no-browser', action='store_true', help='skip the Playwright browser run')
    ap.add_argument('--update-baseline', action='store_true', help='accept the current numbers as the new baseline')
    ap.add_argument('--save', help='also write the report to this file')
    args = ap.parse_args()

    started = time.perf_counter()
    tmp = tempfile.mkdtemp(prefix='dba_tests_')
    before = db_fingerprint()
    baseline = json.load(open(BASELINE_FILE, encoding='utf-8')) if os.path.exists(BASELINE_FILE) else {}
    mode = 'quick' if args.quick else 'full'
    head = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    out(f'# tests.py ({mode}) -- {time.strftime("%Y-%m-%d %H:%M")} -- git {head}{" + uncommitted changes" if dirty else ""}')
    out()

    names = [s[0] for s in SUITES if s[2]] if args.quick else [s[0] for s in SUITES]
    if args.no_browser and 'browser' in names:
        names.remove('browser')
    use_coverage = not args.quick and has_module('coverage')
    out('## Suites')
    results = {}
    suite_results, coverage = run_suites(names, tmp, use_coverage)
    results['suites'] = suite_results

    gates, _ = run([sys.executable, os.path.join('tools', 'test_tests_runner.py')], cwd=ROOT)
    g_pass, g_fail, _ = count_checks(gates.stdout + gates.stderr)
    results['suites']['runner_gates'] = {'pass': g_pass, 'fail': g_fail, 'skipped': 0, 'exit': gates.returncode}
    out(f'| runner_gates | {"ok" if gates.returncode == 0 and not g_fail else "FAILED"} | {g_pass} | {g_fail} | 0 | |')
    out()

    out('## Measurements')
    payload, turn_ms = payload_and_speed()
    results['payload_bytes'], results['turn_ms'] = payload, turn_ms
    out(f'update-state per player (fixed 3v3 sample): {payload} bytes (baseline {baseline.get("payload_bytes", "-")})')
    out(f'engine: {turn_ms:.3f} ms per turn with 18 ticking statuses (baseline {baseline.get("turn_ms", "-")})')
    if not args.quick:
        confirmed, not_reproduced, secs = run_probe(tmp)
        results['probe_confirmed'] = confirmed
        out(f'exploit probe: {len(confirmed)} confirmed, {not_reproduced} not reproduced ({secs:.1f}s)')
        for title in confirmed:
            out(f'    [CONFIRMED] {title}')
        if coverage is not None:
            results['coverage'] = coverage
            out(f'coverage (backend, tests excluded): {coverage:.0f}% (baseline {baseline.get("coverage", "-")}%)')
        if has_module('pyflakes'):
            issues = lint_issues()
            results['lint_issues'] = len(issues)
            out(f'lint (pyflakes): {len(issues)} issue(s) (baseline {baseline.get("lint_issues", "-")})')
            for i in issues:
                out(f'    {i}')
    results['real_db_changed'] = db_fingerprint() != before
    out(f'real backend/game.db untouched: {"NO" if results["real_db_changed"] else "yes"}')
    out()

    problems, warnings = compare(results, baseline)
    if args.update_baseline:
        if args.quick or args.no_browser:
            problems.append("--update-baseline needs a full run (no --quick / --no-browser)")
        elif any(p for p in problems if 'FAILED' in p or 'exited' in p or "couldn't run" in p or 'game.db' in p):
            problems.append("baseline NOT updated: fix the failures first")
        else:
            new_base = {
                'updated': time.strftime('%Y-%m-%d %H:%M'), 'git': head,
                'suites': {n: {k: r[k] for k in ('pass', 'skipped')} for n, r in results['suites'].items()},
                'probe_confirmed': results.get('probe_confirmed', []), 'payload_bytes': payload,
                'turn_ms': turn_ms, 'coverage': results.get('coverage'), 'lint_issues': results.get('lint_issues'),
            }
            with open(BASELINE_FILE, 'w', encoding='utf-8', newline='\n') as fh:
                json.dump(new_base, fh, indent=2)
                fh.write('\n')
            out(f'Baseline updated: {os.path.relpath(BASELINE_FILE, ROOT)} (commit it with the change)')
            problems, warnings = [], []

    out('## Verdict')
    for w in warnings:
        out(f'  WARN  {w}')
    for p in problems:
        out(f'  PROBLEM  {p}')
    total = time.perf_counter() - started
    out(f'{"ALL GREEN" if not problems else f"{len(problems)} PROBLEM(S)"} in {total:.0f}s')
    if args.save:
        with open(args.save, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
    sys.exit(1 if problems else 0)


if __name__ == '__main__':
    main()
