# tests.py (full) -- 2026-11-24 20:19 -- git ded9859 + uncommitted changes

## Suites
| Suite | Result | PASS | FAIL | SKIPPED | Time |
|---|---|---|---|---|---|
| engine | ok | 229 | 0 | 0 | 0.5s |
| content | ok | 53 | 0 | 0 | 0.7s |
| config | ok | 71 | 0 | 0 | 10.7s |
| rate_limit | ok | 10 | 0 | 0 | 0.3s |
| migrations | ok | 17 | 0 | 0 | 9.7s |
| smoke | ok | 163 | 0 | 0 | 9.1s |
| browser | ok | 39 | 0 | 0 | 36.1s |
| runner_gates | ok | 19 | 0 | 0 | |

## Measurements
update-state per player (fixed 3v3 sample): 8606 bytes (baseline 8606)
engine: 0.277 ms per turn with 18 ticking statuses (baseline 0.255)
exploit probe: 1 confirmed, 35 not reproduced (6.4s)
    [CONFIRMED] reflect ignores attacker's invulnerability/defense
coverage (backend, tests excluded): 92% (baseline 92.0%)
lint (pyflakes): 3 issue(s) (baseline 3)
    backend\test_integration_smoke.py:94:47: f-string is missing placeholders
    backend\test_integration_smoke.py:543:19: f-string is missing placeholders
    tools\probe_exploits.py:128:1: 'inspect' imported but unused
real backend/game.db untouched: yes

## Verdict
ALL GREEN in 78s

Note: local run without PostgreSQL/container (Windows blocks psycopg's DLL, DEV-3). Those suites: GitHub Actions run 45282310917, green on the same commit (ded9859).
