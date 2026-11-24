# tests.py (full) -- 2026-11-24 21:28 -- git 3995316

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 53 | 0 | 0 | 0.6s |
| config | ok | 71 | 0 | 0 | 8.9s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 8.4s |
| smoke | ok | 194 | 0 | 0 | 10.3s |
| browser | ok | 39 | 0 | 0 | 35.3s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.280 ms per turn with 18 ticking statuses (baseline 0.255)
exploit probe: 1 confirmed, 37 not reproduced (7.3s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
  WARN  smoke: 31 new check(s) -- run --update-baseline to keep them
ALL GREEN in 76s

Note: local run without PostgreSQL/container (Windows blocks psycopg's DLL, DEV-3). Those suites: GitHub Actions run 45469641909, green on the same commit (3995316).
