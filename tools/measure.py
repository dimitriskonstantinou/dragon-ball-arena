"""
Before/after snapshot of the project: tests, coverage, lint, code size,
asset weight, roster/content integrity and network payload size.

Run from the repo root before and after any change, then diff the two:

    python tools/measure.py                     # print report
    python tools/measure.py --save before.md    # also write it to a file

Never touches backend/game.db -- the integration smoke test is pointed at a
throwaway SQLite file in the system temp dir. coverage/pyflakes/Pillow are
optional: if they're not installed, those sections just say "skipped".
"""
import argparse
import copy
import glob
import json
import os
import re
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKEND = os.path.join(ROOT, 'backend')
FRONTEND = os.path.join(ROOT, 'frontend')
PHOTOS = os.path.join(BACKEND, 'photos')

lines = []


def out(s=''):
    lines.append(s)
    print(s)


def run(args, env_extra=None):
    env = dict(os.environ, **(env_extra or {}))
    start = time.perf_counter()
    proc = subprocess.run(args, cwd=BACKEND, env=env, capture_output=True, text=True,
                          encoding='utf-8', errors='replace')
    return proc, time.perf_counter() - start


def has_module(name):
    return subprocess.run([sys.executable, '-c', f'import {name}'], capture_output=True).returncode == 0


def section_tests(tmp_db_url):
    out('## Tests')
    out('| Suite | Result | PASS | FAIL | Time |')
    out('|---|---|---|---|---|')
    for name, script, env in (('engine', 'test_game_engine.py', None),
                              ('smoke', 'test_integration_smoke.py', {'DATABASE_URL': tmp_db_url})):
        proc, secs = run([sys.executable, script], env)
        text = proc.stdout + proc.stderr
        passes = len(re.findall(r'\bPASS\b', text))
        fails = len(re.findall(r'\bFAIL\b', text))
        result = 'ok' if proc.returncode == 0 else f'EXIT {proc.returncode}'
        out(f'| {name} | {result} | {passes} | {fails} | {secs:.2f}s |')
        for line in text.splitlines():
            if 'FAIL' in line or 'Traceback' in line or 'Error' in line:
                out(f'    {line.strip()}')
    out()


def section_coverage(tmp_db_url):
    out('## Coverage (backend, tests excluded)')
    if not has_module('coverage'):
        out('skipped (pip install coverage)\n')
        return
    data_file = os.path.join(tempfile.gettempdir(), 'dba_measure.coverage')
    if os.path.exists(data_file):
        os.remove(data_file)
    base = [sys.executable, '-m', 'coverage', 'run', f'--data-file={data_file}', '--source=.',
            '--omit=test_*']
    run(base + ['test_game_engine.py'])
    run(base[:4] + ['-a'] + base[4:] + ['test_integration_smoke.py'], {'DATABASE_URL': tmp_db_url})
    proc, _ = run([sys.executable, '-m', 'coverage', 'report', f'--data-file={data_file}'])
    out('```')
    out(proc.stdout.strip())
    out('```\n')


def section_lint():
    out('## Lint (pyflakes)')
    if not has_module('pyflakes'):
        out('skipped (pip install pyflakes)\n')
        return
    proc, _ = run([sys.executable, '-m', 'pyflakes'] + sorted(glob.glob(os.path.join(BACKEND, '*.py'))))
    issues = [l for l in proc.stdout.splitlines() if l.strip()]
    out(f'{len(issues)} issue(s)')
    for l in issues:
        out(f'    {l.replace(ROOT + os.sep, "")}')
    out()


def section_size():
    out('## Code size')
    out('| File | Lines | Bytes |')
    out('|---|---|---|')
    files = sorted(glob.glob(os.path.join(BACKEND, '*.py')) +
                   glob.glob(os.path.join(FRONTEND, '*.*')))
    total_l = total_b = 0
    for f in files:
        with open(f, encoding='utf-8') as fh:
            n = sum(1 for _ in fh)
        b = os.path.getsize(f)
        total_l += n
        total_b += b
        out(f'| {os.path.relpath(f, ROOT)} | {n} | {b} |')
    out(f'| **total** | **{total_l}** | **{total_b}** |')
    fe = sum(os.path.getsize(f) for f in glob.glob(os.path.join(FRONTEND, '*.*')))
    out(f'\nFrontend first-load (html+css+js, excl. CDN socket.io): {fe / 1024:.1f} KB\n')


