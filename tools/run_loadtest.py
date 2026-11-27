"""
Load test (DEPLOY_PLAN Stage 5): how many players does one server hold? Run from the repo root
(needs Docker running):

    python tools/run_loadtest.py                                   # 100, 500, 1000, 2000 players
    python tools/run_loadtest.py --levels 200 --seconds 1800       # soak: 30 min at 200 players (leaks)
    python tools/run_loadtest.py --save docs/measurements/<date>-loadtest.md

Runs the PRODUCTION image (gunicorn + gevent, production settings, JSON logs) on a fresh
PostgreSQL database, limited to --cpus / --memory (default 1 CPU / 1 GB: a small paid
instance), and the bots (tools/loadtest.py) in a separate container on the same Docker
network. Samples the server's CPU and RAM every ~2 s and reports per level: turns/s,
commit -> new-state latency (p50/p95/p99), CPU, RAM, server errors, refusals, drops.
Everything it starts is removed afterwards (the image is kept).
"""
import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import tests  # noqa: E402  (PostgreSQL container helpers)

IMAGE = 'dragon-ball-arena:loadtest'
NETWORK = 'dba-load'
SERVER = 'dba-load-server'
ENV = dict(os.environ, MSYS_NO_PATHCONV='1')


def docker(*args, timeout=600):
    return subprocess.run(['docker', *args], capture_output=True, text=True, encoding='utf-8', errors='replace',
                          timeout=timeout, env=ENV)


def mem_mb(text):
    m = re.match(r'([\d.]+)\s*([KMG]i?B)', text.strip())
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    return round(value * {'KiB': 1 / 1024, 'KB': 1 / 1000, 'MiB': 1, 'MB': 1, 'GiB': 1024, 'GB': 1000}[unit], 1)


class Sampler(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.samples, self.running = [], True

    def run(self):
        while self.running:
            out = docker('stats', '--no-stream', '--format', '{{.CPUPerc}}|{{.MemUsage}}', SERVER, timeout=30).stdout
            if '|' in out:
                cpu, mem = out.strip().split('|', 1)
                try:
                    self.samples.append((time.time(), float(cpu.rstrip('%')), mem_mb(mem.split('/')[0])))
                except ValueError:
                    pass
            time.sleep(1)


def window(samples, start, end):
    inside = [s for s in samples if start <= s[0] <= end]
    if not inside:
        return {}
    cpus, mems = [s[1] for s in inside], [s[2] for s in inside if s[2] is not None]
    return {'cpu_avg': round(sum(cpus) / len(cpus)), 'cpu_max': round(max(cpus)),
            'mem_start': mems[0] if mems else None, 'mem_end': mems[-1] if mems else None,
            'mem_max': max(mems) if mems else None, 'samples': len(inside),
            'mem_per_minute': [round(sum(m) / len(m), 1) for m in (
                [s[2] for s in inside if s[2] is not None and start + 60 * i <= s[0] < start + 60 * (i + 1)]
                for i in range(int((end - start) // 60))) if m]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--levels', default='100,500,1000,2000')
    ap.add_argument('--seconds', type=int, default=90)
    ap.add_argument('--ramp', type=int, default=30)
    ap.add_argument('--think', default='2,4', help='seconds a bot waits before acting: min,max')
    ap.add_argument('--cpus', default='1')
    ap.add_argument('--memory', default='1g')
    ap.add_argument('--save')
    args = ap.parse_args()

    pg_admin, why_not = tests.ensure_postgres()
    if not pg_admin:
        sys.exit(f"PostgreSQL container unavailable: {why_not}")
    version = subprocess.run(['git', 'rev-parse', '--short', 'HEAD'], cwd=ROOT, capture_output=True,
                             text=True).stdout.strip() or 'unknown'
    print(f"building {IMAGE} ({version}) ...", flush=True)
    build = docker('build', '--build-arg', f'APP_VERSION={version}', '-t', IMAGE, ROOT, timeout=1800)
    if build.returncode:
        sys.exit(build.stderr[-800:])

    _, database = tests.pg_database(pg_admin)
    docker('network', 'create', NETWORK)
    docker('rm', '-f', SERVER)
    sampler = Sampler()
    lines, report = [], []
    try:
        env = {'ENV': 'production', 'SECRET_KEY': secrets.token_hex(32), 'ALLOWED_ORIGINS': 'https://arena.example',
               'DATABASE_URL': f'postgresql+psycopg://dba:dbatest@host.docker.internal:55432/{database}',
               'REGISTER_LIMIT': '100000', 'LOG_FORMAT': 'json'}   # config.py's maximum
        run = ['run', '-d', '--name', SERVER, '--network', NETWORK, '--add-host=host.docker.internal:host-gateway',
               f'--cpus={args.cpus}', f'--memory={args.memory}']
        for k, v in env.items():
            run += ['-e', f'{k}={v}']
        started = docker(*run, IMAGE)
        if started.returncode:
            sys.exit(started.stderr)
        up = False
        for _ in range(60):
            probe = docker('exec', SERVER, 'python', '-c', "import urllib.request;"
                           "urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=2)", timeout=30)
            if probe.returncode == 0:
                up = True
                break
            if docker('inspect', '-f', '{{.State.Running}}', SERVER).stdout.strip() != 'true':
                break   # the server exited (e.g. a configuration error)
            time.sleep(1)
        if not up:
            logs = docker('logs', SERVER)
            sys.exit("The server did not come up:\n" + (logs.stdout + logs.stderr)[-1500:])
        idle = docker('stats', '--no-stream', '--format', '{{.MemUsage}}', SERVER).stdout.split('/')[0]
        print(f"server up (idle RAM {idle.strip()}); starting bots ...", flush=True)
        sampler.start()

        gen = subprocess.Popen(
            ['docker', 'run', '--rm', '--name', 'dba-load-bots', '--network', NETWORK, '--cpus=4',
             '-v', f"{os.path.join(ROOT, 'tools')}:/tools:ro", 'python:3.12-slim', 'sh', '-c',
             'pip install -q --disable-pip-version-check --root-user-action=ignore -r /tools/requirements-loadtest.txt '
             f'&& python -u /tools/loadtest.py --url http://{SERVER}:8000 --levels {args.levels} '
             f'--seconds {args.seconds} --ramp {args.ramp} --think {args.think}'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding='utf-8', errors='replace', env=ENV)
        for line in gen.stdout:
            line = line.strip()
            if not line.startswith('{'):
                if line and 'WARNING: Running pip' not in line:
                    print('  bots:', line[:200], flush=True)
                continue
            data = json.loads(line)
            lines.append(data)
            if data['phase'] == 'register':
                print(f"  registered {data['accounts']} accounts in {data['seconds']}s "
                      f"({data['per_second']}/s, {data['failures']} failures)", flush=True)
            elif data['phase'] == 'level':
                res = window(sampler.samples, data['start'], data['end'])
                data['server'] = res
                lat = data['latency_ms']
                print(f"  {data['players']:>5} bots ({data['connected']} connected): {data['turns_per_s']} turns/s, commit p50/p95/p99 "
                      f"{lat['commit_p50']}/{lat['commit_p95']}/{lat['commit_p99']} ms, CPU avg {res.get('cpu_avg')}% "
                      f"max {res.get('cpu_max')}%, RAM max {res.get('mem_max')} MB, server errors "
                      f"{data['server_errors']}, lost acks {data['lost_acks']}, drops "
                      f"{data['unexpected_disconnects']}, unanswered commits {data['unanswered_commits']}, generator CPU "
                      f"{data['generator_cpu']}%", flush=True)
        gen.wait()
    finally:
        sampler.running = False
        server_logs = docker('logs', SERVER).stdout + docker('logs', SERVER).stderr
        docker('rm', '-f', SERVER)
        docker('rm', '-f', 'dba-load-bots')
        docker('network', 'rm', NETWORK)
        tests.pg_database(pg_admin, create=False, name=database)

    errors = [l for l in server_logs.splitlines() if '"level": "ERROR"' in l]
    report.append(f"# Load test -- {time.strftime('%Y-%m-%d %H:%M')} -- git {version}")
    report.append("")
    report.append(f"Server: production image (gunicorn + gevent, 1 worker), production settings, PostgreSQL 16, "
                  f"JSON logs; limited to **{args.cpus} CPU / {args.memory} RAM**. Bots: tools/loadtest.py in a "
                  f"separate container, waiting {args.think.replace(',', '-')} s before each turn. {args.seconds} s measured "
                  f"per level after a {args.ramp} s ramp. Generator CPU near 100% (one process) would mean the "
                  f"latencies measure the bots, not the server.")
    report.append("")
    reg = next((l for l in lines if l['phase'] == 'register'), None)
    if reg:
        report.append(f"Registration burst: {reg['accounts']} accounts in {reg['seconds']} s = **{reg['per_second']}/s** "
                      f"({reg['failures']} failures) -- password hashing is deliberately slow.")
        report.append("")
    report.append("| Bots | Connected (start / end) | Turns/s | Commit p50 / p95 / p99 / max (ms) | Queue p95 | CPU avg / max | RAM start -> end (max) MB "
                  "| Server errors seen by bots | Lost acks | Unanswered commits | Drops | Generator CPU | Matches started / ended |")
    report.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|")
    for l in (x for x in lines if x['phase'] == 'level'):
        lat, s = l['latency_ms'], l.get('server', {})
        report.append(f"| {l['players']} | {l['connected']} / {l['connected_at_end']} | {l['turns_per_s']} | {lat['commit_p50']} / {lat['commit_p95']} / "
                      f"{lat['commit_p99']} / {lat['commit_max']} | {lat['queue_p95']} | {s.get('cpu_avg')}% / "
                      f"{s.get('cpu_max')}% | {s.get('mem_start')} -> {s.get('mem_end')} ({s.get('mem_max')}) | "
                      f"{l['server_errors']} | {l['lost_acks']} | {l['unanswered_commits']} | {l['unexpected_disconnects']} | "
                      f"{l['generator_cpu']}% | "
                      f"{l['matches_started']} / {l['matches_ended']} |")
    for l in (x for x in lines if x['phase'] == 'level' and x['seconds'] >= 600):
        report.append("")
        report.append(f"RAM per minute (MB, average) at {l['players']} bots: "
                      f"{', '.join(str(m) for m in l.get('server', {}).get('mem_per_minute', []))}")
    refusals = {}
    for l in (x for x in lines if x['phase'] == 'level'):
        for k, v in l['refusals'].items():
            refusals[k] = refusals.get(k, 0) + v
    report.append("")
    report.append(f"Refused actions (rule refusals, expected occasionally): {refusals or 'none'}")
    report.append(f"Server log: {len(server_logs.splitlines())} lines, {len(errors)} at ERROR level.")
    for e in errors[:5]:
        entry = json.loads(e)
        cause = (entry.get('exc') or '').strip().splitlines()[-1:]
        report.append(f"    {entry['ts']} {entry['msg'][:200]} -> {cause[0][:150] if cause else ''}")
    text = '\n'.join(report)
    print('\n' + text)
    if args.save:
        with open(args.save, 'w', encoding='utf-8') as fh:
            fh.write(text + '\n')


if __name__ == '__main__':
    main()