def image_info(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            return im.format, im.size
    except ImportError:
        return None, None


def section_assets():
    out('## Assets (backend/photos)')
    imgs = sorted(glob.glob(os.path.join(PHOTOS, '*', '*')))
    total = sum(os.path.getsize(p) for p in imgs)
    out(f'{len(imgs)} files, {total / 1024:.0f} KB total')
    ext_fmt = {'.png': 'PNG', '.jpg': 'JPEG', '.jpeg': 'JPEG', '.webp': 'WEBP'}
    mismatched, oversized = [], []
    for p in imgs:
        fmt, size = image_info(p)
        if fmt is None:
            continue
        if ext_fmt.get(os.path.splitext(p)[1].lower()) != fmt:
            mismatched.append(f'{os.path.relpath(p, PHOTOS)} is {fmt}')
        if os.sep + 'skills' + os.sep in p and max(size) > 256:
            oversized.append((os.path.getsize(p), f'{os.path.relpath(p, PHOTOS)} {size[0]}x{size[1]}'))
    if image_info(imgs[0])[0] is None if imgs else True:
        out('format/dimension checks skipped (pip install pillow)')
    else:
        out(f'extension != real format: {len(mismatched)}')
        out(f'skill icons > 256px (rendered at 32px): {len(oversized)}, '
            f'{sum(b for b, _ in oversized) / 1024:.0f} KB')
    out()


def section_content():
    out('## Roster / content integrity')
    sys.path.insert(0, BACKEND)
    import characters
    import game_engine
    chars = characters.CHARACTERS
    skills = [(cid, s) for cid, c in chars.items() for s in c['skills']]
    out(f'{len(chars)} characters, {len(skills)} skills')

    referenced = set()
    missing = []
    for cid, c in chars.items():
        referenced.add(os.path.normpath(c['image']))
        if not os.path.exists(os.path.join(PHOTOS, c['image'])):
            missing.append(c['image'])
        for s in c['skills']:
            imgs = [s.get('image')] + [e.get('primed_image') for e in s.get('effects', [])]
            for img in filter(None, imgs):
                rel = os.path.normpath(os.path.join('skills', img))
                referenced.add(rel)
                if not os.path.exists(os.path.join(PHOTOS, rel)):
                    missing.append(rel)
    on_disk = {os.path.relpath(p, PHOTOS) for p in glob.glob(os.path.join(PHOTOS, '*', '*'))}
    out(f'images referenced but missing: {len(missing)} {missing if missing else ""}')
    unused = sorted(on_disk - referenced)
    out(f'images on disk but unreferenced: {len(unused)} {unused if unused else ""}')

    # Descriptions that hardcode a cost suffix ("| 1 Eng, 1 Rand") duplicate
    # the cost dict and drift out of sync with it.
    hardcoded = [f'{cid}.{s["id"]}' for cid, s in skills if re.search(r'\|\s*\d', s.get('description', ''))]
    out(f'descriptions with hardcoded cost text: {len(hardcoded)}')

    # Sample 3v3 payload, same shape app.py broadcasts on every update-state.
    ids = list(chars)[:3] or []
    team = [dict(copy.deepcopy(chars[i]), defense=0) for i in (ids * 3)[:3]]
    game = {'roomId': 'x', 'turn': 'p1', 'winner': None, 'turn_count': 1, 'pending_moves': [],
            'players': {k: {'id': 'sid', 'resources': game_engine.roll_dice(3), 'status': [],
                            'team': copy.deepcopy(team)} for k in ('p1', 'p2')}}
    out(f'update-state payload (sample 3v3): {len(json.dumps(game))} bytes')
    out()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--save', help='also write the report to this file')
    args = ap.parse_args()

    tmp_db = os.path.join(tempfile.gettempdir(), 'dba_measure_smoke.db')
    if os.path.exists(tmp_db):
        os.remove(tmp_db)
    tmp_db_url = 'sqlite:///' + tmp_db.replace('\\', '/')

    out(f'# Measurement - {time.strftime("%Y-%m-%d %H:%M")}')
    try:
        head = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(['git', 'status', '--porcelain'], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        out(f'git: {head}{" (uncommitted changes)" if dirty else ""}\n')
    except FileNotFoundError:
        out()

    section_tests(tmp_db_url)
    section_coverage(tmp_db_url)
    section_lint()
    section_size()
    section_assets()
    section_content()

    if args.save:
        with open(args.save, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
